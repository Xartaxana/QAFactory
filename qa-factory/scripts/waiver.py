"""Record a coverage gap the human accepted at a gate, in a form the next gate can read.

A gate decision was recorded as prose: `gates.A.decision` plus the answers verbatim in the
journal. That is enough for an auditor and useless to a check. On TP2-2381 the R-9
gap — no dedicated test for filter AND-composition — was put to the human at gate A,
reviewed, and accepted with "the approved scope is sufficient". Nothing carried that
decision forward, so at gate B `check_traceability.py` recomputed the same gap from the same
artifacts, `delivery_ready` came back no, and the factory went round test planning, case
design, case review, implementation, code review, reporting and documentation again to ask
the same person about the same gap.

  waiver.py --task QA-1 --gate A --requirement R-9 --decision "accepted: the approved scope
             is sufficient, no dedicated AND-composition test"
  waiver.py --task QA-1 --list          # one line per waiver in words a person reads (the gate packet's list)
  waiver.py --task QA-1 --list --json   # the same records as one JSON object, for code
  waiver.py --selftest

The entry lands in `pipeline.json` as `gate_waivers[]` — `{gate, requirement, decision, at,
by}` — and `check_traceability.py`, the ledger and `check_delivery.py` read it as a terminal
`deferred_by_decision` outcome with the human's own words as the detail.

A waiver exists only where a gate decision exists: without `gates.<gate>` in pipeline.json
this refuses, because then nobody was asked and this would be the factory excusing itself.

The second form is for a block that is not a gate. No check in the factory is allowed to be
one a person cannot pass with their word: a check stops a SILENT pass, never an informed one.

  waiver.py --task QA-1 --stage S1 --block "source material unavailable" \
            --decision "go on without the video and the external links"
  waiver.py --task QA-1 --stage S5 --block "*" --decision "<the person's words>"

lands in `pipeline.json` as `stage_overrides[]` — `{stage, match, decision, at, by}`.
`exit_gate.py`, `stage_done.py` and `stage_guard.py` (the dispatch path) drop every error of
that stage whose text contains `match` (`*` = all of them), journal what was passed over, and
gates A and B repeat it to the person. Only the orchestrator records one, and only with words
the person actually said: the pre-tool guard refuses this form from inside a role.

Before anything is written the block is held against the refusal that stands (t-722 C2-5, class
K4; the rule of t-722 L-7). The carrier is the driver's record `state/standing-refusal.json` of that
stage: only a record that holds lines or doors refuses a block that is in none of them, with those
lines as the closed options, because recording it would pass nothing and the step would stay
refused - see `block_standing`. The dispatch guard is an advisor: a block it refuses on is re-checked
after the record, but the guard alone refuses nothing (at gate A it always holds "gate A is not
approved"). Temporal edge: the driver writes the record when the seam is called for a refusal and erases
it when it is out of that refusal (C2-5s); with no record the refusal is silent and every block the guard
does not hold is recorded as `not verified`. After recording, this script prints `block lifted` or `block NOT lifted: <why>` only
for what the guard re-run checked (`recheck_stage_block`); every other block - the refusal's own door
included - prints `not verified`, naming the guard lines that still stand.

A person may also take a pass back — the stand they said to go on without is installed, or what
they accepted turned out to matter. Every state the factory records has a way out (FR-40), and
this is the one out of a passed block:

  waiver.py --revoke --task QA-1 --stage S1 --block "source material unavailable" \
            --decision "the video is attached now, read it"

The entry is not deleted: it keeps `revoked_at`, `revoked_by` and `revoked_decision`, so the
story still shows that the block was passed and when it stopped being. `split_overridden` stops
honouring it, which is what makes the check speak again.

The answer to a stand-gap card (`--block "stand gap: <id>"`) is the person's words as they were given;
the factory reads the FIRST WORD of them (`contract.stand_gap_decisions`: apply, theirs, handed or
accept - the word the driver writes first from the closed list in `references/question-vocabulary.json`).
After every stand-gap record this prints `stand gap <id> now reads: ...`, what the factory will act on,
so a record whose first word is none of the four is seen at once to be asked again.

A block of the form `protected test path: <folder/ or pattern>` is not a pass at all but a
PERMISSION: it lets the automator of this story write test files that match the pattern inside
`protected_app_paths` (never deletes, moves or shell writes; M15):

  waiver.py --task QA-1 --stage S5 --block "protected test path: src/tests/" --words-file <file>

`test_path_grants.pattern_errors` checks it first; a pattern that would open the boundary itself (or
is badly written, or lies in no protected folder) is refused and nothing is recorded. A pattern that
does not carry a usual test name is NOT refused (D-0030: the list of usual names is a suggestion):
it is recorded as the person said it and an advisory note is printed. The permission is for this
story only; to keep a place for every story the orchestrator records it in the config's
`test_locations` on the person's word (the line printed after the record names the door).
`--revoke` takes the permission back.

One block is not a stage error at all: `controller.py --operation next` answering
`wait_existing_job` for a dispatch nobody is doing. A `--block` naming it is routed to
`controller.py --operation release` for that dispatch — see `route_release`.

The third form records an answer that passes nothing and is simply worth keeping:

  waiver.py --remark --task QA-1 --stage S5 --text "the toolchain is theirs, not ours"

lands in `pipeline.json` as `remarks[]` — `{stage, text, at, by}` — which `gate_brief.py`
reads into the gate. A person who has already answered something must not be asked it again
two stages later; a remark is how the answer survives without pretending to be a decision.

In every form the person's words may come from a file instead of the command line:
`--words-file <path>` stands for `--decision` (the gate-requirement, `--stage` and `--revoke`
forms) and for `--text` (`--remark`). A command line cannot carry a multi-line text through
cmd.exe whole (TP2-2406, M30); `person_words.py` is the one reader, and inline words that
arrive through `run-py.cmd` are refused. The orchestrator writes the words as they were given to
`<story folder>/state/words/<name>.txt`.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detector_verdict as DV  # noqa: E402  (the one reader of a numbered list of problems: its `ITEM_RE`)
import person_owned  # noqa: E402  (the one reader of the question classes, RN1-9: `--why-person`)
from hooklib import (artifacts_dir, load_config, read_json, ref as reference_file, require_project,  # noqa: E402
                     resolve_app_root)

GATES = ("A", "B")
EXIT_BAD_ARGS = 2
EXIT_NO_PIPELINE = 4
EXIT_NO_GATE = 5
# A `<case>` or `RP-<profile>` in a block is the form's placeholder, not a word: nothing is named by it (GW1-1 P3/P4).
PLACEHOLDER_RE = re.compile(r"<[^<>]+>")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def apply_waiver(pipeline: dict, gate: str, requirement: str, decision: str, at: str,
                 by: str = "human") -> dict:
    """Append, or replace the one for the same requirement at the same gate. A human who
    revisits a decision replaces it; they do not accumulate two contradictory records."""
    waivers = pipeline.setdefault("gate_waivers", [])
    if not isinstance(waivers, list):
        waivers = pipeline["gate_waivers"] = []
    entry = {"gate": gate, "requirement": requirement, "decision": decision, "at": at, "by": by}
    for i, existing in enumerate(waivers):
        if not isinstance(existing, dict):
            continue
        if existing.get("gate") == gate and existing.get("requirement") == requirement:
            waivers[i] = entry
            return pipeline
    waivers.append(entry)
    return pipeline


def apply_stage_override(pipeline: dict, stage: str, match: str, decision: str, at: str,
                         by: str = "human") -> dict:
    overrides = pipeline.setdefault("stage_overrides", [])
    if not isinstance(overrides, list):
        overrides = pipeline["stage_overrides"] = []
    entry = {"stage": stage, "match": match, "decision": decision, "at": at, "by": by}
    klass, _why = record_class(match, stage)      # GW1-43: the data row says which blocks are a decision of a CLASS
    if klass:
        entry["class"] = klass
    for i, existing in enumerate(overrides):
        if isinstance(existing, dict) and existing.get("stage") == stage and existing.get("match") == match:
            overrides[i] = entry
            return pipeline
    overrides.append(entry)
    return pipeline


def revoke_stage_override(pipeline: dict, stage: str, match: str, decision: str, at: str,
                          by: str = "human") -> dict:
    """Mark a stage override as revoked — the sanctioned way out of a passed block (FR-40).

    A person's word passes any block, and a person may change their mind: the stand they said
    to go on without is installed, or what they accepted turned out to matter. Nothing could
    undo an override, so the only route was editing `pipeline.json` by hand, which is both
    unrecorded and exactly what this file exists to replace.

    Revoking does not delete: the entry stays, with `revoked_at` and the words said now, so the
    story's record still shows that the block was passed and when it stopped being passed.
    `split_overridden` stops honouring it, which is what makes the check speak again.
    """
    overrides = pipeline.get("stage_overrides")
    if not isinstance(overrides, list):
        return pipeline
    for existing in overrides:
        if not isinstance(existing, dict) or existing.get("stage") != stage:
            continue
        if match not in ("*", existing.get("match")) and existing.get("match") != match:
            continue
        existing["revoked_at"] = at
        existing["revoked_by"] = by
        existing["revoked_decision"] = decision
    return pipeline


def apply_remark(pipeline: dict, stage: str, text: str, at: str, by: str = "human") -> dict:
    """Append a person's answer as a remark. Unlike a waiver or an override it replaces
    nothing and passes nothing: two answers about the same stage are two facts, and the gate
    shows both. An identical repeat is dropped, so re-recording the same answer is harmless."""
    remarks = pipeline.setdefault("remarks", [])
    if not isinstance(remarks, list):
        remarks = pipeline["remarks"] = []
    entry = {"stage": stage, "text": text, "at": at, "by": by}
    if not any(isinstance(r, dict) and r.get("stage") == stage and r.get("text") == text
               for r in remarks):
        remarks.append(entry)
    return pipeline


def split_overridden(errors: list, pipeline: dict, stage: str) -> tuple[list, list]:
    """(still blocking, passed over by a person's word) for one stage's error list.

    A word passes a line when it is `*`, or names the line WHOLE (`contract.names_whole`: any case, whole identifiers - `R-3`
    does not pass a line about `BR-3`). The error direction is toward blocking, which asks the person again. A revoked
    override is history, not a pass (`contract.live_stage_overrides`, FR-40): it acts nowhere, `*` included. A `match` that
    holds a `<placeholder>` is no word and passes nothing, an old record on disk included (it was never a name)."""
    import contract
    overrides = [o for o in contract.live_stage_overrides(pipeline, (stage,))
                 if str(o.get("match") or "").strip() and not PLACEHOLDER_RE.search(str(o.get("match")))]
    if not overrides:
        return list(errors), []
    blocking, passed = [], []
    for error in errors:
        hit = next((o for o in overrides
                    if o["match"] == "*" or contract.names_whole(o["match"], error)), None)
        if hit:
            passed.append({"error": error, "decision": hit["decision"], "at": hit.get("at")})
        else:
            blocking.append(error)
    return blocking, passed


def recheck_stage_block(task: str, stage: str, match: str, revoked: bool = False) -> str:
    """After recording, ask the guard again: is that block actually gone?

    On TP1-15045 the person answered "Go on", this script wrote `stage_overrides[]` and
    printed OK — and the very next dispatch was refused, because `stage_guard` had never read
    `stage_overrides[]` at all. Everyone downstream believed the block was lifted. A silent OK
    over a standing block is its own defect, so the record is verified by re-running the
    checks, not by trusting that it was written."""
    remaining, failed = _guard_after_record(task, stage)
    if failed:
        return failed
    # The same reading the gate has (`_reads` = `split_overridden`): "block NOT lifted" says what the guard will say, so a
    # word `R-3` over a standing line about `BR-3` is no false alarm (GW1-1 P6a).
    still = _reads(remaining, stage, match)
    if revoked:
        # A revocation takes a pass back; it lifts nothing (t-722 N7). Same re-run, other words.
        if still:
            return f"pass taken back: the guard of {stage} refuses on it again: {still[0]}"
        return (f"pass taken back: the guard of {stage} does not refuse on it now; a check that refused "
                "at a step reads the revocation when that step runs again")
    if still:
        return ("block NOT lifted: " + still[0] +
                " — the override is recorded, but the guard still refuses. This is the "
                "factory's own defect, not yours; report it and do not edit the plugin.")
    if remaining:
        return ("block lifted; " + str(len(remaining)) + " other block(s) of " + stage +
                " still stand: " + remaining[0])
    return (f"block lifted: the guard of {stage} no longer refuses on it, and no other dispatch block of "
            f"{stage} stands")


# An ANSWER that does not let the story move is a block like any other. `next` replying
# `wait_existing_job` for a dispatch nobody is doing is the one TP1-15045 died on: the
# person said "it's dead, go on", this script recorded their words, printed OK — and `next`
# went on answering `wait_existing_job`, because a stage override passes stage ERRORS and a
# held dispatch is not one. A24 never caught it either, since "wait" was not written down as
# a refusal. The person's word has to reach the thing that is actually holding the story, so
# it is routed to the operation that releases the dispatch.
RELEASE_BLOCKS = ("wait_existing_job", "resume_checkpoint")


def _dispatches(task: str) -> dict:
    try:
        data = json.loads((artifacts_dir(task) / "state" / "controller.json")
                          .read_text(encoding="utf-8"))
        held = data.get("dispatches") if isinstance(data, dict) else None
        return {str(k): v for k, v in (held or {}).items() if isinstance(v, dict)}
    except Exception:
        return {}


def _dispatch_for(task: str, block: str) -> str:
    """The dispatch the person's words name, or "" — which leaves the choice to the
    controller, whose `release` knows the full set of states a dispatch can be freed from
    and says which ones are open when there is more than one."""
    dispatches = _dispatches(task)
    import contract
    named = [i for i in dispatches if i and contract.names_whole(i, block)]   # `S5-qa-automator-1` is not inside `-10`
    return named[0] if len(named) == 1 else ""


RUN_FAILED = 127           # `run_release` could not start the controller at all (the answer is why)


def run_release(task_root, dispatch: str, *, words: str = "", words_file: str = "", env=None) -> tuple:
    """THE one caller of `controller.py --operation release` outside the controller's own tests (t-722 §4.4, N4): `(exit code,
    the controller's answer)`. The person's words go by FILE (`words_file`, absolute or relative to the caller's cwd) or inline
    (`words`); `dispatch` empty leaves the choice to the controller. `env` is the CALLER'S child environment (the driver passes its own,
    UTF-8 included: the controller prints the person's words); None = this process's. `RUN_FAILED` when the controller could not be started."""
    argv = [sys.executable, "-B", str(Path(__file__).resolve().parent / "controller.py"),
            "--task-root", str(task_root), "--operation", "release"]
    argv += ["--words-file", str(words_file)] if words_file else ["--words", words]
    if dispatch:
        argv += ["--dispatch", dispatch]
    import subprocess
    try:
        done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120, env=env)
    except Exception as exc:
        return RUN_FAILED, f"could not run controller.py ({type(exc).__name__}: {exc})"
    return done.returncode, (done.stdout or done.stderr or "").strip()


def route_release(task: str, block: str, decision: str) -> str:
    """Run `controller.py --operation release` for the dispatch the block names (through `run_release`)."""
    dispatch = _dispatch_for(task, block)
    code, answer = run_release(artifacts_dir(task), dispatch, words=decision)
    if code == RUN_FAILED:
        return f"block NOT lifted: {answer}"
    if code != 0:
        if "unrecognized" in answer or "invalid choice" in answer:
            return ("block NOT lifted: this build of the factory has no `--operation release`. "
                    "Your word is recorded; what holds the story now is the factory's own "
                    "defect, not anything of yours — report it and do not edit the plugin.")
        return f"block NOT lifted: {answer[-400:]}"
    return (f"block lifted: {dispatch or 'the open dispatch'} released by the person's word "
            f"— {answer[-400:]}")


def is_stand_gap_block(match) -> bool:
    """Does this `--block` / `match` start `stand gap:` (`contract.STAND_GAP_MATCH_PREFIX`), case apart?"""
    import contract
    return _fold(match).startswith(contract.STAND_GAP_MATCH_PREFIX)


def stand_gap_reading(pipeline: dict, match: str) -> str:
    """`stand gap <id> now reads: <option> (<date>)` for a stand-gap block, else "".

    A person's answer to one card can be recorded at gate A (S5) and again at gate B (S9); what the
    factory will act on is what `contract.stand_gap_decisions` reads (the first word of the latest
    live record), not what this command just wrote. Printing that reading is how the orchestrator
    learns, at the moment of recording, that a record whose first word is none of the four is still
    "in your own words" and the card is asked again (FR-7). An unparseable date reads
    `an unrecorded date`."""
    import contract
    if not is_stand_gap_block(match):
        return ""
    gap_id = contract.stand_gap_id(match)
    name = gap_id or "(no id named after \"stand gap:\")"
    answer = contract.stand_gap_decisions(pipeline).get(gap_id) if gap_id else None
    if not answer:
        return f"stand gap {name} now reads: no answer"
    import test_path_grants
    when = test_path_grants.date_of(answer.get("at"))
    if answer.get("option"):
        return f"stand gap {gap_id} now reads: {answer['option']} ({when})"
    return (f"stand gap {gap_id} now reads: in your own words - the decision's first word is not one of "
            f"apply, theirs, handed, accept, so the card is asked again ({when})")


# --- the block against the refusal that stands (t-722 C2-5, class K4) -------------------------------------------
# cmp3 18:09: the conductor recorded `--block "window_record.py --review-receipt"` against a refusal that did not hold
# it; this script wrote the line and printed "block lifted", and the person was asked a third time. The writer knew no
# standing refusal except the two rules of the guard. Now the driver leaves the refusal it is handling in
# `<story folder>/state/standing-refusal.json`:
#   {"stage": "S5", "lines": ["<one problem, whole>", ...], "doors": ["<a block name the refusal printed>", ...]}
# and `block_standing` reads it, so nothing is recorded against a refusal this script does not hold. `doors` are the
# block names the refusal printed in its OWN door line (`... --block "no accepted controller stage" ...`): a door a
# refusal names has to be one its reader can use (FR-2), and the door line is cut from `lines` (it is not a problem),
# so the name travels apart. Nothing else reads the file.
STANDING_REFUSAL_FILE = "standing-refusal.json"
STANDING_UNREADABLE = "the driver's record of the standing refusal could not be read"
REFUSAL_LISTING_CEILING = 20

# The blocks the factory's own code writes and reads in pairs (K4-5): they are known by FORM and never held against
# the record. One definition: the callers take the NAME from here, they do not spell the literal (t-722 N5).
QUESTION_THRESHOLD_BLOCK = "question threshold"
MODE_SWITCH_BLOCK = "mode switch"
STAND_NOT_CONFIRMED_BLOCK = "stand not confirmed"
STAND_LOGIN_MISSING_BLOCK = "stand login missing"
OWN_FORM_BLOCKS = (QUESTION_THRESHOLD_BLOCK, MODE_SWITCH_BLOCK, STAND_NOT_CONFIRMED_BLOCK, STAND_LOGIN_MISSING_BLOCK)

# The door in backticks that ends a refusal line: ONLY a final span that IS a door - a command (`waiver.py --block ...`), so it holds
# `--` or `.py`. A span that is the problem's own text (a case id: ``... case `TC-3` ``) stays: two lines that differ only in it
# are two problems, and a block on one of them must not pass the other (t-842 F2, FR-4). The cost, named: a problem whose last span
# is a file name (``no test imports `helper.py` ``) is cut as a door, and two such lines differing only in that file name read as one.
_DOOR_TAIL = re.compile(r"\s*`[^`]*(?:--|\.py)[^`]*`\s*\.?\s*$")
_DOOR_NAME = re.compile(r"--block\s+(?:\"([^\"]+)\"|'([^']+)')")


def _squash(value) -> str:
    """The one whitespace fold of this script: runs of spaces, tabs and newlines become one space, the edges are cut."""
    return " ".join(str(value if value is not None else "").split())


def _fold(text) -> str:
    """`_squash` without case: how a block is compared with a name (a constant of the factory, a door)."""
    return _squash(text).lower()


def _strings(value) -> list:
    return [s.strip() for s in value if isinstance(s, str) and s.strip()] if isinstance(value, list) else []


def standing_path(task: str, root=None) -> Path:
    """The record's file. `root` is the story's folder when the caller already holds it (`stage_done` does: the folder whose
    pipeline it is closing); none reads the project's artifacts folder by the ticket, as every other reader does."""
    return (Path(root) if root is not None else artifacts_dir(task)) / "state" / STANDING_REFUSAL_FILE


def write_standing(task: str, stage: str, lines, doors, root=None) -> None:
    """THE writer of `state/standing-refusal.json` (HF8-22, L-E; AR-14): `{stage, lines, doors}`, the bytes the driver has always
    written. Two callers, one writer: `Driver.standing_refusal` (the refusal the seam is called for) and `stage_done.s9_exit` (a
    refusal of S9 with no driver on the skill road, where `waiver.py --block "report check"` read `unknown` for want of this
    file). The last refusal REPLACES the record. An OSError is the caller's to say (a record that could not be written is
    never judged against, and the step goes on)."""
    path = standing_path(task, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": stage, "lines": [str(line) for line in lines], "doors": [str(d) for d in doors]},
                               ensure_ascii=False, indent=2), encoding="utf-8")


def drop_standing(task: str, stage: str = "", root=None) -> None:
    """THE eraser of the record (FR-40). `stage` given: erased only when the record is of that stage (a closed S9 never
    erases the refusal of a stage the driver still holds), and a record that cannot be read is left as it is; none: erased
    whatever it holds (the driver's own eraser). No file is no work. An OSError is the caller's to say."""
    path = standing_path(task, root)
    if stage:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or str(data.get("stage") or "").strip().upper() != stage.strip().upper():
            return
    path.unlink(missing_ok=True)


def refusal_parts(lines) -> list:
    """A refusal's line(s) as the separate problems the reader judges, by FORM (no phrase list, FR-12): the hint is cut
    (`stage_guard.without_hint`), then ONE trailing door in backticks, then the `N) ` number, then the line is split at
    `"; "` (the controller joins its problems that way), edges stripped, empties and repeats dropped, order kept. The
    ONE normalisation: the driver builds the record's `lines` with it and `block_standing` applies it to the block, so
    a whole line the driver recorded matches itself."""
    import stage_guard
    parts = []
    for item in ([lines] if isinstance(lines, str) else list(lines or [])):
        text = DV.ITEM_RE.sub("", _DOOR_TAIL.sub("", stage_guard.without_hint(item), count=1).strip(), count=1)
        for part in text.split("; "):
            part = part.strip()
            if part and part not in parts:
                parts.append(part)
    return parts


def door_blocks(*texts) -> list:
    """The block names a refusal prints in its own doors (`--block "<name>"`), whole and in order. A placeholder
    (`--block "<part of the line>"`) and `*` are not names a person could record, so they are not doors."""
    found = []
    for text in texts:
        for hit in _DOOR_NAME.finditer(str(text if text is not None else "")):
            name = _squash(hit.group(1) or hit.group(2))
            if name and name != "*" and not re.search(r"<[^<>]*>", name) and name not in found:
                found.append(name)
    return found


def read_standing(task: str, stage: str) -> dict:
    """What the driver recorded about the refusal standing at `stage`: {"lines", "doors", "problem"}. No file, a record
    of another stage and a record with neither lines nor doors all read as empty; a file that cannot be read reads as
    empty with `problem` set (the caller says so; an unknown is not a refusal, FR-59); a record of another stage also
    reads as empty and its `problem` names that stage."""
    nothing = {"lines": [], "doors": [], "problem": ""}
    path = standing_path(task)
    # No file: the driver holds no refusal at this stage - `Driver.standing_refusal` writes the record when the seam is called for a
    # refusal with lines and `Driver.drop_standing` erases it when the driver is out of that refusal (t-722 §L-7, C2-5s). Nothing
    # to judge a block by, so it reads as empty: the block is recorded and reported "not verified" (an unknown is not a refusal).
    if not path.is_file():
        return nothing
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(nothing, problem=STANDING_UNREADABLE)
    if not isinstance(data, dict):
        return dict(nothing, problem=STANDING_UNREADABLE)
    recorded_for = str(data.get("stage") or "").strip().upper()
    if recorded_for != stage:
        return dict(nothing, problem=f"the driver's record of the standing refusal is of stage {recorded_for}, not {stage}"
                    if recorded_for else "")
    return {"lines": _strings(data.get("lines")), "doors": _strings(data.get("doors")), "problem": ""}


def _releases(match: str, decision: str = "") -> bool:
    """The block goes to the controller's `release` (`route_release`): the one condition `run_stage` routes by, the
    person's words included."""
    return any(name in f"{match} {decision}" for name in RELEASE_BLOCKS)


def _is_own_constant(match: str) -> bool:
    """The block IS one of the factory's own constants (`OWN_FORM_BLOCKS`): compared whole, case and spaces folded."""
    return _fold(match) in {_fold(b) for b in OWN_FORM_BLOCKS}


# --- the block NAMES a code reader acts on (conductor/4 C4-3) ------------------------------------------------------
# A block is held against the refusal that stands because one the refusal does not hold would pass nothing. A few blocks
# are not lines of any refusal: they are NAMES that a code reader recognises in `stage_overrides[]` (`keep it local` ->
# `external_writes.local_only_decision`, `executor unavailable: <profile>` -> `contract.handed_profiles`, `story budget` ->
# `story_budget.override`). Held against an unrelated record they were refused (`unmatched`) or recorded as unverified
# (`unknown`) although the reader was waiting for exactly that text; `--remark` is no way out, no reader reads it. The names
# are closed variety, so they are DATA (FR-13): `references/block-names.json`, one row per name - `block` (the whole text, or
# a fixed text with ONE `<placeholder>` at the end = a prefix that must be followed by a non-empty value), `reader`
# (`module:function` of `scripts/`, the code that recognises it) and `stages` (`S5`, ... or `*`). A table that cannot be
# read or holds a bad row is a refusal that names the file (FR-41, FR-59), never a pass and never a silent "no names".
BLOCK_NAMES_FILE = "block-names.json"
_NAME_READER = re.compile(r"^([a-z][a-z0-9_]*):([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?$")
_NAME_STAGE = re.compile(r"^(?:S\d|\*)$")
_NAME_PLACEHOLDER = re.compile(r"<[^<>]+>")
_NAME_SHAPE = '{"block": "<text>", "reader": "<module>:<function>", "stages": ["S5" | "*", ...]}'


class BlockNamesError(Exception):
    """`references/block-names.json` cannot be trusted; the message names the file, what is wrong and what is expected."""


def _reader_defined(source: str, name: str, method: str | None) -> bool:
    """`name` is a column-0 function of `source`; or, with `method`, `name` is a column-0 class of it and `method` an
    indented def inside that class body (which ends at the next column-0 `class `/`def `)."""
    if method is None:
        return bool(re.search(rf"^def {name}\(", source, re.MULTILINE))
    start = re.search(rf"^class {name}\b[^\n]*:[ \t]*$", source, re.MULTILINE)
    if not start:
        return False
    body = source[start.end():]
    end = re.search(r"^(?:class |def )", body, re.MULTILINE)
    body = body[:end.start()] if end else body
    return bool(re.search(rf"^    def {method}\(", body, re.MULTILINE))


def _name_row(n: int, row, scripts: Path) -> dict:
    """One validated row as the matcher reads it; raises BlockNamesError with the problem only (the loader adds the file)."""
    if not isinstance(row, dict):
        raise BlockNamesError(f"row {n} is not an object")
    text = _squash(row.get("block")) if isinstance(row.get("block"), str) else ""
    if not text:
        raise BlockNamesError(f"row {n}: key `block` must be a non-empty string")
    where = f"row {n} ({text})"
    holes = list(_NAME_PLACEHOLDER.finditer(text))
    if holes and (len(holes) > 1 or not text.endswith(holes[0].group(0)) or not text[:holes[0].start()].strip()):
        raise BlockNamesError(f"{where}: a `<placeholder>` may stand once, at the end, after a fixed text")
    reader = row.get("reader")
    hit = _NAME_READER.match(reader) if isinstance(reader, str) else None
    if not hit:
        raise BlockNamesError(f"{where}: key `reader` must be `<module>:<function>` of scripts/, got {reader!r}")
    try:
        source = (scripts / f"{hit.group(1)}.py").read_text(encoding="utf-8")
    except (OSError, ValueError):
        source = ""
    if not _reader_defined(source, hit.group(2), hit.group(3)):
        what = "no method of that class in" if hit.group(3) else "no function of"
        raise BlockNamesError(f"{where}: the reader `{reader}` is {what} scripts/{hit.group(1)}.py")
    stages = row.get("stages")
    if not (isinstance(stages, list) and stages and all(isinstance(s, str) and _NAME_STAGE.match(s) for s in stages)):
        raise BlockNamesError(f"{where}: key `stages` must be a non-empty list of stage ids (S5) or `*`, got {stages!r}")
    out = {"block": _fold(text), "prefix": _fold(text[:holes[0].start()]) if holes else "", "reader": reader,
           "stages": tuple(stages)}
    if "class" in row:
        # GW1-43: the decision of a CLASS - a person's word read as the answer for every instance of the class (optional key)
        if not (isinstance(row["class"], str) and row["class"].strip()):
            raise BlockNamesError(f"{where}: key `class`, when present, must be a non-empty string, got {row['class']!r}")
        out["class"] = row["class"].strip()
    return out


def load_block_names(path=None, scripts=None) -> list:
    """The rows of `references/block-names.json`, validated: [{block, prefix, reader, stages}]. Raises BlockNamesError when
    the file is absent, not JSON, not an object with a non-empty list `names`, or holds a bad row (a reader that is no
    function of scripts/ is a typo - the row is named)."""
    path = Path(path) if path is not None else reference_file(BLOCK_NAMES_FILE)
    scripts = Path(scripts) if scripts is not None else Path(__file__).resolve().parent
    head = f"references/{path.name} ({path}) cannot be used"
    table = read_json(path, None, kind=dict)
    rows = table.get("names") if table else None
    if not isinstance(rows, list) or not rows:
        raise BlockNamesError(f"{head}: it is absent, unreadable, not JSON, or has no non-empty list `names` of rows "
                              f"{_NAME_SHAPE}. Restore it from the plugin package.")
    out = []
    for n, row in enumerate(rows, 1):
        try:
            out.append(_name_row(n, row, scripts))
        except BlockNamesError as exc:
            raise BlockNamesError(f"{head}: {exc}. Expected rows {_NAME_SHAPE}. Fix that row or restore the file "
                                  "from the plugin package.") from None
    return out


def block_name_row(match: str, stage: str) -> dict | None:
    """The row of `references/block-names.json` this block IS, at this stage, or None. Whole text, case and spaces folded
    (a longer text that merely contains a name is no name); a prefix row needs ONE token after the prefix
    (`contract.prefix_value`: words are not an id the reader can look up; an unfilled `<placeholder>` is no value). `*` and
    an empty block never read the table (FR-4: `*` is legal always). Raises BlockNamesError for a table that cannot be trusted."""
    import contract
    text = _fold(match)
    if not text or text == "*":
        return None
    where = str(stage or "").strip().upper()
    for row in load_block_names():
        if "*" not in row["stages"] and where not in row["stages"]:
            continue
        if row["prefix"]:
            value = contract.prefix_value(text, row["prefix"])
            if value and not _NAME_PLACEHOLDER.fullmatch(value):
                return row
        elif text == row["block"]:
            return row
    return None


def record_class(match: str, stage: str) -> tuple:
    """`(class, why)` - the `class` of the block's row in `references/block-names.json` ("" when the row has none or the block is no
    name), and `why` ("" when the table was read): a table that cannot be read gives `("", <why>)`, never a raise, so the word is
    still recorded - without a class, which asks the person again later and passes nothing (FR-59). The ONE reader (AR-13) of
    that key: `apply_stage_override` stores it and `run_stage` says when it could not."""
    try:
        row = block_name_row(match, stage)
    except Exception as exc:        # BlockNamesError or any read error: the record is made, without a class
        return "", f"{type(exc).__name__}: {exc}"
    return (str(row.get("class") or "") if row else ""), ""


def _is_own_form(match: str, decision: str = "") -> bool:
    """Blocks known by FORM, never held against the record: a stand gap, a test-path permission, a block routed to the
    controller's `release` and the factory's own constants. No table is read here: these forms never wait on one (the
    names a code reader acts on are `block_name_row`, consulted by `block_standing` after this)."""
    import test_path_grants
    return (is_stand_gap_block(match) or test_path_grants.is_grant_block(match)
            or _releases(match, decision) or _is_own_constant(match))


def _guard_lines(pipeline: dict, stage: str) -> list:
    """The dispatch guard's lines for `stage`, each without its waiver hint. Raises when the guard cannot run: the caller
    says what that means."""
    import stage_guard
    return [stage_guard.without_hint(e) for e in stage_guard.dispatch_errors(pipeline, stage, journal=False)]


def _guard_after_record(task: str, stage: str) -> tuple:
    """(the guard's lines re-run on pipeline.json as written, "") or ([], the line that says it could not run): the one
    re-run `recheck_stage_block` and the texts of the kinds `door` and `unknown` read."""
    try:
        pipeline = json.loads((artifacts_dir(task) / "pipeline.json").read_text(encoding="utf-8"))
        return _guard_lines(pipeline, stage), ""
    except Exception as exc:
        return [], f"block not re-checked ({type(exc).__name__}: {exc}) — verify the stage by hand"


def _reads(lines: list, stage: str, match: str) -> list:
    """The lines the READERS' rule passes for this block (`split_overridden`: the block names the line by whole
    identifiers - `contract.names_whole`, any case, never a bare substring - and `*` = all)."""
    probe = {"stage_overrides": [{"stage": stage, "match": match, "decision": "x"}]}
    return [p["error"] for p in split_overridden(list(lines), probe, stage)[1]]


def _carrier_hits(lines: list, stage: str, match: str) -> list:
    """The record's lines the block passes, after the SAME normalisation of both sides: EVERY part of the block must
    pass some line (a block with no part - all code in backticks - passes none, so a word is never recorded over nothing)."""
    hits = []
    for part in refusal_parts(match):
        found = _reads(lines, stage, part)
        if not found:
            return []
        hits += [line for line in found if line not in hits]
    return hits


def block_standing(task: str, stage: str, match: str, pipeline: dict, decision: str = "") -> tuple:
    """(kind, lines, row): is this `--block` in the refusal that stands? Checked BEFORE anything is written. The order is
    positional - (a) a block known by form, or a name a code reader acts on, is never held against the record, (b) the
    guard is asked before the record so that "block lifted" is printed only for what the guard checked, (c) a refusal is
    possible only where the driver's record of THIS stage holds lines or doors (t-722 §L-7: the guard is an advisor, the
    record is the carrier; at gate A the guard always holds "gate A is not approved", so a guard alone would refuse the
    factory's own doors).
      own_form  - a block of the factory's own form, or a name a code reader acts on (`references/block-names.json`);
                  lines []; `row` = the table row the name matched (None for a form), so that `standing_report` does not
                  load the table a second time
      guard     - the guard refuses on it; lines = the guard's lines it passes
      door      - the block IS a door name the standing refusal printed (the refusal's own door); lines = the record's
                  lines it also passes (the kind wins over `carrier`)
      carrier   - every part of the block is in a line of the record; lines = those lines
      unmatched - the record holds lines or doors and the block is in none of it; lines = the standing lines (the
                  guard's and the record's), the closed options
      unknown   - no record of this stage holds anything (guard noise alone counts for nothing); lines []
    `row` is None for every kind but `own_form`. A table that cannot be trusted (BlockNamesError) can only mean "no name":
    it never refuses a block the table could not change - the chain goes on to the guard and the record. It is raised
    (the caller refuses, naming the file) only where the verdict is `unmatched` or `unknown`: there the table might have
    been the block's only way through."""
    if _is_own_form(match, decision):
        return "own_form", [], None
    broken = None
    try:
        row = block_name_row(match, stage)
    except BlockNamesError as exc:
        row, broken = None, exc
    if row:
        return "own_form", [], row
    kind, lines = _held_against_record(task, stage, match, pipeline)
    if broken and kind in ("unmatched", "unknown"):
        raise broken
    return kind, lines, None


def _held_against_record(task: str, stage: str, match: str, pipeline: dict) -> tuple:
    """(kind, lines) of `block_standing` for a block no form and no name accepts: the guard, then the driver's record."""
    try:
        guard = _guard_lines(pipeline, stage)
    except Exception:
        # A guard that cannot run holds nothing to judge by. After the record the kinds `guard`, `door` and `unknown`
        # re-run it and print "block not re-checked (...)"; `carrier` and `own_form` do not re-run it.
        guard = []
    hit = _reads(guard, stage, match)
    if hit:
        return "guard", hit
    held = read_standing(task, stage)
    if match.strip() == "*":       # legal always (FR-4): it passes every line there is, and is never refused
        return ("carrier", held["lines"]) if held["lines"] else ("unknown", [])
    if _fold(match) in {_fold(d) for d in held["doors"]}:
        return "door", _reads(held["lines"], stage, match)
    if held["lines"]:
        hit = _carrier_hits(held["lines"], stage, match)
        if hit:
            return "carrier", hit
    if held["lines"] or held["doors"]:
        return "unmatched", list(dict.fromkeys(guard + held["lines"]))
    # Remains (t-722 K4-NP3): with no driver there is no record of the standing refusal, so this command cannot check the block; it records the words and says "not verified", never "block lifted".
    return "unknown", []


def listed(items: list, more, bullet: bool = False) -> str:
    """`  1. <line>` (or `  - <line>`) per item, each whole, up to the ceiling; beyond it `  (+k more: <more>)`, `more`
    naming where the rest is read."""
    shown = [f"  {'-' if bullet else str(n) + '.'} {line}" for n, line in enumerate(items[:REFUSAL_LISTING_CEILING], 1)]
    if len(items) > REFUSAL_LISTING_CEILING:
        shown.append(f"  (+{len(items) - REFUSAL_LISTING_CEILING} more: {more})")
    return "\n".join(shown)


def unmatched_text(task: str, stage: str, match: str, options: list) -> str:
    """The refusal (stderr, exit 2) for a block that is in nothing that stands: a machine channel, FR-1 / FR-57 - what
    is wrong, what is expected (the standing lines and the doors the refusal printed, as closed options), and two doors
    (the exact line, or the words kept without a pass)."""
    import person_words
    path = standing_path(task)
    doors = read_standing(task, stage)["doors"]
    text = (f'waiver: the block "{match}" is in no line of the refusal standing at {stage}, so recording it would '
            f"pass nothing and the step would stay refused.")
    if options:
        text += ("\nExpected: --block set to one of these lines, whole or by whole words only that line contains:\n"
                 + listed(options, path))
    if doors:
        text += "\nOr the block name the refusal printed in its own door, whole:\n" + listed(doors, path, bullet=True)
    remark = person_words.door(f"waiver.py --task {task} --remark --stage {stage}")
    return (text + f"\nRecord again with that --block and the same words (--words-file <file>). If the person's words "
            f"pass none of these, keep them without a pass: {remark}. Nothing was recorded.")


def _also(stage: str, lines: list) -> str:
    return (f"it also passes {len(lines)} line(s) of the refusal standing at {stage}: "
            + "; ".join(lines[:REFUSAL_LISTING_CEILING]))


NOTHING_STANDING = ("not verified: no refusal of {stage} is known to this command (the driver records the refusal it is "
                    "handling; none is open now), so it cannot say the block is lifted. The check that refused reads the "
                    "word when the step runs again.")


def _guard_holds(task: str, stage: str, lines: list) -> list:
    """The guard's standing lines after the record, whole and numbered under the record's ceiling (the rest is what
    `stage_guard.py --ticket <T> --stage <S>` prints). A text silent on them would read as nothing standing (FR-41, FR-1)."""
    if not lines:
        return []
    return [f"the guard of {stage} holds {len(lines)} line(s), and the block passes none of them:",
            listed(lines, f"stage_guard.py --ticket {task} --stage {stage}")]


def _door_text(stage: str, match: str, doors: list, lines: list) -> list:
    """The kind `door`: the word is recorded on a name the refusal printed as its own door, so the pass is informed
    (FR-4) - but nothing here re-ran that check, and the record does not prove the refusal still stands, so it is
    `not verified`, never "block lifted" (FR-41, FR-59). The name is the record's own, whole."""
    name = next((d for d in doors if _fold(d) == _fold(match)), _squash(match))
    return ([f"recorded on the refusal's own door ({name}), the block the refusal standing at {stage} printed itself - "
             "not verified: the record does not re-run the check; that check reads the word when the step runs again."]
            + ([_also(stage, lines)] if lines else []))


def _unknown_text(task: str, stage: str, held: dict, standing: list) -> list:
    """The kind `unknown`. The old sentence ("none is open now") is true only where the guard re-run holds nothing and
    the record of this stage is empty; anywhere else the guard's lines, the record's problem or its doors are named, and
    the sentence says what this command does not know (FR-41)."""
    note, doors = held["problem"], held["doors"]
    if not (standing or note or doors):
        return [NOTHING_STANDING.format(stage=stage)]
    out = ([note] if note else []) + standing
    if doors:              # only `*` reaches here with doors: any other block is judged by them
        out += [f"the driver's record of {stage} holds no line, only the door(s) its refusal printed:",
                listed(doors, standing_path(task), bullet=True)]
        why = f"the record of {stage} holds doors only, no line to check the block against"
    elif note:
        why = f"there is no record of {stage} this command can read"
    else:
        why = f"the driver's record of {stage} is empty"
    return out + [f"not verified: {why} - the block is recorded, not verified. The check that refused reads the word "
                  "when the step runs again."]


def standing_report(kind: str, task: str, stage: str, match: str, lines: list, named: dict | None = None) -> list:
    """What `run_stage` prints once the block is recorded, by `kind` (see `block_standing`). "block lifted" is only ever
    what the guard re-run said (kind `guard`): this script cannot restart the check that refused, so every other kind
    says `not verified`, and the kinds `door` and `unknown` name what the guard re-run still holds. `named` is the table
    row `block_standing` matched: this report never loads the table (the block is already written by now)."""
    if kind == "guard":
        out = [recheck_stage_block(task, stage, match)]
        carried = _carrier_hits(read_standing(task, stage)["lines"], stage, match)
        return out + ([_also(stage, carried)] if carried else [])
    if kind == "carrier":
        return [f"recorded against the refusal standing at {stage}: the word is in {len(lines)} of its line(s):",
                listed(lines, standing_path(task)),
                "not verified: the check that refused judges each of its own lines when the step runs again; if it "
                "still refuses, that refusal comes back with the lines it still holds."]
    if kind in ("door", "unknown"):
        held = read_standing(task, stage)
        guard, failed = _guard_after_record(task, stage)
        standing = [failed] if failed else _guard_holds(task, stage, guard)
        if kind == "door":
            return _door_text(stage, match, held["doors"], lines) + standing
        return _unknown_text(task, stage, held, standing)
    if _is_own_constant(match):
        return [f"recorded for the step of the factory that asked for this word ({match}); it reads the word when "
                "it runs again"]
    if named:
        # A name its reader acts on (block-names.json): the record was not read for it. The guard re-run still speaks, so
        # a rehearsal door at gate A is not mistaken for a lift (t-782 M1).
        guard, failed = _guard_after_record(task, stage)
        return ([f"recorded under a block name the factory reads ({match}, read by {named['reader']}); it reads the word "
                 "when it runs again - not verified here, the standing refusal was not held against it."]
                + ([failed] if failed else _guard_holds(task, stage, guard)))
    # What is left is a stand-gap card (a permission and a release return in `run_stage` before this): its reading,
    # printed above, IS the result. The guard never refuses on a card, so a re-run line would only print "block lifted"
    # right after "the card is asked again" (t-782 m3).
    return []


def class_fields(classed) -> dict:
    """The keys a word carries for its class (RN1-9): `{}` when the word is not classified (nothing is written then, the record is
    exactly as before), else `why_person` (and `why_person_unchecked` when the class file could not be read to check it)."""
    return dict(classed) if isinstance(classed, dict) else {}


def run_revoke(task: str, stage: str, match: str, decision: str, by: str, classed=None) -> int:
    """Take a passed block back (FR-40). The record stays; the pass stops. `classed` (RN1-9): the class of the word, stamped on
    the entries this call revokes."""
    require_project("waiver")
    path = artifacts_dir(task) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline = pipeline if isinstance(pipeline, dict) else {}
    except Exception:
        pipeline = {}
    live = [o for o in (pipeline.get("stage_overrides") or [])
            if isinstance(o, dict) and o.get("stage") == stage and not o.get("revoked_at")
            and (match == "*" or o.get("match") == match)]
    if not live:
        print(f"waiver: {stage} has no live override matching [{match}] — nothing to revoke; "
              f"`waiver.py --task {task} --list` prints what this story has", file=sys.stderr)
        return EXIT_BAD_ARGS
    at = now_iso()
    revoke_stage_override(pipeline, stage, match, decision, at, by)
    for entry in pipeline.get("stage_overrides") or []:
        if isinstance(entry, dict) and entry.get("revoked_at") == at and entry.get("stage") == stage:
            entry.update(class_fields(classed))
    path.write_text(json.dumps(pipeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        import log_append
        record = log_append.build_record({"event": "human_answer", "task": task,
                                         "notes": f"{stage} override revoked [{match}]: {decision}"})
        if not log_append.validate(record):
            log_append.write([record])
    except Exception:
        pass  # the revocation is on disk; a journal hiccup must not undo a person's decision
    for entry in live:
        print(f"stage_overrides[] revoked: {stage} · {entry.get('match')} — was "
              f"\"{entry.get('decision')}\", now \"{decision}\"")
    reading = stand_gap_reading(pipeline, match)
    if reading:
        print(reading)
    print(recheck_stage_block(task, stage, match, revoked=True))
    return 0


NO_GAP_ID = ('waiver: "stand gap:" names no gap, so there is no card this answer belongs to and nothing would '
             'ever read it. Expected: the id of the card after "stand gap:" - a precondition id such as PC-1, '
             'a case key such as TC-7, or RP-<profile> for every test of a profile. Record again with '
             '--block "stand gap: <id>" and the person\'s words in a file (--words-file <file>), the file '
             'starting with their answer: "<apply | theirs | handed | accept> - the person wrote: <their '
             'words>". Nothing was recorded.')


def record_refusals(match: str) -> list:
    """What stops a NEW record of this block, in texts to print (empty = record it).

    A stand-gap record that names no gap is read by nobody (`contract.stand_gap_decisions` skips an
    empty id), so a person's answer would vanish: refused with what to give instead. A record of the
    form `protected test path: <p>` opens application code to the automator, so its pattern is checked
    by `test_path_grants.pattern_errors` before anything is written. Existing records of either kind
    stay as they are on disk.

    A block that still holds the form's placeholder (`probe gap: <case key>`, `RP-<profile>`) names nothing: it
    is refused with what is expected (the value in its place) and a door (GW1-1 P4). `*`, `stand gap:` and `protected
    test path:` keep their own branches above it. An old record with a placeholder stays on disk, passes nothing
    (`split_overridden`) and can still be revoked."""
    import contract
    import test_path_grants
    if is_stand_gap_block(match) and not contract.stand_gap_id(match):
        return [NO_GAP_ID]
    if test_path_grants.is_grant_block(match):
        cfg = load_config()
        return test_path_grants.pattern_errors(test_path_grants.pattern_of(match), cfg, resolve_app_root(cfg))
    if is_stand_gap_block(match) or str(match).strip() == "*":
        return []
    found = PLACEHOLDER_RE.search(str(match))
    if found:
        import person_words
        return [f'waiver: the block "{match}" still holds the placeholder {found.group(0)}, which names nothing, so recording it '
                f"would pass nothing. Expected: the real value in its place (the id of the test, the case or the profile the "
                f"person means). Record again with that --block and the same words. If the <...> is the refusal's own text, "
                f"give a part of the line without it. If the person's words name nothing "
                f"the check shows, keep them without a pass: "
                f"{person_words.door('waiver.py --task <T> --remark --stage <S>')}. Nothing was recorded."]
    return []


def record_stage_overrides(path, task: str, entries, by: str = "human", pipeline: dict | None = None, quiet: bool = False,
                           fields: dict | None = None) -> dict:
    """THE one place that stores a person's word over a block (AR-14, FR-8): applies every `(stage, match, decision)` of `entries`
    to `path` (a pipeline.json; `pipeline` is the dict the caller already read, else it is read here and raises OSError/ValueError
    when it is not an object), publishes the file by replace, and journals one `human_answer` line per entry - the line `brief_pack`
    hands every later brief as the person's standing instructions. A journal hiccup never undoes the stored word. The caller runs
    its own checks (`record_refusals`, `block_standing`) BEFORE this; they are not this function's business. Returns the pipeline.

    `fields` (GW1-40, the carry of a word to another key): `{(stage, match): {field: value}}` is laid over the record
    `apply_stage_override` made for that entry - the source's `at`, `carried_from`, `carried_at` and its `class` (which replaces the one
    the data row gave); a value of `None` removes the field. The journal line of an entry that carries `carried_from` says
    `carried from <key>`. Without `fields` nothing changes."""
    if pipeline is None:
        pipeline = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(pipeline, dict):
            raise ValueError("pipeline.json is not an object")
    at = now_iso()
    fields = fields or {}
    for stage, match, decision in entries:
        apply_stage_override(pipeline, stage, match, decision, at, by)
        extra = fields.get((stage, match)) or {}
        if extra:
            record = next(e for e in pipeline["stage_overrides"]
                          if isinstance(e, dict) and e.get("stage") == stage and e.get("match") == match)
            for field, value in extra.items():
                if value is None:
                    record.pop(field, None)
                else:
                    record[field] = value
    from event_store import atomic_json
    atomic_json(path, pipeline)
    try:
        import contextlib
        import io
        import log_append

        def carried(stage, match) -> str:
            origin = (fields.get((stage, match)) or {}).get("carried_from")
            return f" (carried from {origin})" if origin else ""
        records = [log_append.build_record({"event": "human_answer", "task": task,
                                            "notes": f"{stage} block passed by the person's word [{match}]: {decision}"
                                                     + carried(stage, match)})
                   for stage, match, decision in entries]
        # `quiet`: the caller's stdout is a JSON answer (the controller CLI); `log_append.write` prints its `OK: n event(s)` line there
        with (contextlib.redirect_stdout(io.StringIO()) if quiet else contextlib.nullcontext()):
            log_append.write([r for r in records if not log_append.validate(r)])
    except (Exception, SystemExit):      # `log_append.require_project` exits when the folder is no onboarded project
        pass  # the override is on disk; a journal hiccup must not undo a person's decision
    return pipeline


def run_stage(task: str, stage: str, match: str, decision: str, by: str, classed=None) -> int:
    require_project("waiver")
    refusals = record_refusals(match)
    if refusals:
        for text in refusals:
            print(text, file=sys.stderr)
        return EXIT_BAD_ARGS
    path = artifacts_dir(task) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline = pipeline if isinstance(pipeline, dict) else {}
    except Exception:
        pipeline = {}
    if not pipeline:
        print(f"waiver: no pipeline.json at {path} — an override belongs to a story that exists",
              file=sys.stderr)
        return EXIT_NO_PIPELINE
    try:
        kind, standing, named = block_standing(task, stage, match, pipeline, decision)
    except BlockNamesError as exc:
        # The table of names cannot say whether this block is one, and nothing else in the chain accepts it (a form, a
        # carrier, a door or the guard would have): neither a pass nor "not verified" (FR-41, FR-59).
        import person_words
        remark = person_words.door(f"waiver.py --task {task} --remark --stage {stage}")
        print(f'waiver: {exc}\nThe block "{match}" was not judged. Until it is restored, keep the person\'s words without '
              f"a pass: {remark}. Nothing was recorded.", file=sys.stderr)
        return EXIT_BAD_ARGS
    if kind == "unmatched":
        print(unmatched_text(task, stage, match, standing), file=sys.stderr)
        return EXIT_BAD_ARGS
    record_stage_overrides(path, task, [(stage, match, decision)], by, pipeline,
                           fields={(stage, match): class_fields(classed)} if classed else None)
    print(f"stage_overrides[]: {stage} · {match} — {decision}")
    _klass, no_class = record_class(match, stage)
    if no_class:
        # the word is on record, but the table of names could not say whether it is a decision of a class (FR-41)
        print(f"recorded without a class: {no_class}")
    reading = stand_gap_reading(pipeline, match)
    if reading:
        print(reading)
    import test_path_grants
    if test_path_grants.is_grant_block(match):
        # A permission, not a pass of a dispatch error: there is no block to re-check. The line says
        # what is open and, in the same breath, what is not.
        pattern = test_path_grants.pattern_of(match)
        print(f"protected test path: test files under '{pattern}' are open to the "
              f"automator of {task} from now on: \"{decision}\". Application code outside that pattern "
              "stays closed."
              f" To keep it for every story: the orchestrator shows the person what test_locations.py --check "
              f"--candidate '{pattern}' counts there and, on their word, records it in test_locations through "
              "project_decisions.py (references/conductor.md); this permission is then no longer needed.")
        cfg = load_config()
        for note in test_path_grants.pattern_notes(pattern, cfg, resolve_app_root(cfg)):
            print(note)
        return 0
    if _releases(match, decision):
        print(route_release(task, f"{match} {decision}", decision))
        return 0
    for line in standing_report(kind, task, stage, match, standing, named):
        print(line)
    return 0


# --- the carry of a person's words to a story under another key (GW1-40) ---------------------------------------------------------
#
# A story that moves to a new key (a local ticket that got a tracker key, an old key renamed) starts a new history with its own folder
# (S0 makes it); the person's earlier words stay in the old folder, which is not moved and not rekeyed. `waiver.py --carry-from <old key>
# --task <new key>` copies what the person said there - the live S0-S2 words and the words of a class - into the new history, each marked
# `carried_from`. The form of `pipeline.json`, `stage_overrides[]`, `state/words/` and `gap-classes.json` is unchanged; no function of the
# key form is called, so the command works the same before and after the local-key forms of S6 exist.
CARRY_STAGES = ("S0", "S1", "S2")


def _carry_overrides(old_pipeline, new_pipeline, old_key: str, carried_at: str) -> tuple:
    """`(entries, fields, lines)`: the words of the old history that this call carries, the fields `record_stage_overrides` lays over
    them, and one line per live old word that is NOT written (`already carried`, `kept yours`, `not carried`). Pure.

    Carried: a live word (`contract.live_stage_overrides`: never a revoked one, FR-40) that has a `class`, or is a word of S0-S2, and is
    not `*`. Not carried, with the line `not carried: <stage> · <block>`: every other live word (a pass of one case of a later stage means
    nothing for another story), and `*`. A word of the new history on the same `(stage, match)` wins: live and carried from here before
    -> `already carried` (the repeat adds nothing, `at` does not move); live and its own -> `kept yours` (it is newer by definition);
    taken back -> not carried, a revoked word does not come back. `at` stays the old one, so a carried word is never newer than the
    new history's own; the `class` is the source's (none when it has none: an old word does not become a class word by a data row);
    `carried_from` is the key the words were first said under (a word carried before keeps its origin)."""
    import contract
    own = [e for e in new_pipeline.get("stage_overrides") or [] if isinstance(e, dict)]
    live_own = {id(e) for e in contract.live_stage_overrides(new_pipeline)}
    wanted: dict = {}
    for src in contract.live_stage_overrides(old_pipeline):
        wanted[(str(src.get("stage") or ""), str(src.get("match") or ""))] = src
    entries: list = []
    fields: dict = {}
    lines: list = []
    for (stage, match), src in wanted.items():
        said = f"{stage} · {match}"
        klass = src.get("class") if isinstance(src.get("class"), str) and src.get("class").strip() else None
        if match.strip() == "*" or not (klass or stage in CARRY_STAGES):
            lines.append(f"not carried: {said}")
            continue
        origin = str(src.get("carried_from") or "").strip() or old_key
        same = [e for e in own if e.get("stage") == stage and e.get("match") == match]
        live = [e for e in same if id(e) in live_own]
        if live:
            lines.append((f"already carried: {said}" if any(str(e.get("carried_from") or "") == origin for e in live)
                          else f"kept yours: {said}"))
            continue
        if any(e.get("revoked_at") for e in same):
            lines.append(f"not carried: {said} (you took your word back in this story)")
            continue
        at = src.get("at") if isinstance(src.get("at"), str) and src.get("at").strip() else None
        entries.append((stage, match, str(src.get("decision") or "")))
        fields[(stage, match)] = {"at": at, "carried_from": origin, "carried_at": carried_at, "class": klass}
    return entries, fields, lines


def _carry_gap_classes(rows, new_root, new_key: str) -> tuple:
    """`(lines, code)`: each live row of the old history's `work/gap-classes.json` is written into the new one through
    `source_inventory.record_gap_class` (AR-14: its one writer), with the person's words and the question line they answered. A cause
    the table no longer holds (`ValueError`) is `not carried: gap class <cause>`; a row whose cause the new history already has
    live is `already recorded` (the earlier words stand); a cause the person TOOK BACK in the new history (a revoked row and no live one) is `not carried: gap class <cause> (you took your
    word back in this story)`, as a revoked stage word is (FR-40; the new file is read whole, `environment_record.load_rows`); a new file
    that cannot be read is a problem, printed, code 2, and nothing is written over it."""
    import environment_record
    import source_inventory as SI
    lines: list = []
    work = Path(new_root) / "work"
    if not work.is_dir():
        return ["not carried: no inventory yet"], 0
    output = work / "source-inventory.json"        # only `parent.parent` of it is used: the folder of the history
    own, _problem = environment_record.load_rows(SI.gap_classes_path(new_root), SI.GAP_CLASSES_KEY, SI.GAP_CLASSES_SCHEMA)
    taken_back = {str(r.get("cause")) for r in own if r.get("revoked_at")} - {str(r.get("cause")) for r in own if not r.get("revoked_at")}
    for row in rows:
        cause = str(row.get("cause") or "")
        if cause in taken_back:
            lines.append(f"not carried: gap class {cause} (you took your word back in this story)")
            continue
        try:
            written, already, problem = SI.record_gap_class(output, [cause], row.get("words"), row.get("shown"), new_key)
        except ValueError:
            lines.append(f"not carried: gap class {cause}")
            continue
        if problem:
            lines.append(f"waiver: {problem}. Expected: a readable work/{SI.GAP_CLASSES_FILE} in the new story. Repair or remove "
                         "that file, then run the same command again. The kinds of gap after this one were not carried.")
            return lines, EXIT_BAD_ARGS
        lines.extend(f"carried {r['id']}: {r['cause']}" for r in written)
        lines.extend(f"already recorded {r['id']}: {r['cause']}" for r in already)
    return lines, 0


def run_carry(task: str, old_key: str, carry_root, by: str) -> int:
    """`waiver.py --carry-from <old key> [--carry-from-root <folder>] --task <new key>`: copy a person's words from the story folder of
    `old_key` into the history of `task` (see the block above). `carry_root` is the folder that holds `<old key>/`; none means the
    project's artifact root. Every refusal says what is wrong, what was expected and the door, and writes nothing (FR-1): an old key that
    is no one folder name, the same key, a root that is no folder, an old folder that is not there, an old `pipeline.json` that cannot be
    read (an unreadable source is not "nothing to carry", AR-28), a new history with no `pipeline.json` (EXIT_NO_PIPELINE: the words belong to a
    story that exists). Exit 0 also for "nothing to carry" and for a partial carry whose lines say what was left."""
    require_project("waiver")
    from hooklib import artifact_root, is_one_component, is_story_folder

    def refuse(text: str, code: int = EXIT_BAD_ARGS) -> int:
        print(f"waiver: {text} Nothing was carried.", file=sys.stderr)
        return code
    key = str(old_key)
    if not key.strip() or key != key.strip() or ".." in key or not is_one_component(key):
        return refuse(f'--carry-from "{old_key}" is not the name of one story folder. Expected: the key of the earlier story, as its '
                      "folder is named (no slash, no `..`, not empty).")
    if key.casefold() == str(task).strip().casefold():
        return refuse(f"--carry-from {old_key} is the story --task names: words are not copied onto themselves. Expected: the earlier key.")
    try:
        base = Path(carry_root) if carry_root is not None else artifact_root()
        if not base.is_dir():
            return refuse(f"--carry-from-root {base} is not a folder. Expected: the folder that holds the earlier story's folder "
                          f"`{key}/`; leave the option out for the project's own artifacts.")
        old_root = base / key
        if not is_story_folder(base, key):
            return refuse(f"there is no story folder `{key}` under {base}. Expected: the earlier story's folder; when it was moved by hand "
                          f"(into `superseded/`, say), name the folder that holds it with --carry-from-root <folder>.")
        new_root = artifact_root() / str(task)
        if not is_one_component(str(task)):
            return refuse(f'--task "{task}" is not the name of one story folder.')
    except (OSError, ValueError) as exc:
        return refuse(f"the artifact root cannot be resolved ({exc}). Expected: a readable qa-factory/config.json.")
    new_path = new_root / "pipeline.json"
    new_pipeline = read_json(new_path, None)
    if not isinstance(new_pipeline, dict) or not new_pipeline:
        print(f"waiver: no pipeline.json at {new_path} - words are carried into a story that exists. Run the story's S0 for `{task}` first "
              "(`story_run.py --task <new key> ...`), then this command. Nothing was carried.", file=sys.stderr)
        return EXIT_NO_PIPELINE
    if new_root.resolve() == old_root.resolve():
        return refuse(f"--carry-from {old_key} names the folder of --task itself: words are not copied onto themselves.")
    old_path = old_root / "pipeline.json"
    old_pipeline = read_json(old_path, None)
    if not isinstance(old_pipeline, dict):
        return refuse(f"{old_path} cannot be read as a story record (missing, not JSON, or not an object), so what was said there is "
                      "unknown, not empty. Expected: the earlier story's own pipeline.json; repair it, or name the right folder with "
                      "--carry-from-root <folder>.")
    for side, pipe, path in (("earlier", old_pipeline, old_path), ("new", new_pipeline, new_path)):
        if pipe.get("stage_overrides") is not None and not isinstance(pipe.get("stage_overrides"), list):   # a present key of another shape is unknown, not empty (AR-28)
            return refuse(f"`stage_overrides` in the {side} story's {path} is not a list, so what was said there is unknown"
                          f"{'' if side == 'earlier' else ' and nothing can be stored beside it'}, not empty. Expected: a list of words; repair that "
                          "file (or restore it from the story's history), then run the same command again.")
    import source_inventory as SI
    entries, fields, lines = _carry_overrides(old_pipeline, new_pipeline, key, now_iso())
    classes, class_problem = SI.live_gap_classes(old_root)
    if class_problem:
        lines.append(f"not carried: gap classes: {class_problem}")
    if classes and (new_root / "work").is_dir():
        _rows, new_problem = SI.live_gap_classes(new_root)
        if new_problem:
            return refuse(f"{new_problem}. Expected: a readable work/{SI.GAP_CLASSES_FILE} in the new story, which is not written over. "
                          "Repair or remove that file, then run the same command again.")
    if not (entries or lines or classes):
        print(f"nothing to carry: {key} holds no word of a person that stands")
        return 0
    if entries:
        try:
            record_stage_overrides(new_path, task, entries, by, new_pipeline, fields=fields)
        except Exception as exc:        # nothing is printed as carried when nothing was stored
            print(f"waiver: the words could not be stored in {new_path} ({exc}). Nothing was carried.", file=sys.stderr)
            return EXIT_BAD_ARGS
        lines = [f"carried: {stage} · {match}" for stage, match, _decision in entries] + lines
    code = 0
    if classes:
        class_lines, code = _carry_gap_classes(classes, new_root, str(task))
        lines.extend(class_lines)
    for line in lines:
        print(line, file=sys.stderr if line.startswith("waiver:") else sys.stdout)
    return code


def run_remark(task: str, stage: str, text: str, by: str, classed=None) -> int:
    require_project("waiver")
    path = artifacts_dir(task) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline = pipeline if isinstance(pipeline, dict) else {}
    except Exception:
        pipeline = {}
    if not pipeline:
        print(f"waiver: no pipeline.json at {path} — a remark belongs to a story that exists",
              file=sys.stderr)
        return EXIT_NO_PIPELINE
    apply_remark(pipeline, stage, text, now_iso(), by)
    if classed:
        for entry in pipeline["remarks"]:
            if isinstance(entry, dict) and entry.get("stage") == stage and entry.get("text") == text:
                entry.update(class_fields(classed))
    path.write_text(json.dumps(pipeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        import log_append
        record = log_append.build_record({"event": "human_answer", "task": task,
                                          "notes": f"{stage} remark kept for the gate: {text}"})
        if not log_append.validate(record):
            log_append.write([record])
    except Exception:
        pass  # the remark is on disk; a journal hiccup must not lose the person's words
    print(f"remarks[]: {stage} — {text}")
    return 0


def run(task: str, gate: str, requirement: str, decision: str, by: str, classed=None) -> int:
    require_project("waiver")
    path = artifacts_dir(task) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline = pipeline if isinstance(pipeline, dict) else {}
    except Exception:
        pipeline = {}
    if not pipeline:
        print(f"waiver: no pipeline.json at {path} — a waiver belongs to a story that exists",
              file=sys.stderr)
        return EXIT_NO_PIPELINE
    gates = pipeline.get("gates") if isinstance(pipeline.get("gates"), dict) else {}
    recorded = gates.get(gate) if isinstance(gates.get(gate), dict) else {}
    if not str(recorded.get("decision") or "").strip():
        print(f"waiver: gate {gate} carries no decision in pipeline.json — record the gate "
              "first. A waiver is a person accepting a gap; without the gate nobody was "
              "asked, and this would be the factory excusing itself.", file=sys.stderr)
        return EXIT_NO_GATE
    apply_waiver(pipeline, gate, requirement, decision, now_iso(), by)
    if classed:
        for entry in pipeline["gate_waivers"]:
            if isinstance(entry, dict) and entry.get("gate") == gate and entry.get("requirement") == requirement:
                entry.update(class_fields(classed))
    path.write_text(json.dumps(pipeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"gate_waivers[]: {requirement} accepted at gate {gate} — {decision}")
    return 0


# The list a PERSON reads (t-363 B1, owner's rule t-342: a person is never shown a script name, a flag, an exit
# code or a dispatch id). `gate_text` printed this command's old lines straight into the gate packet:
# `stage S5 · waiver.py --task ... · <words> (human, <timestamp>)`. One list, two shapes: the words form is the
# DEFAULT of `--list`, `--json` is the machine form for code that reads the record.
# FR-13 DEBT (queued, t-363): these phrases are words the person reads, and waiver.py reads no data file for words (only
# stages.json for stage names and human-text.json for shapes), so they stay constants here until such a file exists.
GENERIC_BLOCK = "a check the factory ran"
EVERY_BLOCK = "every block at this stage"
STAND_GAP_BLOCK = "a gap in the stand that the gate's card named"
HANDED_BLOCK = "a test runner that could not be started on this stand"
PROTECTED_PATH_BLOCK = "test files you opened to the automator inside the application"
NOT_RECORDED = "not recorded"
NO_WORDS = "no words recorded"
WITHDRAWN = "(withdrawn)"


def stage_in_words(stage) -> str:
    """`Automation (S5)`: the stage's own name beside its id (human-questions.md: an internal stage name is never
    left alone). An id the stage table does not know, or a table that cannot be read, is shown as recorded."""
    text = _squash(stage)
    if not text:
        return NOT_RECORDED
    try:
        import hooklib
        for row in hooklib.load_ref_json("stages.json").get("stages") or []:
            if isinstance(row, dict) and row.get("id") == text and str(row.get("name") or "").strip():
                return f"{_squash(row['name'])} ({text})"
    except Exception:
        pass
    return text


def block_in_words(block) -> str:
    """The block as a person reads it, never as the factory keys it (t-373 F1-F3, the owner's rule).
    - A string that is a `refusal_registry` id is GENERIC_BLOCK: the registry's `refuses` text is written for a role (field
      names, state paths) and the registry has no field written for a person yet.
    - A stand-gap or handed-profile block (`contract.STAND_GAP_MATCH_PREFIX` / `HANDED_MATCH_PREFIX` + ONE token, the gap's
      or the profile's id) is said by a phrase, never by the key; the prefix followed by words is a phrase already.
    - A test-path permission (`protected test path: <folder/ or pattern>`, M15) is said by PROTECTED_PATH_BLOCK; the pattern
      follows after a colon only when `human_text.shape_problems` of the whole phrase is empty, and an empty pattern gives
      the phrase alone.
    - A stage code standing alone is said with the stage's name (`Triage (S7)`).
    - The owner's rule outranks the stored string: whatever still carries a shape `human_text` forbids in a question (a
      script name, a flag, an exit code, a dispatch id, an unexplained row id, a configuration key ...; the rules are DATA,
      references/human-text.json) - the packet's OWN check, the `question` rows - is replaced whole by GENERIC_BLOCK, and so
      is a string that cannot be checked."""
    text = _squash(block)
    if not text:
        return NOT_RECORDED
    if text == "*":
        return EVERY_BLOCK
    try:
        import contract
        import refusal_registry
        if any(isinstance(e, dict) and e.get("id") == text for e in refusal_registry.REGISTRY):
            return GENERIC_BLOCK
        for prefix, phrase in ((contract.STAND_GAP_MATCH_PREFIX, STAND_GAP_BLOCK), (contract.HANDED_MATCH_PREFIX, HANDED_BLOCK)):
            if contract.prefix_value(text, prefix):
                return phrase
        import human_text
        import test_path_grants
        if test_path_grants.is_grant_block(text):
            pattern = test_path_grants.pattern_of(text)
            whole = f"{PROTECTED_PATH_BLOCK}: {pattern}" if pattern else PROTECTED_PATH_BLOCK
            return PROTECTED_PATH_BLOCK if human_text.shape_problems(whole, kind="question") else whole
        text = re.sub(r"(?<![\w(-])S(\d)(?![\w-])", lambda m: stage_in_words("S" + m.group(1)), text)
        if human_text.shape_problems(text, kind="question"):
            return GENERIC_BLOCK
    except Exception:
        return GENERIC_BLOCK
    return text


def person_line(where: str, block, decision, at, withdrawn: bool = False) -> str:
    """`<stage> · <the block, in words> · your word: "<their words whole>" · <date>`, and `(withdrawn)` at the end
    of the line of a pass the person took back (FR-8: they see their own history; the record is never hidden). A
    missing key never raises: its slot reads `not recorded`, and missing words read `no words recorded`."""
    words = _squash(decision)
    day = _squash(at)[:10]
    line = " · ".join([where, block_in_words(block),
                       f'your word: "{words}"' if words else NO_WORDS,
                       day or NOT_RECORDED])
    return f"{line} {WITHDRAWN}" if withdrawn else line


def person_lines(pipeline: dict) -> list:
    """One line per recorded waiver, no cap: the stage overrides first, then the gate waivers. A record that is not
    an object is not a waiver and is skipped."""
    lines = []
    for o in [o for o in (pipeline.get("stage_overrides") or []) if isinstance(o, dict)]:
        lines.append(person_line(stage_in_words(o.get("stage")), o.get("match"), o.get("decision"), o.get("at"),
                                 withdrawn=bool(o.get("revoked_at"))))
    for w in [w for w in (pipeline.get("gate_waivers") or []) if isinstance(w, dict)]:
        gate = _squash(w.get("gate"))
        lines.append(person_line(f"gate {gate}" if gate else NOT_RECORDED, w.get("requirement"),
                                 w.get("decision"), w.get("at")))
    return lines


def show(task: str, machine: bool = False) -> int:
    path = artifacts_dir(task) / "pipeline.json"
    try:
        pipeline = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print(f"waiver: no readable pipeline.json at {path}", file=sys.stderr)
        return EXIT_NO_PIPELINE
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    if machine:
        print(json.dumps({"stage_overrides": [o for o in (pipeline.get("stage_overrides") or []) if isinstance(o, dict)],
                          "gate_waivers": [w for w in (pipeline.get("gate_waivers") or []) if isinstance(w, dict)]},
                         ensure_ascii=False, indent=2))
        return 0
    for line in person_lines(pipeline):
        print(line)
    return 0


def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    p = apply_waiver({}, "A", "R-9", "scope is sufficient", "T1")
    case("the waiver is recorded", len(p["gate_waivers"]), 1)
    case("with the human's words", p["gate_waivers"][0]["decision"], "scope is sufficient")
    case("and the gate", p["gate_waivers"][0]["gate"], "A")
    apply_waiver(p, "A", "R-4", "no UI check this story", "T2")
    case("a second requirement is appended", len(p["gate_waivers"]), 2)
    apply_waiver(p, "A", "R-9", "changed my mind: cover it", "T3")
    case("revisiting one replaces it, never duplicates", len(p["gate_waivers"]), 2)
    case("with the later decision",
         next(w for w in p["gate_waivers"] if w["requirement"] == "R-9")["decision"],
         "changed my mind: cover it")
    apply_waiver(p, "B", "R-9", "still accepted at delivery", "T4")
    case("the same requirement at another gate is its own record", len(p["gate_waivers"]), 3)

    o = apply_stage_override({}, "S1", "material unavailable", "go on without the video", "T1")
    case("a stage override is recorded", len(o["stage_overrides"]), 1)
    apply_stage_override(o, "S1", "material unavailable", "still go on", "T2")
    case("revisiting the same block replaces it", len(o["stage_overrides"]), 1)
    blocking, passed = split_overridden(
        ["source-inventory.json: source material unavailable: SRC-1",
         "context-manifest.json: ticket is required"], o, "S1")
    case("the named block is passed over", [p["error"] for p in passed],
         ["source-inventory.json: source material unavailable: SRC-1"])
    case("with the person's words", passed[0]["decision"], "still go on")
    case("and nothing else is", blocking, ["context-manifest.json: ticket is required"])
    case("another stage is untouched",
         split_overridden(["source material unavailable"], o, "S5")[0], ["source material unavailable"])
    case("an override without words passes nothing",
         split_overridden(["x"], {"stage_overrides": [{"stage": "S1", "match": "*", "decision": " "}]}, "S1")[0],
         ["x"])
    case("`*` passes every error of that stage",
         split_overridden(["a", "b"], apply_stage_override({}, "S4", "*", "ship it", "T1"), "S4")[0], [])

    r = apply_remark({}, "S5", "the toolchain is theirs, not ours", "T1")
    case("a remark is kept", len(r["remarks"]), 1)
    case("with the person's own words and the stage it answered",
         (r["remarks"][0]["stage"], r["remarks"][0]["text"], r["remarks"][0]["by"]),
         ("S5", "the toolchain is theirs, not ours", "human"))
    apply_remark(r, "S5", "the toolchain is theirs, not ours", "T2")
    case("recording the same answer twice keeps one", len(r["remarks"]), 1)
    apply_remark(r, "S5", "and we run without it", "T3")
    case("a second answer about the same stage is a second fact", len(r["remarks"]), 2)
    case("a remark passes no block", split_overridden(["the toolchain is not installed"], r, "S5")[0],
         ["the toolchain is not installed"])

    import contract as C
    case("the reader keys by requirement", sorted(C.waivers_by_requirement(p)), ["R-4", "R-9"])
    case("the latest gate wins for a requirement waived twice",
         C.waivers_by_requirement(p)["R-9"]["gate"], "B")

    # "it's dead, go on" has to reach the dispatch, not just pipeline.json.
    import tempfile
    import hooklib as _hl
    with tempfile.TemporaryDirectory(prefix="qa-factory-release-") as td:
        proj = Path(td)
        art = proj / "qa-factory" / "artifacts" / "QA-1" / "state"
        art.mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text('{"schema_version": 1}', encoding="utf-8")
        import os
        cached = _hl._PROJECT_ROOT_CACHE
        old_env = os.environ.get("CLAUDE_PROJECT_DIR")
        _hl.pin_project_root(proj)  # cache and env var both, the one selftest method (0.7.12)
        print(f"SELFTEST ROOT: {_hl.project_root()}")
        try:
            def controller(dispatches: dict) -> None:
                (art / "controller.json").write_text(json.dumps({"dispatches": dispatches}),
                                                     encoding="utf-8")

            case("release: `wait_existing_job` is one of the blocks that route here",
                 _releases("next says wait_existing_job"), True)
            controller({"S5-qa-code-critic-1": {"id": "S5-qa-code-critic-1", "status": "running"},
                        "S5-qa-automator-2": {"id": "S5-qa-automator-2", "status": "blocked"}})
            case("release: the dispatch the person's words name is the one released",
                 _dispatch_for("QA-1", "wait_existing_job on S5-qa-automator-2"),
                 "S5-qa-automator-2")
            case("release: naming none leaves the choice to the controller, which knows "
                 "every state a dispatch can be freed from",
                 _dispatch_for("QA-1", "next says wait_existing_job"), "")
            case("release: naming two leaves it there too",
                 _dispatch_for("QA-1", "S5-qa-code-critic-1 and S5-qa-automator-2 are dead"), "")
            (art / "controller.json").unlink()
            case("release: a story with no controller state names none",
                 _dispatch_for("QA-1", "wait_existing_job"), "")
            case("release: and the controller's refusal reaches the person",
                 route_release("QA-1", "wait_existing_job", "it's dead, go on")
                 .startswith("block NOT lifted"), True)

            # A remark has to come back out where the gate looks for it, not only go in.
            (art.parent / "pipeline.json").write_text("{}", encoding="utf-8")
            case("a remark needs a story that exists",
                 run_remark("QA-1", "S5", "run without the toolchain", "human"),
                 EXIT_NO_PIPELINE)
            (art.parent / "pipeline.json").write_text('{"task": "QA-1"}', encoding="utf-8")
            case("a remark is recorded",
                 run_remark("QA-1", "S5", "run without the toolchain", "human"), 0)
            import gate_brief
            case("and the gate brief reads it back",
                 [(x["stage"], x["text"]) for x in gate_brief.remarks(art.parent)],
                 [("S5", "run without the toolchain")])
            # RN1-9: the class key is written when given and absent when not
            case("a remark with a class is recorded",
                 run_remark("QA-1", "S5", "the stand is theirs", "human", classed={"why_person": "access"}), 0)
            kept = json.loads((art.parent / "pipeline.json").read_text(encoding="utf-8"))["remarks"]
            case("the class is written beside the words, and absent on a word without one",
                 [r.get("why_person") for r in kept], [None, "access"])

            # A pass has a way out (FR-40): the record stays, the pass stops, the check speaks.
            pipeline = {"task": "QA-1"}
            apply_stage_override(pipeline, "S1", "video", "go on without it", now_iso())
            case("an override passes the error it matches",
                 split_overridden(["source material unavailable: the video"], pipeline, "S1")[1] and
                 split_overridden(["source material unavailable: the video"], pipeline, "S1")[0], [])
            revoke_stage_override(pipeline, "S1", "video", "the video is attached now", now_iso())
            case("a revoked override passes nothing",
                 split_overridden(["source material unavailable: the video"], pipeline, "S1")[0],
                 ["source material unavailable: the video"])
            case("and the record of the pass is still there, with both sets of words",
                 [(o["decision"], o["revoked_decision"]) for o in pipeline["stage_overrides"]],
                 [("go on without it", "the video is attached now")])
            (art.parent / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
            case("revoking what nobody passed refuses, and says where to look",
                 run_revoke("QA-1", "S2", "*", "changed my mind", "human"), EXIT_BAD_ARGS)
        finally:
            _hl._PROJECT_ROOT_CACHE = cached
            if old_env is None:
                os.environ.pop("CLAUDE_PROJECT_DIR", None)
            else:
                os.environ["CLAUDE_PROJECT_DIR"] = old_env

    if failures:
        print("WAIVER SELFTEST: VIOLATIONS")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("WAIVER SELFTEST: no violations (append, replace, per-gate records, reader, "
          "stage overrides, revocation, remarks)")
    return 0


def _classed(ap, value):
    """`None` when `--why-person` is absent; else `{"why_person": <id>}` (plus `why_person_unchecked` when the class file cannot be read
    to check it - FR-59: the person's word is never refused for our data defect); a value that is no class exits 2 with the one
    sentence of `person_owned.class_rule` and the door `--why-person <id>` (m-3). Nothing is written yet (E-5)."""
    if value is None:
        return None
    norm = person_owned.normalize(value)
    if person_owned.status() != "ok":
        if not norm:
            ap.error("--why-person needs a class id and got an empty value. Expected: --why-person <id>, one of the classes of "
                     f"references/{person_owned.FILE_NAME} (the file cannot be read here, so the ids are not listed)")
        return {"why_person": norm, "why_person_unchecked": True}
    rule = person_owned.class_rule(value, "x", person_owned.WAIVER_DOOR)
    if rule:
        ap.error(rule)
    return {"why_person": norm}


def _noted(code: int, classed) -> int:
    """After a recorded word (exit 0): the one stdout line a word with no class, or an unchecked one, owes (RN1-9). The exit code stays."""
    if code == 0:
        if classed is None:
            print(f"not classified: this word answers no class of references/{person_owned.FILE_NAME} (--why-person <id>); "
                  "counted by person_owned.py --share")
        elif classed.get("why_person_unchecked"):
            print(f"class not checked: {person_owned.status()}; the word is recorded with `why_person` {classed['why_person']!r} as given")
    return code


def main() -> None:
    ap = argparse.ArgumentParser(description="record a coverage gap accepted at a gate")
    ap.add_argument("--task")
    ap.add_argument("--gate", choices=GATES)
    ap.add_argument("--requirement")
    ap.add_argument("--decision")
    ap.add_argument("--stage", help="a stage id (S0..S9): pass a block of that stage")
    ap.add_argument("--block", help="text of the blocking error to pass over, or * for all")
    ap.add_argument("--by", default="human")
    ap.add_argument("--remark", action="store_true",
                    help="keep a person's answer for the gate instead of re-asking it; "
                         "needs --task, --stage and --text. It passes no block.")
    ap.add_argument("--text", help="the person's own words, for --remark")
    ap.add_argument("--words-file", help="a file holding the person's own words as they were given "
                                         "(UTF-8; <story folder>/state/words/<name>.txt), instead "
                                         "of --decision (every form but --remark) or --text "
                                         "(--remark). A multi-line text, or one with quotes, goes "
                                         "here; inline words cannot cross the cmd launcher whole")
    ap.add_argument("--list", action="store_true",
                    help="print this story's waivers, one line each in words a person reads "
                         "(a story with none prints nothing); needs --task")
    ap.add_argument("--json", action="store_true",
                    help="with --list: the machine form - one JSON object with `stage_overrides` and "
                         "`gate_waivers` as recorded")
    ap.add_argument("--revoke", action="store_true",
                    help="take a stage override back: needs --task, --stage, --block and "
                         "--decision (why, in the person's words). The entry stays, marked "
                         "revoked, and the check it was passing speaks again.")
    ap.add_argument("--carry-from", help="the key of an earlier story: copy the person's words said there (its live S0-S2 words and the "
                                          "words of a class) into --task, marked `carried_from`. Needs --task; no other form with it")
    ap.add_argument("--carry-from-root", help="with --carry-from: the folder that holds the earlier story's folder, only when it was "
                                               "moved by hand (default: the project's artifacts)")
    ap.add_argument("--why-person", help=f"the class of references/{person_owned.FILE_NAME} this word answers - what only a person decides "
                                         "(access, money, risk, ...); recorded beside the words")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.why_person is not None and (ns.list or ns.json or ns.carry_from is not None or ns.carry_from_root is not None or ns.selftest
                                      or not (ns.stage or ns.block or ns.gate or ns.remark or ns.revoke)):
        ap.error("--why-person goes with a recording form (--stage/--block, --gate, --remark, --revoke)")
    if ns.selftest:
        sys.exit(selftest())
    if ns.carry_from is not None or ns.carry_from_root is not None:
        # one form: the words are the earlier story's, so no other option may ride along (a `--decision` given here would be lost silently)
        mixed = [flag for flag, given in (("--stage", ns.stage), ("--block", ns.block), ("--revoke", ns.revoke), ("--remark", ns.remark),
                                          ("--gate", ns.gate), ("--requirement", ns.requirement), ("--decision", ns.decision),
                                          ("--text", ns.text), ("--words-file", ns.words_file), ("--list", ns.list), ("--json", ns.json))
                 if given]
        if mixed:
            ap.error(f"--carry-from is a form of its own and does not combine with {', '.join(mixed)}. Expected: "
                     "waiver.py --carry-from <old key> [--carry-from-root <folder>] --task <new key>")
        if ns.carry_from is None or not ns.task:
            ap.error("--carry-from-root goes with --carry-from, and the form needs --task: "
                     "waiver.py --carry-from <old key> [--carry-from-root <folder>] --task <new key>")
        sys.exit(run_carry(ns.task, ns.carry_from, ns.carry_from_root, ns.by))
    if ns.json and not ns.list:
        ap.error("--json is the machine form of --list")
    if ns.list:
        if not ns.task:
            ap.error("--list needs --task")
        sys.exit(show(ns.task, machine=ns.json))
    # The person's words are resolved ONCE, here, before any pipeline.json is read or written: a
    # refusal leaves no override, no waiver, no remark and no journal line. `--words-file` is the
    # file form of whichever option carries the words in this form: `--text` for --remark,
    # `--decision` for the gate-requirement, --stage and --revoke forms. Strip stays this
    # file's own rule for what is recorded.
    import person_words
    flag = "--text" if ns.remark else "--decision"
    try:
        words = person_words.read(ns.text if ns.remark else ns.decision, ns.words_file, flag)
    except person_words.WordsRefused as exc:
        ap.error(str(exc))
    classed = _classed(ap, ns.why_person)    # BEFORE any pipeline.json read or write (E-5): a refusal leaves the words in state/words/
    if ns.remark:
        if not (ns.task and ns.stage and str(words or "").strip()):
            ap.error("--remark needs --task, --stage and --text or --words-file (the person's words)")
        sys.exit(_noted(run_remark(ns.task, ns.stage.upper(), words.strip(), ns.by, classed), classed))
    if ns.revoke:
        if not (ns.task and ns.stage and ns.block and str(words or "").strip()):
            ap.error("--revoke needs --task, --stage, --block and --decision or --words-file "
                     "(why, in their words)")
        sys.exit(_noted(run_revoke(ns.task, ns.stage.upper(), ns.block.strip(), words.strip(), ns.by, classed), classed))
    if ns.stage or ns.block:
        if not (ns.task and ns.stage and ns.block and str(words or "").strip()):
            ap.error("--task, --stage, --block and --decision or --words-file (the person's words) "
                     "are all required")
        sys.exit(_noted(run_stage(ns.task, ns.stage.upper(), ns.block.strip(), words.strip(), ns.by, classed), classed))
    if not (ns.task and ns.gate and ns.requirement and words):
        ap.error("--task, --gate, --requirement and --decision or --words-file are all required")
    sys.exit(_noted(run(ns.task, ns.gate, ns.requirement, words.strip(), ns.by, classed), classed))


if __name__ == "__main__":
    main()
