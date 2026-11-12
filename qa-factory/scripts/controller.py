"""Task-scoped lifecycle API. No model invocation or external write is implicit.

Usage: controller.py (--task KEY | --task-root PATH) --operation OP --input request.json
--task KEY names the story by its ticket key (the folder of that name under the artifact root,
matched letter for letter); --task-root PATH gives the folder itself. Exactly one of them; flags
are never abbreviated (`--task` is not short for `--task-root`). The folder must exist: the
controller never creates a story folder (S0 does), and on a folder with no state/events.jsonl
only `initialize` (once S0 wrote its pipeline.json) and `prepare` act; the rest are refused.
OP is initialize, dispatch, checkpoint, accept, decision, invalidate, next, stage-scope
(read-only S5/S6 scope from the approved plan) or recover (self-repair of internal state).
Consumers use next_action and receipts rather than hand-editing pipeline state.

Three operations build their own request, so nobody reverse-engineers this file's shape
from a prompt (TP1-15045: three minutes of `sed -n 1055,1230p` and two rejected
hand-written decisions before Gate A could be recorded):
  --operation gate-decision --gate A --words-file <path> [--build-only]
  --operation rework --stage S4 --role qa-case-designer --cases TC-012,TC-014
      --reason "<why>" [--rows TS-3] [--purpose repair_verify] [--build-only]
      [--cause test_defect|mechanical|environment|tooling|reviewer_error|question_answer|source_arrived|ticket_changed]
  --operation gate-preflight --gate A     (read-only rehearsal, gate_preflight.run)

One more takes only a person's word, because a dispatch nobody is doing must never outlive it:
  --operation release --dispatch S3-qa-test-strategist-2 --words-file <path>
(the person's words as they were given, in a UTF-8 file; inline `--words "<one line>"` is for a
single line typed by code and is refused through run-py.cmd - see person_words.py)

A role that stopped resumes in one step: `next` and `recover` carry the ready retry packet
(`retry_packets`), and it is dispatched as it stands with `--operation dispatch --input`.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import time

import event_store
from event_store import (DerivedViewStale, EventCommitted, EventStore, IdempotencyKeyReused, StateConflict, atomic_json,
                         content_hash, retry_shared, shared_file)
from hooklib import (CLOSED_AT, ORDERS_DUE, REOPENED_AT, STOP_VALUES, gate_orders, load_config, sorted_paths,
                     story_closed, story_closure, story_root, story_root_at)
import person_words
from record_schema import validate_record
from runtime_policy import (DEFAULT_LIMITS, resolve_model, checkpoint_due, cumulative_budget,
                            warning_milestones, orchestrator_rollover_due)

TERMINAL = {"accepted", "blocked", "incomplete", "paused"}
PURPOSES = {"initial", "repair_verify", "red_probe", "diagnostic",
            "flaky_diagnostic", "build", "collect", "manual", "quality", "s3_labelling", "s5_plan",
            "investigation",
            # t-2181 PC-6 / t-2277: three words of a dispatch's purpose, each the reader of one new road. `bind` - the S5 round
            # after code arrived (its S5 record reads `window` through `s5_part_of`, which knows only `s5_plan`); `reference_walk` -
            # the S1 walk of the older version (PC-9b sends it); `first_look` - the S1 look at the new version (FL-6 sends it).
            # PC-6 owns the words, the senders are PC-7, PC-9b and FL-6 (AR-1: a closed set is data, one writer).
            "bind", "reference_walk", "first_look"}
# Window 1 of S3 (G1-11): the strategist labels `work/grounding.yaml` and writes no plan. The word is written at dispatch time into
# `request_binding.purpose` and read ONLY through `s3_window_of`; `PURPOSES` is the closed set (AR-1).
S3_LABELLING = "s3_labelling"
# The first look at the new version (t-2277 FL-5): an OPTIONAL qa-runner dispatch of S3 (`stages.json` S3 `optional_dispatches`) that walks
# the register's requirements before any plan exists. It runs no half of the plan, so it names no `execution_kind` and no case.
FIRST_LOOK = "first_look"
# The reference walk (t-2181 PC-9b): the OPTIONAL qa-runner dispatch of S1 (`stages.json` S1 `optional_dispatches`) that walks the OLD version of a side
# on its reference stand. Same shape as the first look: no plan, so no `execution_kind`; `runner_kind_required` admits it by its row, not by this word.
REFERENCE_WALK = "reference_walk"


def runner_kind_required(state, role, purpose) -> bool:
    """Does a qa-runner request of this story have to say which half it runs (`execution_kind` manual / automation)? THE one predicate of
    `prepare` and `apply` (AR-13): true for a qa-runner in the new plan-contract mode, EXCEPT an optional dispatch - one whose purpose is
    exactly the `purpose` of an `optional_dispatches` row of `stages.json` that names this role (the first look of S3, the reference
    walk of S1; read through `stage_guard.optional_purposes`, AR-1: the words are data) has no plan to be a half of. Error direction:
    toward the refusal - any other purpose, an absent one, a non-mapping state, a role that is not the runner, or a row table that
    cannot be read keeps today's answer. Pure up to reading `stages.json`; never raises."""
    if role != "qa-runner" or not isinstance(state, dict) or state.get("plan_contract_mode") != "new":
        return False
    try:
        import stage_guard
        optional = stage_guard.optional_purposes(stage_guard.stage_model(), role)
    except Exception:
        optional = set()
    return not (isinstance(purpose, str) and purpose in optional)


def s3_window_of(record) -> str:
    """`"labelling"` or `"exit"`: which window of S3 a dispatch RECORD is. `"labelling"` ONLY when the record is a mapping of stage
    S3 whose `request_binding` is a mapping whose `purpose` is exactly `S3_LABELLING`; EVERYTHING else is `"exit"` (a plan is owed, the
    behaviour before the windows). The word is read from `request_binding`, never from the top of the record (a checkpoint or an
    acceptance overwrites the top). Error direction: only toward `exit`. Pure; never raises."""
    if not isinstance(record, dict) or record.get("stage") != "S3":
        return "exit"
    binding = record.get("request_binding")
    if isinstance(binding, dict) and binding.get("purpose") == S3_LABELLING:
        return "labelling"
    return "exit"


# The S5 plan dispatch (SC1-14): ONE dispatch of the author (and one of the critic) written against EVERY case of the stage, before
# any window. The word is written at dispatch time into `request_binding.purpose` and read ONLY through `s5_part_of`; `PURPOSES`
# is the closed set (AR-1). The twin of `S3_LABELLING` / `s3_window_of`, with one more reader: a REQUEST that is not yet a record.
S5_PLAN = "s5_plan"
# The three words of a person that pass the plan-order refusals (P13). A recorded word passes a refusal whose LINE contains it
# (`waiver` matches by whole words, `contract.names_whole`), so no word is a whole-word part of another and a refusal's line carries its own word only (the doors,
# which name the others, are appended after the match).
WORD_PLAN_BEFORE_WINDOWS = "plan before windows"
WORD_PLAN_FORM_SWITCH = "plan form switch"
WORD_PLAN_REVIEW_ROUND = "plan review round"
# t-1937 TR3-4: the person's word that passes the backstop refusal of an S5 completion beside a running window (P13). Its own words:
# no other word of this block is a whole-word part of it.
WORD_CLOSE_BESIDE_RUNNING = "close beside a running window"
WORD_CLOSE_BESIDE_RUNNING_LANE = "close beside a running lane"   # the S6 twin: a manual lane, not a window (P9)
S5_PLAN_ROLES = ("qa-automator", "qa-code-critic")
# t-1937 TR3-4: the roles whose S5 WINDOW dispatches may run beside each other (`Controller._window_beside_running`). The two roles
# of a window's chain; every other role, stage or plan dispatch keeps the rule "one running dispatch" (AR-1: closed variety is data).
S5_WINDOW_ROLES = ("qa-automator", "qa-code-critic")


def s5_part_of(item) -> str:
    """`"plan"` or `"window"`: which kind of S5 dispatch an `item` is. `"plan"` ONLY when `item` is a mapping of stage S5 whose
    purpose word is exactly `S5_PLAN`; EVERYTHING else is `"window"` (the behaviour of every reader before the plan existed).

    Where the word is read: from `item["request_binding"]` when the item HAS that key (a dispatch RECORD: the binding is a mapping
    or it is nothing, and the top of the record is never read - `checkpoint`/`accept` overwrite it, `Controller.apply`); from
    `item["purpose"]` when the item has NO `request_binding` key (a REQUEST not yet a record - `request_binding()` builds the
    binding from this very key; also an imported record, which cannot be older than 0.10.3: before it `validate` refused the word).

    Error direction: only toward `window`. On every record the controller writes the function is exact; on a crooked input
    (a binding that is a list or a string, no stage, `"S5 "`, not a mapping) it answers `window`, so a reader reads the record as
    it did before the node. Pure; never raises."""
    if not isinstance(item, dict) or item.get("stage") != "S5":
        return "window"
    if "request_binding" in item:
        binding = item["request_binding"]
        word = binding.get("purpose") if isinstance(binding, dict) else None
    else:
        word = item.get("purpose")
    return "plan" if word == S5_PLAN else "window"


def s7_part_of(item) -> str:
    """`"investigation"` when `item` is a mapping of stage S7 whose purpose word is exactly `investigation`, else `""`.
    The word is read from `item["request_binding"]` when the item HAS that key (a dispatch record), else from `item["purpose"]`
    (a request not yet a record) - the `s5_part_of` rule. Crooked input answers `""`. Pure; never raises."""
    if not isinstance(item, dict) or item.get("stage") != "S7":
        return ""
    if "request_binding" in item:
        binding = item["request_binding"]
        word = binding.get("purpose") if isinstance(binding, dict) else None
    else:
        word = item.get("purpose")
    return "investigation" if word == "investigation" else ""


def lineage_root(records: dict, identifier: str, keys: tuple) -> str:
    """The root of the chain `identifier` belongs to: follow the first of `keys` whose value names a record, step first, then stop
    on a revisit (returning the revisited name). An unknown identifier, an unknown target or a non-dict record stops the walk."""
    seen = {identifier}
    name = identifier
    while isinstance(records, dict) and isinstance(records.get(name), dict):
        named = next((str(records[name].get(key) or "") for key in keys
                      if str(records[name].get(key) or "") in records), None)
        if named is None:
            break
        name = named
        if name in seen:
            break
        seen.add(name)
    return name


# A dispatch receipt whose agent was never launched. The hook on `Agent` refused the call
# after the receipt was already written, so the story waited forever on a job nobody was
# doing (TP1-15045, `wait_existing_job` with `cancel_allowed: false`). It is not a
# stopped dispatch — there is no checkpoint to resume — and it spends nobody's repair cap.
NEVER_STARTED = "never_started"
# A dispatch whose role started and stopped without its work being accepted. The role's
# return is a FACT (the SubagentStop hook records it); accepting the evidence, recording the
# block or sending the work back stays with the orchestrator. TP2-2523: the role
# stopped with a refusal, nothing recorded the return, and the story waited on
# `wait_existing_job` with `cancel_allowed: false` while a person's word freed nothing.
RETURNED = "returned_unaccepted"
# A dispatch whose agent stopped writing to its transcript long before any threshold.
ABANDONED = "abandoned"
# A dispatch a person's recorded word freed. Artifacts stay, the stage is startable again.
RELEASED = "released_by_person"
# Closed, but the role's own work still counts as a round of that window.
SETTLED = {RETURNED, ABANDONED}
# A dispatch whose role stopped with a checkpoint: the work is paused, not finished, and a
# retry that inherits that checkpoint is how it goes on (`_retry_packet`).
STOPPED = {"blocked", "paused", "incomplete"}
# The one stop a retry does not answer: the validator refuses to resume it, so no packet is
# offered for it and the reason says why.
BUDGET_EXHAUSTED = "INFRA/BUDGET_EXHAUSTED"
# Statuses a dispatch can carry without being part of its window's history.
DISCOUNTED = {"superseded", "stale", NEVER_STARTED, RELEASED}
# Written by `inject_context` when the hook on `Agent` denies a dispatch.
DENIALS_FILE = "state/dispatch-denials.jsonl"
# A dispatch or a stage left open AFTER the story closed. Not a liveness verdict — the host
# may well be able to prove nothing about it — but a contradiction: gate B is decided and S8
# is done, so there is no work this tail can be part of (TP2-2534, I-92).
STALE_AFTER_CLOSURE = "stale_after_closure"
# The one stage that legitimately runs on a closed story: the retro reads what the story did.
RETRO_STAGE = "S9"
# The operations whose refusal reads "what is running" (TR4-7): `apply` records a dead holder before they validate.
HOLDING_OPS = frozenset({"revise_plan", "semantic_reopen", "invalidate", "dispatch", "resume"})
# Dispatch statuses that still claim somebody owes the story something.
OPEN_AFTER_CLOSURE = {"running", "blocked", "paused", "incomplete", RETURNED, ABANDONED}
# RH1-6 (owner's F-2): the block a person's word passes when the open items of gate A cannot be listed, or an item has no block a
# recorded word could pass (RH1-5's `<name>: unreadable` form; no script name inside it, so it is no substring of theirs).
GATE_A_ITEMS_UNREADABLE = "gate A open items: unreadable"
OPEN_ITEMS_LISTED = 20            # `problems` names this many open items, then `and N more` (the machine list `open_items` is whole)
OPEN_ITEM_SENTENCE = 300          # one `problems` sentence is cut here, with `…`
# pipeline.json: the person's own words that reopened a closed story, beside `reopened_at`.
REOPENED_BY_WORDS = "reopened_by_words"
CLOSED_BY = "gate B + S8 done"
# The stages whose scope is not a matter of taste: it follows from the approved plan's
# dispositions, so the controller can compute it and refuse an empty one.
DERIVED_SCOPE_STAGES = ("S5", "S6")
# The outcome of an instance the person took over at gate A, because the runner of its
# profile does not exist in this session (TP2-2536: Maestro/iOS without Xcode). S5
# still writes and reviews the code; S6 never executes it.
HANDED_OUTCOME = "handed_to_person"
# The outcome of an instance the STAND blocked (t-219): written and reviewed, never run to a verdict. The
# same word as `acceptance.BLOCKED_OUTCOME` and the manifest's `unresolved[].reason`; spelled here because
# this module imports `acceptance` only inside the S5 completion check.
BLOCKED_OUTCOME = "blocked_by_env"
# The word of the completion that accepts a probe gap the person named (HF1-14); the same as `acceptance.PROBE_GAP_KIND`,
# spelled here for the same reason as BLOCKED_OUTCOME.
PROBE_GAP_WORD = "probe_gap"
# The word of the completion that accepts a RED window (HF2-4b): a test that failed against the requirement and whose
# manifest row says so; the same as `acceptance.CONTRADICTS_REQUIREMENT` (held equal by test_red_window), spelled here
# for the same reason as BLOCKED_OUTCOME.
CONTRADICTS_WORD = "contradicts_requirement"
# The roles that run a repair/review loop and therefore carry a repair cap.
REPAIR_LOOP_ROLES = {"qa-automator", "qa-code-critic", "qa-case-designer", "qa-case-critic",
                     "qa-requirements-tester", "qa-test-strategist",      # X2-7: the authors of S2/S3 repair on the stage critic's word
                     "qa-runner", "qa-failure-analyst"}                   # X7-6c (B1): the authors of S6/S7 repair on their CONSUMER's word: `prepare` carries the round count


# Why a round after the first one exists. Only `test_defect` spends the repair cap: on
# TP1-15045 (session 57cf578c) the two rounds of every S5 window went to manifest
# bookkeeping, an env file the conftest did not read, and the critic's own five parallel UI
# runs on a one-account stand — and a five-line `sleep` fix found in the last review could
# not be made because "the cap was reached". An absent cause is `test_defect`, which is
# every receipt written before 0.7.8.
#
# `ticket_changed` (B-364) is the DRIVER's word, never a reviewer's: the person chose a changed ticket text and S2-S3
# are re-run from it. It spends none of the cap (it is not a test_defect). The reviewers' own list is the five
# above: `judge_code` and `repair_route` read REVIEWER_CAUSES, so a judge or a route that wrote `ticket_changed`
# reads as `test_defect` - the safe side, the one that spends the cap - and a real defect of a test cannot hide
# behind the driver's word.
#
# `question_answer` (HF2-7) is the DRIVER's word too: the person answered a question after the plan or the cases were
# written, and the owner of the rows or cases that followed the other reading is sent back to make them follow it. It
# spends none of the cap, and a reviewer's finding that names it reads as `test_defect`, the same safe side. It stands
# BEFORE `ticket_changed`, which stays the last word of the list (`test_story_run_freshness_k15_k26.py` K26 pins it).
REVIEWER_CAUSES = ("test_defect", "mechanical", "environment", "tooling", "reviewer_error")
# `source_arrived` (t-2181 PC-6) is the DRIVER's word as well: code arrived for a story that waited for it, and the S0-S2 work
# that follows is not a defect of any test, so it spends none of the cap and a reviewer's finding that names it reads as
# `test_defect`. It stands BEFORE `ticket_changed`, which stays the last word of the list.
REPAIR_CAUSES = REVIEWER_CAUSES + ("question_answer", "source_arrived", "ticket_changed")
# A mechanical fix (a sleep, a raw locator outside a page object, a lint) is a finding the
# critic words — file, what is wrong, what to do — and the AUTHOR makes as it sees fit. The
# critic is NOT dispatched again: the author re-runs only the instances whose files changed,
# green on the new bytes, and that run block is the whole proof. The window record carries
# `mechanical_round` (`acceptance.mechanical_round`), which lets the review and the probe stay
# bound to the bytes they were made on, and the author's mechanical dispatch may complete S5.
# 0.7.8 shipped one "closing" reviewer dispatch instead; the owner withdrew it — S4 closes a
# critic's exact replacements by code, not by another critic, and S5 does the same.
AUTHOR_ROLES = {"qa-automator", "qa-case-designer", "qa-requirements-tester", "qa-test-strategist"}
DISPATCH_DEFAULTS = {"mechanical_rounds": 1, "ui_window_cases": 2, "api_window_cases": 4}
# What the first S5 window learned and the next must not rediscover (page objects and their
# load gates, stand rules, fixtures, env files, id spelling). Task-relative.
S5_NOTES = "work/s5-notes.md"
# TR3-15: from windows on, the notes are one file per dispatch, `work/s5-notes/<dispatch>.md` (`S5-qa-automator-N` and `S5-qa-code-critic-N`
# each write their own; `references/artifact-writers.json` claims `work/s5-notes/S5-qa-automator-*.md` and `work/s5-notes/S5-qa-code-critic-*.md`),
# so two windows never edit one file. S5_NOTES stays the one file of a story from before. A role reads ALL of them (shared knowledge).
S5_NOTES_DIR = "work/s5-notes"


def repair_cause(dispatch):
    cause = str((dispatch or {}).get("repair_cause") or "test_defect")
    return cause if cause in REPAIR_CAUSES else "test_defect"


# What a dispatch request binds its role to, and what a continuation of it must carry
# unchanged: the pinned CaseVersions it repairs, why the round exists and from where, the
# accepted work it reworks, the sentence the role reads, and the shape of the work. TP2-2406:
# retry and relaunch packets copied four fields of the dispatch RECORD, and the record is not the
# request - `checkpoint`/`accept` overwrite its `reason` and the liveness repair rewrites it - so
# a resumed repair lost its binding, its cause, its lineage and the mandatory `reason`.
BINDING_KEYS = ("case_version_links", "repair_cause", "repair_cause_source", "rework_of", "reason",
                "purpose", "execution_kind", "manual_case_ids", "limits", "plan_rows")


def request_binding(payload):
    """A deep copy of the immutable part of a dispatch request: only what the request carried."""
    return {key: copy.deepcopy(payload[key]) for key in BINDING_KEYS
            if (payload or {}).get(key) is not None}


def window_key(dispatch):
    """One S5 window whoever works on it: the author's rounds and the reviewer's share it.

    The S5 PLAN dispatch (SC1-14 B1a) is not a window: its scope is every case of the stage, which with one window is the window's
    own scope, and the hash would make the plan's runs and its stand signal the window's. Its key is its own (`S5:plan`);
    `s5_part_of` answers `window` for every record the plan form did not write, so a story that began on the old form keys as before."""
    if s5_part_of(dispatch) == "plan":
        return "S5:plan"
    return str(dispatch.get("stage")) + ":" + content_hash(sorted(dispatch.get("scope") or []))


def set_aside_in_own_stage(dispatches, dispatch):
    """A `stale` dispatch that a rework of ITS OWN stage set aside: its round was paid (A1, I3).

    The `reviews` stamp of an S5 rework stales the S5 critic whose review no longer stands
    (`apply_rerun_after` step 1, `stale_by_rework: <the S5 rework>`): the round the critic spent
    stays spent, or the cap would reset on every person's word. The stamp's second step stales the
    accepted dispatches of the LATER stages (`stale_by_rework: <the S3/S4 rework>`): that is a
    window run again from nothing, and its old chain must not count (a new window, counted 0).
    The two are told apart by the stage of the rework the mark names."""
    if dispatch.get("status") != "stale":
        return False
    rework = dispatches.get(str(dispatch.get("stale_by_rework") or ""))
    return isinstance(rework, dict) and rework.get("stage") == dispatch.get("stage")


def holds_a_round(dispatches, dispatch):
    """THE A1 predicate: this dispatch still counts as a round - live, or `stale` because a rework of its
    OWN stage set it aside (`set_aside_in_own_stage`). The repair ledger and the mechanical counter read it."""
    return dispatch.get("status") not in DISCOUNTED or set_aside_in_own_stage(dispatches, dispatch)


def repair_ledger(dispatches, dispatch):
    """The rounds of this role on this bounded window, each with the cause it was opened for.

    A round is one piece of work, not one receipt: a `parent_retry` resumes its parent from
    the checkpoint, so the whole chain is a single round carrying the cause it was opened
    with. The first round that really happened opened the window and is nobody's repair — the
    first live chain none of whose members reworks another dispatch (`rework_of`).
    Counting receipts instead lost a round whenever the opener had been resumed — on
    TP1-15045 window 1 (`automator-2` superseded, `-3` its retry, `-4`, `-5`) read as
    one repair round while the roles were being told "round 2 of 2 — the last".

    A `stale` dispatch counts as live only when a rework of its OWN stage set it aside
    (`set_aside_in_own_stage`, A1): the round was paid. One an earlier stage's rework set aside
    opens a new window, counted 0. `DISCOUNTED` itself is read as before by its other readers.
    """
    key = ledger_key(dispatch)
    # An S7 investigation is a read-only pass beside the triage, never a repair round of it (X7-6c): it spends no round.
    own = {_dispatch_ident(d, name): d for name, d in dispatches.items()
           if isinstance(d, dict) and ledger_key(d) == key and not s7_part_of(d)}

    def root(name):
        return lineage_root(own, name, ("parent_retry",))

    chains = {}
    for name, d in own.items():
        chains.setdefault(root(name), []).append((name, d))
    live = [members for members in chains.values()
            if any(holds_a_round(dispatches, d) for _, d in members)]
    # A dispatch that reworks another is a repair by construction and never the opener. S7 and
    # S4 reworks are registered on a window whose plain opener sits under another key or in
    # another stage, so "the first live chain" was their first repair — counted as nobody's
    # round, and the cap then allowed one round more than it said (B-007).
    opener = next((i for i, members in enumerate(live)
                   if not any(d.get("rework_of") for _, d in members)), None)
    rounds = []
    for index, members in enumerate(live):
        if index == opener:
            continue
        cause = next((repair_cause(d) for _, d in members if d.get("repair_cause")), "test_defect")
        rounds.append({"id": members[-1][0], "cause": cause})
    by_cause = {}
    for entry in rounds:
        by_cause[entry["cause"]] = by_cause.get(entry["cause"], 0) + 1
    return {"opened": bool(live), "rounds": rounds, "by_cause": by_cause,
            "counted": by_cause.get("test_defect", 0)}


def repair_rounds(dispatches, dispatch):
    """Repair rounds already spent on this bounded window, counted from the journal itself.

    The cap in `runtime_policy` was reachable only through `cumulative_counters`, and a
    counter exists only when the host reported one. On TP1-15045 no host counter was
    ever recorded, `cumulative_budget` returned None for every metric, and the cap silently
    did not exist. Dispatch receipts are always there, whatever the host measures.

    Keyed by `budget_scope`, exactly like the counters it stands in for: S5 runs several
    windows of the same stage and role on purpose, and window three is not repair round three.
    A `parent_retry` resumes the same work from its checkpoint and is not another round.
    Only a round about the test counts (`REPAIR_CAUSES`): the cap bounds how long a test may
    stay wrong, not how often the stand, the tooling or the reviewer may be.
    """
    return repair_ledger(dispatches, dispatch)["counted"]


def mechanical_rounds(dispatches, dispatch, by_role=False):
    """Mechanical rounds already had on this window: the AUTHOR's whichever role asks (the cap's own
    counter), or with `by_role` the asking role's own (a reviewer's, whose pass is used up by each one).

    ONE counter, one predicate for both: a round counts as the ledger counts it (A1, F1) - live, or
    set aside by a rework of its OWN stage (`set_aside_in_own_stage`: the round was paid, a person's
    word must not hand the reviewer its first mechanical pass again); one an earlier stage's rework
    set aside opens a new window, counted 0."""
    key_of = ledger_key if by_role else window_key
    key = key_of(dispatch)
    return sum(1 for d in dispatches.values()
               if isinstance(d, dict) and key_of(d) == key and not d.get("parent_retry")
               and holds_a_round(dispatches, d) and repair_cause(d) == "mechanical"
               and (by_role or d.get("role") in AUTHOR_ROLES))


def pack_windows(groups, ui_cases=2, other_cases=4, start=1):
    """Groups of cases (`{"cases": [...], "surface": "ui" | anything else}`, in the order they are to be placed) packed into
    dispatch windows numbered from `start`: small ones for UI, never a mixed one.

    TP1-15045 ran UI windows of six and four cases: 130-178 tool calls each, a context of
    250-350K tokens, three dispatches at $8-15 — and each re-learned the UI repository.
    Everything that is not UI goes first: it is cheaper, and what it learns about the stand
    (accounts, env files, fixtures) is what a UI window would otherwise pay to find out.

    A group is never cut: first fit, the first window of its surface with room for the WHOLE group; a group that fits no window
    opens one; a group larger than the cap is one window of its own - `over_cap: True, cap: <the cap>`, UI included (the cap
    yields, owner F-J2 (b); SC1-14 FJ-B). Groups of one case are the cut by cases, `split_windows`. Pure and deterministic."""
    out = []
    for surface, size in (("other", max(1, int(other_cases))), ("ui", max(1, int(ui_cases)))):
        opened = []
        for group in (g for g in groups if (g.get("surface") == "ui") == (surface == "ui")):
            cases = list(group["cases"])
            if not cases:
                continue        # a group of nothing opens no window
            if len(cases) > size:
                opened.append({"scope": cases, "over_cap": True, "cap": size})
                continue
            room = next((w for w in opened if not w.get("over_cap") and len(w["scope"]) + len(cases) <= size), None)
            if room is None:
                opened.append({"scope": []})
                room = opened[-1]
            room["scope"].extend(cases)
        for window in opened:
            out.append(dict({"index": start + len(out), "surface": surface}, **window))
    return out


def split_windows(cases, is_ui, ui_cases=2, other_cases=4):
    """The scope cut into dispatch windows by cases alone: `pack_windows` over groups of one case. The cut of `legacy` S5, of S6
    and of an S5 with no plan and no written window - byte for byte what it was before the plan cut existed."""
    return pack_windows([{"cases": [c], "surface": "ui" if is_ui(c) else "other"} for c in cases], ui_cases, other_cases)


def known_paths_problems(paths):
    """`[(ValueError, message)]` for `paths`: the shape stop alone (every key check reads a dict), else one
    item per bad key in the order of the checks (K1: the keys are independent of one another)."""
    if not isinstance(paths, dict):
        # the folder is not known here: a placeholder that says where it comes from (FR-59)
        return [(ValueError, "known_paths must be an object of named paths, not a list: copy the `resolved_paths` object that "
                 "`controller.py --task-root <the story's folder> --operation prepare` prints")]
    problems = []
    for key in ("root", "project_root", "task_root", "plugin_root", "scripts_root", "python_executable"):
        if key in paths and (not isinstance(paths[key], str) or not paths[key].strip()):
            problems.append((ValueError, f"known_paths.{key} must be a nonempty path string"))
    for key in ("repository_roots", "entrypoints"):
        if key in paths and (not isinstance(paths[key], dict) or any(
                not isinstance(value, str) or not value.strip() for value in paths[key].values())):
            problems.append((ValueError, f"known_paths.{key} must map names to path strings"))
    return problems


def names_handed(payload) -> bool:
    """Does this completion say out loud that it hands instances to the person?

    Read out of `unresolved` and `reason` together, in whatever shape the payload spells
    them (a flag with a sentence, a string, a list of rows) — the accept payload has carried
    all three across versions, and a story in flight must not be refused over a spelling."""
    try:
        blob = json.dumps([(payload or {}).get("unresolved"), (payload or {}).get("reason")],
                          default=str)
    except (TypeError, ValueError):
        return False
    return HANDED_OUTCOME in blob


def names_blocked(payload) -> bool:
    """Does this completion say out loud that instances were blocked by the stand?

    The twin of `names_handed`, read the same way (`unresolved` and `reason` together, in whatever shape the
    payload spells them), for the same reason: the manifest, the ledger and gate B carry the word
    `blocked_by_env`, so the completion that closes the window carries it too."""
    try:
        blob = json.dumps([(payload or {}).get("unresolved"), (payload or {}).get("reason")],
                          default=str)
    except (TypeError, ValueError):
        return False
    return BLOCKED_OUTCOME in blob


def names_probe_gap(payload) -> bool:
    """Does this completion say out loud that it accepts probe gaps the person named (HF1-14)?

    The twin of `names_blocked`, read the same way (`unresolved` and `reason` together, in whatever shape the payload
    spells them): the derived pair `story_step.py finish` writes carries the word `probe_gap`."""
    try:
        blob = json.dumps([(payload or {}).get("unresolved"), (payload or {}).get("reason")],
                          default=str)
    except (TypeError, ValueError):
        return False
    return PROBE_GAP_WORD in blob


def names_contradicts(payload) -> bool:
    """Does this completion say out loud that it accepts red tests the requirement contradicts (HF2-4b)?

    The twin of `names_blocked`, read the same way (`unresolved` and `reason` together, in whatever shape the payload
    spells them): the derived pair `story_step.py finish` writes carries the word `contradicts_requirement`. INVARIANT
    (FR-10): the word is read as a WORD of the pair, not as the red instance's own record - this reader holds neither
    the window nor the instance, so it cannot tell a pair that names the word for another case from the gap's own;
    that join is `acceptance.validate_window`'s, which re-derives each red from the manifest and the run blocks and
    never from the pair. Error direction: toward False (a payload that cannot be read names nothing)."""
    try:
        blob = json.dumps([(payload or {}).get("unresolved"), (payload or {}).get("reason")],
                          default=str)
    except (TypeError, ValueError, AttributeError):
        return False
    return CONTRADICTS_WORD in blob


# The most cases one manual runner block may name (t-323 C4: the literal 5 had a second reader, `story_progress`,
# that counts blocks left; it now reads `MANUAL_WINDOW_CASES` below). The refusal's text below says "1..5" as a literal on purpose:
# `tools/controller-blocks-gen.py` reads the message from the source, and `design/controller-blocks.md` quotes it.
MANUAL_BLOCK_CASES = 5
# The size of the window the doors OFFER (SC2-38 item 3; t-1957 N5s: three, the cases of one account set walk together): up to three
# cases per manual runner dispatch, run in turn. The ceiling above stays what a block may name (`--scope` of 2..5 is lawful; a rework
# block and a story in flight keep it). The readers of the offered size pass it explicitly to `walk_lanes` (below):
# `story_step._manual_block_door`, `Driver.MANUAL_BLOCK_MAX` and `story_progress._block_position`.
MANUAL_WINDOW_CASES = 3
# The most members a refusal of the scope names (R1, R3, R4 and the pin problem of gate A): the text is finite and the
# number is named when it is cut (FR-41). One constant for every text that lists scope members (CX1-11, E9).
SCOPE_SHOWN = 20
# The `reason` of the `revise_plan` request `case_versions.scope_request` builds (`{n}` = the number of pinned cases): the one
# text the controller recognises as its OWN output (CX2-17 C-4), so a write of the code is never read as a person's words.
SCOPE_REASON = "S4: {n} cases pinned; the approved scope is the case ids S4 produced"


def code_scope_key(key, revision, ticket):
    """True when `key` is the one `case_versions.scope_request` builds: `revise_plan:<ticket>:<revision>:<12 hex>` with the
    revision equal to the `expected_revision` of the same request. Fields only, never words (FR-12). Residue: a hand-written
    key that repeats the whole form with the right revision cannot be told from ours."""
    found = re.fullmatch(r"revise_plan:" + re.escape(str(ticket)) + r":(\d+):[0-9a-f]{12}", str(key or ""))
    return bool(found) and int(found.group(1)) == revision


def code_scope_write(key, revision, reason, ticket):
    """True for a `revise_plan` the CODE wrote: the key of `code_scope_key` AND a `reason` that is `SCOPE_REASON` whole, for any
    whole `n`. The double condition is the point: the key alone says "do not count the scope as set by hand", this one decides
    that no person's word stands in the request, and a mistake here erases a word. It recognises the code's own output, not a
    phrase about someone else's words (FR-12); anything else stays as before - the words of a person."""
    if not isinstance(reason, str) or not code_scope_key(key, revision, ticket):
        return False
    head, tail = SCOPE_REASON.split("{n}")
    return bool(re.fullmatch(re.escape(head) + r"[0-9]+" + re.escape(tail), reason))


def _folder_name(path):
    """The name of the story folder `path` points at, as it was written; the resolved folder's name when the written one names
    no folder (`.` has an empty name, `..` a dotted one): the one rule of `Controller._ticket` and `apply_door` (CX2-17, E20)."""
    path = Path(path)
    return path.name if path.name not in ("", "..") else path.resolve().name


def _subset_of(items, allowed):
    """`set(items).issubset(allowed)`, and False when an element cannot be hashed (`Controller._within` is this)."""
    try:
        return set(items).issubset(allowed)
    except TypeError:
        return False


def manual_block_problems(scope, manual_case_ids) -> list:
    """EVERY problem of a manual runner block, each its own sentence (the owner's class rule 27.10: a refusal lists the problems
    one by one). `[]` for exactly the inputs the one-sentence validator accepted: a list of 1..MANUAL_BLOCK_CASES unique
    non-empty strings, all inside `scope or []` (`_subset_of` semantics: a scope entry that is no string does not refuse, a
    scope given as a set does not refuse). A non-list stops at ONE problem (nothing else can be read from it). Positions are
    1-based. Id lists go through `detector_verdict.named` (the first SCOPE_SHOWN, then the count). THE one collector (AR-15):
    `validate_manual_runner_block`, `build_rework_request` and `story_step.py start` read it."""
    from detector_verdict import named
    if not isinstance(manual_case_ids, list):
        return [f"manual_case_ids is not a list of case ids (it is {type(manual_case_ids).__name__})"]
    problems = []
    if not manual_case_ids:
        problems.append("it names no case")
    if len(manual_case_ids) > MANUAL_BLOCK_CASES:
        problems.append(f"it names {len(manual_case_ids)} cases, at most {MANUAL_BLOCK_CASES}: split the block")
    bad = [str(at) for at, case in enumerate(manual_case_ids, 1) if not isinstance(case, str) or not case]
    if bad:
        problems.append("entries that are not case ids at position(s) " + named(bad, SCOPE_SHOWN))
    ids = [case for case in manual_case_ids if isinstance(case, str) and case]
    seen, repeated = set(), []
    for case in ids:
        if case in seen and case not in repeated:
            repeated.append(case)
        seen.add(case)
    if repeated:
        problems.append("named more than once: " + named(repeated, SCOPE_SHOWN))
    try:
        allowed = set(scope or [])
    except TypeError:       # not iterable, or an unhashable entry: what `_subset_of` refused
        problems.append("the dispatch scope is not a list of case ids")
    else:
        outside = [case for case in ids if case not in allowed]
        if outside:
            problems.append("not in the dispatch scope: " + named(outside, SCOPE_SHOWN))
    return problems


def manual_blocks(cases, size=MANUAL_BLOCK_CASES) -> list:
    """`cases` cut into consecutive blocks of at most `size`, order kept; `[]` -> `[]`. THE one split (AR-15): the driver and
    `story_step.py start` cut a manual runner block by it. `size < 1` would loop or yield empty blocks: `ValueError`."""
    if size < 1:
        raise ValueError(f"a block holds at least one case, got size {size}")
    cases = list(cases)
    return [cases[at:at + size] for at in range(0, len(cases), size)]


def walk_lanes(cases, keys, size) -> list:
    """The manual cases cut into WALK LANES (t-1957 N5s, spec 3.6): cases that share the key of their account set walk together, in the
    order of `cases` inside a key, at most `size` to a lane; lanes come in the order of their first case. `keys` is `{case: key}`
    (`lane_keys` builds it; `""` = no account named = guest). A case with NO usable key (absent from `keys`, `None`, not text - an
    unreadable request) is a lane of its own: an account is never guessed for a case (E5s.8). THE one cut (AR-15, AR-19): the driver,
    `story_step.py start`'s door and the progress line call it. Pure: reads nothing. A `size` below 1 (or not a number) is read as 1: the
    error direction is the smallest lane, never a lane that merges accounts or an empty one."""
    size = size if isinstance(size, int) and size >= 1 else 1
    groups: dict = {}
    for case in dict.fromkeys(str(c) for c in cases):
        key = (keys or {}).get(case)
        groups.setdefault(("key", key) if isinstance(key, str) else ("own", case), []).append(case)
    return [members[at:at + size] for members in groups.values() for at in range(0, len(members), size)]


def lane_keys(task_root, cases) -> dict:
    """`{case: key of its account set}` for `walk_lanes`: `manual_capture.lane_key`, with the case left OUT (its own lane) when its
    request cannot be read (`manual_evidence.request_actors` says why) - `lane_key` alone would read that as a guest. A request that
    is absent or refused names no account: `""`. A `task_root` of `None` has no requests to read: every case is `""`."""
    keys: dict = {}
    if task_root is None:
        return {str(c): "" for c in cases}
    import manual_capture as MC
    import manual_evidence as ME
    for case in dict.fromkeys(str(c) for c in cases):
        try:
            if ME.request_actors(task_root, case)[1]:
                continue
            keys[case] = MC.lane_key(task_root, case)
        except Exception:       # a case id the evidence folder refuses: it has no readable request either
            continue
    return keys


def manual_done_cases(state, stage="S6") -> set:
    """The cases an ACCEPTED manual runner dispatch of `stage` already carried (`manual_case_ids` of every accepted record whose
    `execution_kind` is `manual`). THE one reader (AR-15): the driver's `manual_done` and `story_step.py start`'s door read it."""
    done = set()
    for record in ((state or {}).get("dispatches") or {}).values():
        if (isinstance(record, dict) and record.get("stage") == stage and record.get("status") == "accepted"
                and record.get("execution_kind") == "manual"):
            done.update(str(case) for case in record.get("manual_case_ids") or [])
    return done


def validate_manual_runner_block(scope, manual_case_ids, extra=()):
    """Keep human execution blocks reviewable without limiting automated runs. ONE refusal lists every problem
    (`manual_block_problems` plus the caller's `extra`, e.g. the plan-membership sentences of the Controller)."""
    problems = manual_block_problems(scope, manual_case_ids) + list(extra)
    if problems:
        from detector_verdict import compound
        raise StateConflict(compound(problems, prefix="manual runner block must name 1..5 unique in-scope cases:"))


def budget_scope(dispatch):
    # Stable across continuation, input refresh and repair; independent windows do not
    # consume each other's caps. Global costs are accounted by the usage ledger.
    # The S5 plan dispatch (SC1-14 B1a) counts under its own key: with one window its scope IS the window's, and the plan would
    # be the window's "opener" (its first dispatch a repair round) and spend the window's cap. `ledger_key` delegates here.
    if s5_part_of(dispatch) == "plan":
        return "S5:" + str(dispatch.get("role")) + ":plan"
    return str(dispatch.get("stage")) + ":" + str(dispatch.get("role")) + ":" + content_hash(sorted(dispatch.get("scope") or []))


def ledger_key(dispatch):
    """The key the REPAIR ledger counts under. S4 has one designer and one case list that changes
    between rounds (a repair adds or drops a case), so every S4 qa-case-designer dispatch of the
    story shares one key: a changed case list must never reset the count and let the loop run past
    its cap (B-007, critic t-064). S5 windows are independent by design and keep `budget_scope`."""
    if str(dispatch.get("stage")) == "S4" and str(dispatch.get("role")) == "qa-case-designer":
        return "S4:qa-case-designer"
    return budget_scope(dispatch)


# The two roles of one repair loop: the author and the critic of a window. A person's word for
# "one more round" is one pass for EACH of them (the author works, the critic reviews it).
REPAIR_PAIRS = (("qa-automator", "qa-code-critic"), ("qa-case-designer", "qa-case-critic"))


def earlier_stage_rework(dispatches, dispatch, keys):
    """The record name of the rework of ANOTHER stage that set `dispatch` aside, when it is a `stale` dispatch
    under one of the ledger `keys` and the mark names a dispatch record; else ''."""
    if not (isinstance(dispatch, dict) and dispatch.get("status") == "stale" and ledger_key(dispatch) in keys):
        return ""
    mark = str(dispatch.get("stale_by_rework") or "")
    if isinstance(dispatches.get(mark), dict) and not set_aside_in_own_stage(dispatches, dispatch):
        return mark
    return ""


def window_life(dispatches, dispatch):
    """The LIFE of a window: the id of the latest rework of an EARLIER stage that set it aside, or "" (F2).

    A rework of an earlier stage (S3/S4) stales the S5 dispatches through the stamp's `stages` step
    and the window runs again from nothing (A1 counts it 0). Its ledger key does not change, so a
    word recorded for round 3 of the old life would pass round 3 of the new one unasked; the id of the
    rework that opened the new life goes into the pass key's hash and the old word stops matching.
    Read from the record `set_aside_in_own_stage` reads: a `stale` dispatch of this loop (both roles
    of its pair) whose `stale_by_rework` names a dispatch record of ANOTHER stage; the latest such
    record in the journal's order wins. A rework of the window's own stage is no new life. A
    rework record with no `id` field reads as the first life, with one line on stderr, never a KeyError."""
    pair = next((roles for roles in REPAIR_PAIRS if dispatch.get("role") in roles), (dispatch.get("role"),))
    keys = {ledger_key(dict(dispatch, role=role)) for role in pair}
    marks = {earlier_stage_rework(dispatches, d, keys) for d in dispatches.values()} - {""}
    if not marks:
        return ""
    latest = max(marks, key=list(dispatches).index)
    life = dispatches[latest].get("id")
    if not life:
        print(f"window life: the rework {latest!r} that set this window aside has no id field; "
              "read as the window's first life", file=sys.stderr)
    return str(life or "")


def repair_pass_key(stage, role, n, key, kind="round", life=""):
    """THE builder of the text a person's recorded word passes ONE repair round with (A2, A3, F2).

    `key` is the window's ledger key (`ledger_key`, never the scope list: a changed case list must
    not change the key, FR-7). `life` is the window's life (`window_life`, "" for the first one):
    the hash is `content_hash(key + "|" + life)[:12]`, so the FIRST life hashes `key + "|"`
    and a pass written in one life never matches the next. `waiver.split_overridden` matches a word
    by whole words (`contract.names_whole`), case-folded, and never uses it up; so the text names the round (`n`) and the role,
    and the ` for ` after the number keeps round 1 from matching round 10. It carries neither
    `repair round` nor `mechanical round`: those are the stage-wide words of the old doors, and a key
    that held one would lift every later round again. `kind` is `round` or `mechanical`."""
    return f"{kind} pass {n} for {role} on {stage}:{content_hash(key + '|' + life)[:12]}"


def repair_passes(dispatches, request):
    """The round pass of BOTH roles of the request's loop: {role: key}, each for the next round that
    role would spend past its cap. One answer, both roles: the packet's `repair_budget.passes`, the
    cap refusal and the conductor's door print these and never rebuild them."""
    # X2-7: a repair-loop role outside every pair (the S2/S3 authors repair on the stage critic's word) is its own pair - the cap refusal
    # below indexes `passes[role]`, so an empty answer was a KeyError instead of the refusal (AR-25)
    pair = next((roles for roles in REPAIR_PAIRS if request.get("role") in roles), (request.get("role"),))
    life = window_life(dispatches, request)
    out = {}
    for role in pair:
        mine = dict(request, role=role)
        out[role] = repair_pass_key(request.get("stage"), role,
                                    repair_ledger(dispatches, mine)["counted"] + 1, ledger_key(mine), life=life)
    return out


def mechanical_pass_key(dispatches, dispatch):
    """The pass of the mechanical round this dispatch asks for. The author's n is the window's
    mechanical round count + 1 (the cap's own counter); a reviewer is never dispatched for a mechanical
    round, so its n is its own earlier mechanical dispatches + 1 and the pass is used up by each one -
    the same counter (`mechanical_rounds`), by role, with the same A1 predicate."""
    n = mechanical_rounds(dispatches, dispatch, by_role=dispatch.get("role") not in AUTHOR_ROLES) + 1
    return repair_pass_key(dispatch.get("stage"), dispatch.get("role"), n, ledger_key(dispatch), "mechanical",
                           window_life(dispatches, dispatch))


def limit_reasons(due):
    """` (over its limit: a, b)` - the metrics a `checkpoint_due` / `cumulative_budget` answer names, or ''."""
    reasons = due.get("reasons") or []
    return f" (over its limit: {', '.join(reasons)})" if reasons else ""


def repair_doors(stage, keys):
    """The recording command of each pass key, as a refusal to a person ends with it: one command per key."""
    return " and ".join("`" + person_words.door(f'waiver.py --task <TICKET> --stage {stage} --block "{key}"') + "`"
                        for key in keys)


def code_close_passed_label(verdict):
    """How a running row that is NOT work any more reads, from its `dispatch_liveness` verdict; None when it still holds the close.

    Pure. The direction of error is the refusal (FR-59, AR-28): only a verdict that is a dict AND says the session is over
    releases the row. `abandoned`, `never_started`, `returned` (the row is still `running`, so the work ended and was never
    accepted) release it; `alive`, `unknown`, a verdict that is not a dict and any state this function does not know hold it."""
    if not isinstance(verdict, dict):
        return None
    word = verdict.get("state")
    if word == "returned":
        return "returned, never accepted"
    if word == "abandoned":
        return "abandoned"
    if word == "never_started":
        return "never started"
    return None


# How a dispatch row that is not `running` but was never accepted reads in a close's name (AR-27): the status is the row's own.
STOPPED_LABELS = {RETURNED: "returned, never accepted", ABANDONED: "abandoned"}
STOPPED_DEFAULT_LABEL = "stopped, never accepted"


def _dispatch_ident(row, key):
    """The id a dispatch row goes by: its own `id`, else its key in `state["dispatches"]` (one reading for the close readers)."""
    return str(row.get("id") or key) if isinstance(row, dict) else str(key)


def _stopped_passed_over(dispatches, number, verdicts):
    """`[(id, label)]` of the rows of the closing stage and earlier ones that stopped and were never accepted (a status of
    `OPEN_AFTER_CLOSURE` that is not `running`), unless an accepted LATER row of the same stage and role replaced the work.
    Read only with `verdicts` (the `code_only` operation). A row with no readable stage number is left out: it names nothing to close."""
    rows = [(key, row) for key, row in dispatches.items() if isinstance(row, dict)]
    out = []
    for index, (key, row) in enumerate(rows):
        status = row.get("status")
        stage = row.get("stage")
        if (not isinstance(status, str) or status == "running" or status not in OPEN_AFTER_CLOSURE
                or not isinstance(stage, str) or not stage[1:].isdigit() or int(stage[1:]) > number):
            continue
        if any(later.get("status") == "accepted" and later.get("stage") == stage and later.get("role") == row.get("role")
               for _k, later in rows[index + 1:]):
            continue
        out.append((_dispatch_ident(row, key), STOPPED_LABELS.get(status, STOPPED_DEFAULT_LABEL)))
    return out


def code_close_note(passed_over):
    """The one sentence of a close that passed over dispatches that were not work any more (AR-27): it goes into the stage's close
    note, so the report reads it. `passed_over` is `facts["passed_over"]`: `[(dispatch id, label), ...]`; empty gives ''."""
    if not passed_over:
        return ""
    return ("; passed over, not holding the close: "
            + ", ".join(f"{ident} ({label})" for ident, label in passed_over))


def _code_close_holders_words(state, holders, verdicts, checkpoint=False):
    """The sentence tail of a running refusal: each holder in the story's words and the doors (FR-1, FR-2, FR-9).

    ONE wording for every "checkpoint active work" refusal (TR4-7, AR-13): the holder by id, role and stage, whether its
    session is known to be alive or the factory could not tell (FR-59), and the doors. `checkpoint=True` (the refusals of an
    operation that changes the plan, the gate or the records) adds the door the caller can use at once: checkpoint it."""
    dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
    rows = {}
    for key, row in dispatches.items():
        rows[_dispatch_ident(row, key)] = row if isinstance(row, dict) else {}
    parts = []
    for ident in holders:
        row = rows.get(ident, {})
        verdict = (verdicts or {}).get(ident)
        live = isinstance(verdict, dict) and verdict.get("state") == "alive"
        what = (f"the {row.get('role') or 'role'}'s work of {row.get('stage') or 'a stage'} (dispatch {ident}) "
                + ("is still running" if live else "may still be running: the factory could not tell whether its session ended"))
        door = (f"checkpoint it with `controller.py --operation checkpoint --dispatch {ident} --status paused --reason \"<why>\" --brief`, "
                if checkpoint else "")
        parts.append(what + f"; wait for it to finish, {door}or free it with the person's word: "
                            f"`{person_words.door(f'controller.py --operation release --dispatch {ident}')}`")
    return " (" + "; ".join(parts) + ")"


def code_close_facts(state, stage, verdicts=None):
    """The facts of a code-only close of `stage` that `code_close_conflicts` decides by (AR-13): the ONE reading.

    `verdicts` (dispatch id -> `dispatch_liveness` verdict, read by the CALLER: this function stays pure) lets a running row that
    is not work any more (`code_close_passed_label`) leave `running` and appear in `passed_over` as `(id, label)`, and so does every
    row of the closing and earlier stages that stopped and was never accepted (`_stopped_passed_over`: B4, it is named whether or
    not `close_settled` ran first); a row with no verdict stays running. With no `verdicts` the facts are what they always were,
    without the `passed_over` key.

    `{"running": [dispatch id, ...], "behind": ("S<i>", status or None) | None, "completed": bool}` - which dispatches
    are running, the FIRST earlier stage that is neither completed nor skipped (with its recorded status), and whether
    `stage` itself is completed. A reader that needs the DETAILS of a refusal (which dispatch, which stage) takes them
    from here, never by scanning `state` itself, so the decision and the words it shows cannot drift apart.
    The direction of error is the refusal (FR-59): a row that cannot be read as what it should be reads as the unsafe
    thing - a dispatch row that is not a dict, or has no string status, counts as RUNNING (named by its key); an EARLIER
    stage entry that is not a dict, or has no string status, is an incomplete stage (status None); the stage's OWN entry
    that is neither absent nor a dict with a string (or no) status is read as completed (an unknown must not open the
    close of a stage that may be closed). A missing `stages` reads as every prior stage incomplete."""
    number = int(stage[1:])
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}

    def status_of(entry):
        status = entry.get("status") if isinstance(entry, dict) else None
        return status if isinstance(status, str) else None

    running, passed_over = [], []
    for key, row in dispatches.items():
        if not isinstance(row, dict) or status_of(row) in (None, "running"):
            ident = _dispatch_ident(row, key)
            label = code_close_passed_label((verdicts or {}).get(ident)) if isinstance(row, dict) else None
            (passed_over.append((ident, label)) if label else running.append(ident))
    behind = next(((f"S{i}", status_of(stages.get(f"S{i}"))) for i in range(number)
                   if status_of(stages.get(f"S{i}")) not in ("completed", "skipped")), None)
    own = stages.get(stage)
    unknown_own = bool(own) and (not isinstance(own, dict)
                                 or (own.get("status") is not None and not isinstance(own.get("status"), str)))
    facts = {"running": running, "behind": behind, "completed": status_of(own) == "completed" or unknown_own}
    if verdicts is not None:
        facts["passed_over"] = passed_over + _stopped_passed_over(dispatches, number, verdicts)
    return facts


def code_close_conflicts(state, stage, verdicts=None):
    """The state conflicts that refuse a code-only close of `stage`, in refusal order: `[(StateConflict, message), ...]`.

    ONE predicate for "this stage can be closed by code right now" (AR-13): `Controller.validate` (the `code_only`
    operation) refuses by it, and `execution_request.s6_close_dispatch` allows the S6 close context only when it is
    empty - so a probe that runs outside a dispatch is allowed exactly when the close that follows it is.
    It decides by `code_close_facts` (the one reading of the state, which the S6 close reader also takes its details
    from); the sentences stay literals here because the route generator reads them as literals.
    The direction of error is the refusal: a malformed `state` (no `stages`, no `dispatches`, a row of the wrong shape)
    reads as "not closable" or as having something running, never as a pass for a closed or working story.
    The three checks and their messages are the ones the `code_only` branch has always carried.
    """
    facts = code_close_facts(state, stage, verdicts)
    problems = []
    if facts["running"]:
        # with verdicts read (the `code_only` operation) the sentence also names who holds the close and the doors
        problems.append((StateConflict, "checkpoint active work before code-only completion"
                         + (_code_close_holders_words(state, facts["running"], verdicts) if verdicts is not None else "")))
    if facts["behind"]:
        problems.append((StateConflict, "required prior logical stage incomplete"))
    if facts["completed"]:
        problems.append((StateConflict, "stage already completed"))
    return problems


def set_stage(state, stage, entry):
    """Stage completion is monotonic: ordinary later work never un-completes a stage.

    The pilot bug: after all three S5 automation windows were accepted, one more legitimate
    quality-gate dispatch with `stage_complete: false` rolled S5 from completed back to
    running/pending, and S6 could no longer start. The stage had been finished and nothing
    about it had been withdrawn — only more work had happened on it.

    A completed stage is lowered by exactly three things, and all of them assign
    `state["stages"]` directly rather than coming through here: an explicit invalidation, a
    gate reopen, and the `rerun_after` stamp of a rework that carries a person's words
    (`apply_rerun_after`, t-675). Later work is still visible — it keeps its
    `active_dispatch_id` and its own status — but it does not rewrite a decision that was
    already recorded."""
    previous = state["stages"].get(stage) or {}
    if previous.get("status") != "completed" or entry.get("status") == "completed":
        # completed -> completed keeps the run marks (STAGE_RUN_MARKS, the table); any other entry is fresh.
        state["stages"][stage] = _carry_run_marks(previous, entry)
        return
    merged = dict(previous, later_work_status=entry.get("status"))
    if entry.get("dispatch_id"):
        merged["active_dispatch_id"] = entry["dispatch_id"]
    if entry.get("status") == "running":
        merged.pop("later_work_settled", None)
    else:
        merged["later_work_settled"] = True
        merged.pop("active_dispatch_id", None)
    state["stages"][stage] = merged


def _manual_lane_like(item) -> bool:
    """An S6 manual qa-runner dispatch (the kind `Controller._lane_beside_running` admits beside another). Pure; never raises."""
    return (isinstance(item, dict) and item.get("stage") == "S6" and item.get("role") == "qa-runner"
            and item.get("execution_kind") == "manual")


def _scope_cases(item):
    """The set of case ids of a dispatch record's `scope`, or None when it is not a non-empty list of non-empty strings (an unreadable
    scope is not disjoint, AR-28). The one reader for the S5 window and the S6 lane admission. Pure; the caller passes a dict."""
    scope = item.get("scope")
    if not isinstance(scope, list) or not scope or not all(isinstance(c, str) and c for c in scope):
        return None
    return set(scope)


def stage_entry_beside_running(state, d, entry):
    """The entry the stage of dispatch `d` is given by an accept/checkpoint that wrote `entry` (t-1937 TR3-4, S-2).

    Two S5 windows can run at once (`Controller._window_beside_running`), and the one that stops first used to write `pending` (or its
    stop status) over a stage that another window is still working in: every reader of "the stage is running" then misread it
    (`run_suite.active_story_stage`, the guard, `exit_gate`). INVARIANT: while another S5 dispatch is `running`, the stage stays
    `running`, with the id of a running one (the lowest id, so a replay gives the same state); a `completed` entry is never touched
    (the backstop in accept validate refuses a close beside a running window, and a journal that holds one keeps it). Derived from
    the state at this event's sequence, so the replay is deterministic. A story with no two running dispatches gets `entry` back, the
    same object: its replay is byte-identical to the one before this function (`replay_serial_journal_identical`)."""
    if d.get("stage") not in ("S5", "S6") or entry.get("status") == "completed":
        return entry
    if d.get("stage") == "S6":
        # t-2147 TR3-9d (critic B5): an S6 manual lane stops beside a running S6 manual sibling. Only manual qa-runner dispatches
        # of S6 count, so a story with one running dispatch gets `entry` back, the same object (serial replay byte-identical).
        if not _manual_lane_like(d):
            return entry
        running = sorted(str(o.get("id")) for o in state["dispatches"].values()
                         if isinstance(o, dict) and o.get("status") == "running" and o.get("id") != d.get("id")
                         and _manual_lane_like(o))
        if not running:
            return entry
        return {"status": "running", "dispatch_id": running[0]}
    running = sorted(str(o.get("id")) for o in state["dispatches"].values()
                     if isinstance(o, dict) and o.get("stage") == "S5" and o.get("status") == "running"
                     and o.get("id") != d.get("id"))
    if not running:
        return entry
    return {"status": "running", "dispatch_id": running[0]}


def reopen_stage(state, stage, reason, marker="repaired_by_recover"):
    """A stage whose dispatch was closed without acceptance is startable again.

    An accepted stage does not lose its acceptance because a rework round of it ended badly
    (TP2-2523 was exactly that: a rework dispatch of an accepted S3). It keeps the
    decision that was already recorded and only stops pointing at a dispatch nobody is doing.

    This is an internal repair, so it never reopens a CLOSED story: reopening one is a
    person's decision and is recorded as `reopened_at` + `reopened_by_words` by the two
    operations that carry their words (`release`, `rework`).
    """
    if not stage:
        return
    entry = state["stages"].get(stage) or {}
    if entry.get("status") in ("completed", "skipped"):
        merged = dict(entry, later_work_settled=True)
        merged.pop("active_dispatch_id", None)
        if merged.get("rework"):
            merged["rework_status"] = "settled"
            merged["rework_reason"] = reason or merged.get("rework_reason", "")
        state["stages"][stage] = merged
        return
    state["stages"][stage] = {"status": "pending", "reason": reason, marker: True}


# What a stage entry says about the run it WAS, which pipeline.json must stop saying once the
# controller's entry no longer carries it: `update` never removes a key, so a stage lowered
# (or closed again by a real run) kept `code_only`, the code-only receipt and the later-work
# marks of its previous life (H14, the rework-marks pop of `_project_pipeline` is the precedent).
#
# ONE rule, which keys of `STAGE_RUN_MARKS` survive which transition (C3-20; `_carry_run_marks` is the
# only place that copies them over a close, every writer of a stage entry below goes through it):
#   writer: transition                                                   marks
#   stage_transition, set_stage: completed -> completed, previous has    CARRY (a second code close, an
#     no `rework`                                                          `accept` with `stage_complete` on a
#                                                                          code-closed stage). The marks describe
#                                                                          the CLOSE, not the dispatch id, so a
#                                                                          different dispatch id still carries
#   stage_transition: completed -> non-completed (rework sub-state)     CARRY (`dict(previous, rework=True, ..)`)
#   stage_transition with `bind_only` (HF9-1, a repair dispatch bound   WRITES NO stage entry (the agent id goes onto
#     on an accepted stage)                                               the dispatch record only; nothing to carry or drop)
#   set_stage: completed -> non-completed (later work; stays completed) CARRY (`dict(previous, later_work_..)`)
#   a close after a rework (previous has `rework`): a real run           DROP (fresh entry, invariant ii of C3-14)
#   set_stage / lower_stage / `rerun_after` stamp on a non-completed
#     stage, or on a stage with no entry yet                             DROP (fresh entry; `lower_stage` names its own)
#   state_repair `stage_completed` naming a dispatch (a role ran)        DROP (`repaired_by_recover` is what stays)
#   state_repair `stage_completed` naming NO dispatch                    the first rule above (nothing ran, so a
#                                                                          code-closed stage keeps its receipt)
#   `code_only` event                                                    WRITES them (fresh entry with the receipt, and the
#                                                                          `passed_over` names of the work it closed over)
STAGE_RUN_MARKS = ("rerun_after", "code_only", "receipt_id", "later_work_status", "later_work_settled", "passed_over")


def _carry_run_marks(previous, entry):
    """`entry` (a `completed` entry about to replace `previous`) with the run marks of `previous` laid over it
    when the table above says CARRY: both are `completed` and `previous` was not reworked. Else `entry`, whole."""
    if previous.get("status") == "completed" and entry.get("status") == "completed" and "rework" not in previous:
        return dict(entry, **{key: previous[key] for key in STAGE_RUN_MARKS if key in previous})
    return entry


def stale_records(state, dispatch_ids=(), decision_ids=(), rework_id=""):
    """THE staling loop: the `invalidate` replay and the `rerun_after` stamp both go through it.

    A dispatch or a decision becomes `stale`; a dispatch staled by a rework also carries
    `stale_by_rework: <rework id>`. An id with no receipt is a historical journal's, kept as
    an imported `stale` record (never as accepted work); a rework's stamp is validated to name
    only receipts that exist, so on its road that branch is not reached."""
    marks = {"stale_by_rework": rework_id} if rework_id else {}
    for did in dispatch_ids:
        dispatch = state["dispatches"].get(did)
        if dispatch:
            dispatch.update(status="stale", **marks)
        elif not rework_id:
            # Historical journals may predate dispatch_started receipts. Preserve
            # the invalidation without fabricating acceptance or a completed stage.
            state["dispatches"][did] = {
                "id": did, "status": "stale", "stage": None, "imported": True,
                "reason": "legacy invalidation references unavailable dispatch receipt",
            }
    for did in decision_ids:
        decision = state["decisions"].get(did)
        if decision:
            decision["status"] = "stale"
        elif not rework_id:
            state["decisions"][did] = {
                "id": did, "status": "stale", "imported": True,
                "reason": "legacy invalidation references unavailable decision receipt",
            }


def lower_stage(state, stage, reason, **marks):
    """A stage goes back to `pending`, whole: nothing of the run it had survives in its entry."""
    state["stages"][stage] = {"status": "pending", "reason": reason, **marks}


def apply_rerun_after(state, rework_id, stage, stamp):
    """The replay of a rework's `rerun_after` stamp (t-675, F6): what the rework makes run again.

    In this order: (1) each named review still `accepted` goes `stale` (+ `stale_by_rework`),
    and when any did, the reworked stage itself is `running` until the rework is accepted;
    (2) each named stage still `completed` goes back to `pending`, its accepted dispatches
    `stale` — a `skipped` stage is never touched, a code-only stage is lowered by status, no
    dispatch needed; (3) each named gate decision still `approved` goes `stale`. Every step
    reads the state it finds, so applying the same stamp twice changes nothing."""
    reviews = [did for did in stamp.get("reviews") or []
               if (state["dispatches"].get(did) or {}).get("status") == "accepted"]
    if reviews:
        stale_records(state, reviews, (), rework_id)
        state["stages"][stage] = {"status": "running", "dispatch_id": rework_id, "rerun_after": rework_id}
    for name in stamp.get("stages") or []:
        if (state["stages"].get(name) or {}).get("status") != "completed":
            continue
        stale_records(state, [did for did, d in state["dispatches"].items()
                              if d.get("stage") == name and d.get("status") == "accepted"], (), rework_id)
        lower_stage(state, name, f"runs again after the rework {rework_id} of {stage}", rerun_after=rework_id)
    stale_records(state, (), [did for did in stamp.get("decisions") or []
                              if (state["decisions"].get(did) or {}).get("status") == "approved"])


def now_iso():
    return stamp_utc(time.time())


# --- the orders of gate B (t-1509, GB-1a): what a person decided at gate B is carried out BEFORE the story is closed ---
# A decision of gate B can order work: the bug reporter files the drafts the person chose (`bugs`), the delivery step opens the
# MR (`mr`). Which executor does which order is a row of data (`stages.json` S8 `gate_orders`, read by `hooklib.gate_orders`);
# this block is the ONE producer of the statuses (`gate_b_orders`), and `hooklib.story_closure` the one reader of what they
# mean for the story (`executing` while an order is due, `closed` after).
ORDER_DUE, ORDER_DONE, ORDER_CANCELLED, ORDER_NOT_ORDERED = "due", "done", "cancelled", "not_ordered"
BUGS_FLAG_VALUES = ("ordered", "not_ordered")          # `gate-decision --gate B --bugs`
MR_FLAG_VALUES = ("open", "do_not_open", "not_offered")  # `--mr`, the lexicon of handoffs/gate-b-to-delivery.yaml `delivery.mr`
SETTLE_OUTCOMES = (ORDER_DONE, ORDER_CANCELLED)
# `settle_order --reason-code`: the reasons the FACTORY (not a person) cancels an order for, each with the delivery step's own record as `--ref`
SETTLE_REASON_CODES = ("no_trace", "delivered_without_mr")
SETTLE_REF_MAX = 2000
EXECUTING = "executing"
# the keys of a gate B decision that only the projection writes (F4): a request carrying one is refused, the projection drops it
PROJECTION_OWNED_B_KEYS = ("orders_settled", "orders_due", "decided_seq", "decided_at")


def stamp_utc(epoch):
    """An event's `created_at` (epoch seconds) in the form of `now_iso()` / `closed_at` - UTC, `+00:00`; `""` when it is not a time."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(float(epoch)))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _seq(record, key="decided_seq"):
    value = record.get(key) if isinstance(record, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def latest_gate_b(state):
    """The newest gate B decision of the state by the event it was recorded in (`decided_seq`), or None. The LAST decision
    wins: a second one replaces the first, orders and all."""
    best = None
    for decision in (state.get("decisions") or {}).values():
        if isinstance(decision, dict) and decision.get("gate") == "B" and (best is None or _seq(decision) >= _seq(best)):
            best = decision
    return best


def executes_order(spec, dispatch) -> bool:
    """Is this dispatch the executor `gate_orders` names for the order (a stage and a role)? `delivery` is no dispatch."""
    executor = spec.get("executor") if isinstance(spec, dict) else None
    return (isinstance(executor, dict) and isinstance(dispatch, dict)
            and executor.get("stage") == dispatch.get("stage") and executor.get("role") == dispatch.get("role"))


def _base_orders(decision, state, retro_guard=True):
    """`{order: due | not_ordered}` before any execution is counted: from the decision's own `orders`, or - for a decision that
    carries none (recorded before 0.10.5, or a raw `decision` request) - derived as the older stories need it (F-5): `bugs` is
    due when drafts were chosen and the retro has not started (`retro_guard`; a retro that is running or done already read
    the story as it was, and an order derived after the fact would vanish again at its acceptance); `mr` is not derived.
    A decision that is not `approved` orders nothing. An unreadable value is `due` - the error direction is "not finished"."""
    table = gate_orders()
    raw = decision.get("orders")
    names = list(table) + [name for name in (raw if isinstance(raw, dict) else ()) if name not in table]
    if decision.get("status") != "approved":
        return {name: ORDER_NOT_ORDERED for name in names}
    if isinstance(raw, dict):
        return {name: ORDER_NOT_ORDERED if raw.get(name, ORDER_NOT_ORDERED) == ORDER_NOT_ORDERED else ORDER_DUE for name in names}
    drafts = decision.get("selected_drafts")
    retro = (state.get("stages", {}).get(RETRO_STAGE) or {}).get("status")
    derived = bool(isinstance(drafts, list) and drafts) and not (retro_guard and retro in ("completed", "skipped", "running"))
    return {name: ORDER_DUE if name == "bugs" and derived else ORDER_NOT_ORDERED for name in names}


def gate_b_orders(state) -> dict:
    """THE producer of the orders of the newest gate B decision: `{order: due | done | cancelled | not_ordered}`, `{}` while gate B
    is not decided. The base statuses of the decision (`_base_orders`) with the executions the projection recorded in
    `orders_settled` laid over the `due` ones. `closure_view` and `_project_pipeline` write these; nothing else derives them."""
    decision = latest_gate_b(state)
    if decision is None:
        return {}
    settled = decision.get("orders_settled") if isinstance(decision.get("orders_settled"), dict) else {}
    out = {}
    for name, status in _base_orders(decision, state).items():
        entry = settled.get(name)
        out[name] = (entry["outcome"] if status == ORDER_DUE and isinstance(entry, dict)
                     and entry.get("outcome") in SETTLE_OUTCOMES else status)
    return out


def orders_due(state) -> list:
    """The orders of the newest gate B decision whose executors have not finished, in the order `stages.json` lists them."""
    return [name for name, status in gate_b_orders(state).items() if status == ORDER_DUE]


def settle_by_executor(state, dispatch, outcome, event, words=""):
    """The projection's half of the producer: the executor of a `due` order of the newest gate B decision was ACCEPTED
    (`done`) or RELEASED by a person (`cancelled`, with their words - B4). Only a dispatch made after that decision counts,
    by event number; one made before it (the scribe, a reporter of the older decision) settles nothing, and an order is
    settled once. Writes `orders_settled[order]` on the decision - the state, never a payload (FR-45)."""
    decision = latest_gate_b(state)
    if decision is None or _seq(dispatch, "dispatched_seq") <= _seq(decision):
        return
    base = _base_orders(decision, state, retro_guard=False)
    settled = decision.setdefault("orders_settled", {})
    for order, spec in gate_orders().items():
        if executes_order(spec, dispatch) and base.get(order) == ORDER_DUE and order not in settled:
            entry = {"outcome": outcome, "dispatch_id": dispatch.get("id"), "seq": event["sequence"],
                     "at": stamp_utc(event.get("created_at"))}
            settled[order] = dict(entry, words=words) if words else entry


def gate_b_record(state, decision):
    """`decision` as pipeline.json's `gates.B` - the controller's vocabulary translated into the file's - with the produced
    orders beside it: `orders` (the statuses), `orders_due`, `decided_seq` and `decided_at` (from the projection). One
    translation for `closure_view` (what the readers see) and `_project_pipeline` (what the file keeps)."""
    record = dict(decision, decision="approved" if decision["status"] == "approved" else decision["status"])
    orders = gate_b_orders(state)
    record["orders"] = orders
    record[ORDERS_DUE] = [name for name, status in orders.items() if status == ORDER_DUE]
    return record


def _executing_refusal(ticket, stage, due) -> str:
    """Why `stage` does not start while the orders of gate B are due, with a door the refused party can use for each order
    (FR-1, FR-2, GB-3): the executor starts, the order is called off by a person's word, or the person reopens the story."""
    table = gate_orders()
    runs = []
    for name in due:
        executor = (table.get(name) or {}).get("executor")
        runs.append(f"`{name}` is carried out by `story_step.py start --task {ticket} --stage {executor['stage']} --role "
                    f"{executor['role']}`" if isinstance(executor, dict)
                    else f"`{name}` is carried out by the delivery step, and whoever delivers settles it: `controller.py "
                         f"--operation settle_order --order {name} --outcome done --ref <the MR's link or id>`")
    return (f"gate B is decided and S8 is done, but what the person decided there is not carried out yet ({', '.join(due) or 'unknown'}), "
            f"so {stage} does not start on the story now: only the executors of those orders run. " + "; ".join(runs) + ". "
            "`--operation next` lists the orders and who runs them. A person who calls an order off says so: "
            f"`{person_words.door('controller.py --operation settle_order --order ' + (due[0] if due else '<order>') + ' --outcome cancelled')}`; "
            "new work on the story starts on a person's word: "
            f"`{person_words.door('controller.py --operation rework --stage <Sn> --role <role> --cases <ids> --brief')}`. "
            "The retro (S9) runs after the orders are settled.")


def _closed_story_doors(state, p=None, held=None) -> str:
    """The doors that OPEN on a closed story, one clause each, and only those that open on THIS state (FR-2, FR-57, GB-3 p.1):
    (a) `reopen_story` only when work is held back; (b) `rework` only when an accepted dispatch of the stage and role exists
    (for `p`, that stage and role; with no `p`, any); (c) the new gate B decision for the executor of an order of gate B, which
    is the one door the first bug reporter has on a closed story (always offered when there is no `p`: a late bug is a new
    decision); (d) the retro needs no word. Nothing that opens: `--operation next` says what the story does now."""
    held = held_dispatches(state, True) if held is None else held
    stage, role = (str(p.get("stage") or ""), str(p.get("role") or "")) if p else ("", "")
    doors = []
    if held:
        doors.append("for work that never started, the person's word goes in "
                     f"`{person_words.door('controller.py --operation reopen_story --dispatch <the held dispatch ids>')}` "
                     "(`--operation next` lists them as `held`)")
    if any(isinstance(d, dict) and d.get("status") == "accepted" and (not p or (d.get("stage") == stage and d.get("role") == role))
           for d in (state.get("dispatches") or {}).values()):
        doors.append("for new work on accepted work, "
                     f"`{person_words.door('controller.py --operation rework --stage {} --role {} --cases <ids> --brief'.format(stage or '<Sn>', role or '<role>'))}` "
                     "reopens the story with the person's words")
    if p is None or any(executes_order(spec, p) for spec in gate_orders().values()):
        decision = 'controller.py --operation gate-decision --gate B --drafts "<refs>" --bugs ordered --mr not_offered'
        doors.append(f"to file a bug or open the MR now, a new decision of gate B: `{person_words.door(decision)}`")
    if stage == RETRO_STAGE:
        doors.append("the retro (S9) needs no word")
    return ("Doors that open on this story now: " + "; ".join(doors) + "." if doors
            else "No door opens on this story for it: `--operation next` says what the story does now.")


def _execute_gate_b_action(s, held=()) -> dict:
    """The `next` answer while the orders of gate B are due: `{"action": "execute_gate_b", "orders": [...], "held": [...],
    "revision", "reason"}`. Each order names its executor (a stage and role, or `delivery`), the drafts the person chose
    and whether a person released the executor. `held` is the never-started work a person's word is still owed on - the
    executor goes first. No `--reason` is named in the text (that option cannot carry a person's words)."""
    decision, table = latest_gate_b(s) or {}, gate_orders()
    orders = []
    for name in orders_due(s):
        spec = table.get(name) or {}
        released = any(executes_order(spec, d) and d.get("status") == RELEASED and _seq(d, "dispatched_seq") > _seq(decision)
                       for d in (s.get("dispatches") or {}).values())
        orders.append({"order": name, "status": ORDER_DUE, "executor": spec.get("executor"),
                       "selected_drafts": list(decision.get("selected_drafts") or []) if name == "bugs" else [],
                       "released_by_person": released})
    action = {"action": "execute_gate_b", "orders": orders, "revision": s["revision"],
              "reason": "gate B is decided and S8 is done, but what the person decided there is not carried out yet: "
                        + "; ".join(f"`{o['order']}` by " + (f"{o['executor']['role']} ({o['executor']['stage']})" if isinstance(o["executor"], dict)
                                                          else "the delivery step") for o in orders)
                        + ". The story is closed when every order is done or called off "
                          "(`--operation settle_order`); the retro waits for that."}
    if held:
        action["held"] = [{"dispatch_id": d.get("id"), "stage": d.get("stage"), "role": d.get("role"),
                           "reason": str(d.get("reason") or "this dispatch never reached an agent")} for d in held]
    return action


def closure_view(state, pipeline=None):
    """The controller's state spoken in pipeline.json's vocabulary, for `story_closure` / `story_closed`.

    There is exactly ONE reading of "this story is closed" (`hooklib.story_closure`), and the
    controller does not get a second one: it says `completed` where the file says `done` and
    keeps gate decisions under `decisions` rather than `gates`, so the state is translated
    INTO that vocabulary here — the same translation the projection writes to disk below.
    """
    view = {"stages": {}, "gates": {}}
    if isinstance(pipeline, dict):
        for section in ("stages", "gates"):
            view[section] = {name: dict(entry)
                             for name, entry in (pipeline.get(section) or {}).items()
                             if isinstance(entry, dict)}
        for key in (CLOSED_AT, REOPENED_AT):
            if pipeline.get(key):
                view[key] = pipeline[key]
    for name, entry in (state.get("stages") or {}).items():
        status = (entry or {}).get("status")
        merged = dict(view["stages"].get(name) or {}, **(entry or {}))
        merged["status"] = {"completed": "done"}.get(status, status)
        view["stages"][name] = merged
    for decision in (state.get("decisions") or {}).values():
        if decision.get("gate"):
            view["gates"][decision["gate"]] = dict(
                decision,
                decision="approved" if decision["status"] == "approved" else decision["status"])
    latest = latest_gate_b(state)
    if latest is not None:
        view["gates"]["B"] = gate_b_record(state, latest)
    if state.get(REOPENED_AT):
        view[REOPENED_AT] = state[REOPENED_AT]
    return view


def closure_of(state, pipeline=None) -> dict:
    """`hooklib.story_closure` over the controller's own state - the one place the controller asks "closed / executing / open"."""
    return story_closure(closure_view(state, pipeline))


def relaunch_shape(s, d):
    """Could `next` relaunch this dispatch, leaving the story's closure out of it? (B-331, C1-6a.)

    The ONE shape test of `relaunchable` (the move) and `held_dispatches` (the question): a dispatch that never
    reached an agent, or that a person released, with the fields a packet is built from; on a stage still open, or
    a never-started REWORK of a completed one (the stage is completed BECAUSE the work was accepted, and the repair
    somebody asked for is what is still owed). Whether the story may start it NOW is the closure's question."""
    if d.get("status") not in (NEVER_STARTED, RELEASED):
        return False
    if not (d.get("stage") and d.get("role") and d.get("input_hash")):
        return False        # no packet can be built from it: it has no move to offer
    if (s["stages"].get(str(d.get("stage")), {}) or {}).get("status") not in ("completed", "skipped"):
        return True
    return bool(d.get("rework_of")) and d.get("status") == NEVER_STARTED


def has_later_work(entries, index):
    """Is there a LATER dispatch of the same stage and role than `entries[index]` that is not itself a dispatch that never
    started or was released? The ONE predicate behind both "the last of each stage+role" readings: `held_dispatches` (the
    question) and `relaunchable` in `next` (the move) - a drift between them would make `held` name what `next` never
    relaunches. A later dispatch that is itself never started or released does not hide the earlier one (it is the later one
    that is picked)."""
    d = entries[index]
    return any(later.get("stage") == d.get("stage") and later.get("role") == d.get("role")
               and later.get("status") not in (NEVER_STARTED, RELEASED) for later in entries[index + 1:])


def left_held_ids(s):
    """The held dispatches a `reopen_story` word did NOT name (B1, C1-6a): `reopen_left_held` minus what a later word covered.
    `next` does not relaunch them and the dispatch check refuses a relaunch packet of them, until a person says `run again`
    for them or `leave` (a word covers only what the question named)."""
    return set(s.get("reopen_left_held") or ()) - set(s.get("reopen_covers") or ())


def owed_executor(s, d) -> bool:
    """Is this dispatch the executor of an order of gate B that is `due` (a dispatch made AFTER that decision, by event number)?
    Such a dispatch is the story's own work to do (`execute_gate_b`), never work a person's word is owed on."""
    decision = latest_gate_b(s)
    if decision is None or _seq(d, "dispatched_seq") <= _seq(decision):
        return False
    table, due = gate_orders(), orders_due(s)
    return any(executes_order(table.get(name), d) for name in due)


def relaunch_candidates(s, released=True, owed=True):
    """The dispatches `next` would relaunch if the story's closure were not asked: `relaunch_shape` accepts them, the retro (S9)
    is left out, the last of each stage+role. A RELEASED one is a candidate (`reopen_story` must not relaunch it unasked) but
    never `held`: `released=False` is the reading `held_dispatches` takes (a released dispatch does not hide an earlier one
    that never started - it is not in the question at all). `owed=False` leaves out the executor of a due order of gate B."""
    entries = list((s.get("dispatches") or {}).values())
    last = {}
    for index, d in enumerate(entries):
        if d.get("stage") == RETRO_STAGE or not relaunch_shape(s, d) or has_later_work(entries, index):
            continue
        if not owed and owed_executor(s, d):
            continue
        if d.get("status") == RELEASED and not released:
            continue
        last[(d.get("stage"), d.get("role"))] = d
    return list(last.values())


def held_dispatches(s, closed):
    """The work a person's word is owed on before it starts: the dispatches that never started and that `next` would relaunch
    (`relaunch_candidates`), a RELEASED one left out.

    INVARIANT (AR-20): `held` is the list of dispatches never started while the story is closed, and it shrinks ONLY through
    `reopen_story` (the dispatch runs, the story open) or `leave_unlaunched` (the dispatch is history, its stage
    `completed_by: person_left`). On a CLOSED story that is every such dispatch. On an OPEN story it is the ones a PARTIAL
    `reopen_story` left out (`left_held_ids`) and nothing else: a story reopened by another road holds nothing back, and a
    dispatch that merely never started on an open stage is ordinary work for `next`. `[]` for an open story with none left.

    A story closed BEFORE `reopen_story` existed carries no `reopened_at`: `closed` is then the plain reading, and
    every such dispatch is held - the same answer as for a story that was never reopened.

    A dispatch a person RELEASED is not held (the Lead's answer to Q1, t-699 §12): the word that released it freed the
    stage and asked for nothing, and `leave_unlaunched` refuses it by name - so the question must not offer it."""
    left = left_held_ids(s)
    if not closed and not left:
        return []
    return [d for d in relaunch_candidates(s, released=False, owed=False) if closed or str(d.get("id")) in left]


def stamp_closure(pipeline, state=None, at=""):
    """Record in the story's own file that it is finished, once. Returns the keys written.

    Nothing in the factory said it. TP2-2534 went S1-S8, gates A and B, MR merged,
    suite green — and its pipeline.json still held a stage `running`, so the stage guard's
    "single running story" fallback counted it for two days and every dispatch of the LIVE
    story was refused as ambiguous (I-92). The rule stays in `hooklib.story_closed`; this
    only writes down what that function already reads, so that a reopening — which is a
    person's word, never a stray `running` — has something to be later than. An existing
    `closed_at` is never overwritten: a story closes once, at the decision's own time. What that does
    NOT mean (B1, C1-6a) is that a reopened story has nothing held: `reopened_at` later than `closed_at`
    keeps it open for every reader, so work a PARTIAL `reopen_story` left held cannot wait for a second
    closure to be asked about - its question rides on the open story through `reopen_left_held`
    (`held_dispatches`). No second `closed_at` is written here; the "closes once" reading is kept.
    """
    written = []
    reopened = str((state or {}).get(REOPENED_AT) or "")
    if reopened and reopened > str(pipeline.get(REOPENED_AT) or ""):
        pipeline[REOPENED_AT] = reopened
        pipeline[REOPENED_BY_WORDS] = str((state or {}).get(REOPENED_BY_WORDS) or "")
        written.append(REOPENED_AT)
    if not pipeline.get(CLOSED_AT):
        closed = story_closed(pipeline)
        if closed:
            # A story from 0.7.x carries no decision time to inherit; `legacy` is that gap,
            # and the stamp records when the factory first read the two facts instead.
            pipeline[CLOSED_AT] = (at or now_iso()) if closed == "legacy" else closed
            pipeline["closed_by"] = CLOSED_BY
            written.append(CLOSED_AT)
    return written


def dispatch_life_key(dispatch) -> str:
    """The suffix every per-dispatch idempotency key (and the content of a liveness fix) carries once the dispatch was resumed.

    FB-4: a dispatch stopped for a person and continued by its own agent is ONE record with several lives. A key built from the
    dispatch id alone answers the second stop (or return) of the second life with the first one's stored event, before any
    validation. `""` for a dispatch never resumed - every key is then byte-equal to the one written before this existed, so a
    journal in flight replays identically; `":r<n>"` after n resumes. Never raises: a record that is not a dict, with no
    `resumes`, or with `resumes` that is not a non-empty list, is a dispatch with no resume (the error direction is toward
    today's key). The ONE reader of `resumes` for keys (AR-15): `story_step.pause`, `build_checkpoint_request`, `record_return`
    and `liveness_fixes` call it."""
    resumes = dispatch.get("resumes") if isinstance(dispatch, dict) else None
    return ":r" + str(len(resumes)) if isinstance(resumes, list) and resumes else ""


# --- the story held for code (t-2181 PC-6, t-2277 J-4) --------------------------------------------------------------------
# ONE state, two causes: `s5_absent_side` (a deliverable side is absent after S5; held from S6) and `first_look_stop` (the person
# stopped after the first look; held from S3). The record is `state["awaiting"]` = {since, sides, packet, s5_dispatch, cause,
# held_from[, stopped: {at, words}]}; it is read ONLY through `contract.awaiting` (which gives a record without `cause` / `held_from`
# the old reading `s5_absent_side` / `S6`, AR-13) and is projected to `pipeline.awaiting`. The word `first_look_stop` is a protocol
# word of the record, like the operation names; the stage a hold starts at is DATA of the record (`held_from`), never a stage
# number in code.
FIRST_LOOK_STOP = "first_look_stop"
HELD_FROM_RE = re.compile(r"^S[0-9]$")


def _project_hold(state, kind, p, event):
    """The four events of the hold folded into `state["awaiting"]` (and the fifth, `first_look_continued`, into `first_look_continue`).
    `await` writes the record whole, replacing any earlier one (a stopped mark with it); `stop_waiting` marks it stopped; `arrive`
    clears it; `first_look_continued` records the person's word beside the keys it was given and clears a `first_look_stop` hold that
    is not stopped. Pure on `(state, payload, event)`, so a replay gives the same state."""
    at = stamp_utc(event.get("created_at"))
    record = state.get("awaiting") if isinstance(state.get("awaiting"), dict) else None
    if kind == "await":
        entry = {"since": str(p.get("since") or at), "sides": copy.deepcopy(p.get("sides") if isinstance(p.get("sides"), dict) else {}),
                 "packet": copy.deepcopy(p.get("packet")),
                 "s5_dispatch": None if p.get("cause") == FIRST_LOOK_STOP else p.get("s5_dispatch"),
                 # the identity of THIS hold: the `await` event's own number (a hold's idempotency keys carry it, F1)
                 "opened": event.get("sequence")}
        entry.update({key: str(p[key]) for key in ("cause", "held_from") if p.get(key)})
        state["awaiting"] = entry
    elif kind == "arrive":
        state.pop("awaiting", None)
    elif kind == "stop_waiting":
        if record is not None:
            state["awaiting"] = dict(record, stopped={"at": str(p.get("at") or at), "words": str(p.get("words") or "")})
    elif kind == "first_look_continued":
        state["first_look_continue"] = {"source_head": p.get("source_head"), "register_hash": p.get("register_hash"),
                                        "words": str(p.get("words") or ""), "at": str(p.get("at") or at)}
        if record is not None and record.get("cause") == FIRST_LOOK_STOP and not record.get("stopped"):
            state.pop("awaiting", None)


def _hold_of(s):
    """(hold, number): the story's hold as `contract.awaiting` reads it from the controller state's own record (never re-parsed
    here), and the number of the stage it starts at. A `held_from` that is not `S<digit>` reads as the reader's default stage
    (`contract.AWAITING_DEFAULT_HELD_FROM`): the record is written by `await`, whose validation refuses any other spelling, so only
    a hand-damaged record reaches that line, and the default holds from S6 (the original t-2181 reading)."""
    import contract
    hold = contract.awaiting({"awaiting": s.get("awaiting")} if isinstance(s, dict) else {})
    text = hold["held_from"] if HELD_FROM_RE.match(hold["held_from"]) else contract.AWAITING_DEFAULT_HELD_FROM
    return hold, int(text[1:])


def _stage_no(record):
    """The number of a dispatch's stage; 99 for a stage that is not `S<digit>` - an unreadable stage reads as HELD, never as free."""
    stage = str((record or {}).get("stage") or "")
    return int(stage[1:]) if HELD_FROM_RE.match(stage) else 99


def _hold_doors(number):
    """The ONE text of the three doors out of a story held for code (FR-2, AR-9, AR-13): `arrive` (the code comes), `stop`
    (the person ends the wait) and `rework` (the person's words reopen the stages below `held_from`, S0..S<number-1>). Every
    controller site that names the doors (`next`, the rework refusal, the four operations' refusals) reads them here."""
    return {"arrive": "relaunch the story with the code (`--mr`, `--branch`, `--commit` or `--side <side>=real`): that is `arrive`",
            "stop": f"`{person_words.door('controller.py --operation stop_waiting')}` ends the wait",
            "rework": (f"a rework of S0-S{number - 1} with the person's words reopens a stopped story "
                       f"(`{person_words.door('controller.py --operation rework --stage <stage> --role <role>')}`)")}


def _hold_action(s, hold, number, held_ids):
    """The answer `next` gives for a story held for code: `awaiting_implementation` (the record, the never-started dispatches from
    `held_from` listed in `held`) or `awaiting_stopped` (terminal: the person stopped the wait, nothing is relaunched). Both name
    the cause, the stage the hold starts at and every door that leads out (FR-2, AR-9, AR-25)."""
    cause, held_from = hold["cause"], f"S{number}"
    door = _hold_doors(number)
    if hold["state"] == "stopped":
        stopped = hold.get("stopped") if isinstance(hold.get("stopped"), dict) else {}
        return {"action": "awaiting_stopped", "cause": cause, "held_from": held_from, "at": stopped.get("at"),
                "words": stopped.get("words"), "revision": s["revision"],
                "reason": f"the person stopped the wait on {str(stopped.get('at') or '')[:10]}: no stage from {held_from} runs and nothing is "
                          f"relaunched. Doors: {door['rework']}; {door['arrive']}"}
    doors = [door["arrive"], door["stop"], door["rework"]]
    if cause == FIRST_LOOK_STOP:
        doors.insert(1, f"`{person_words.door('controller.py --operation first_look_continue --source-head <H> --register-hash <R>')}` "
                        "carries on as it is (the driver passes the keys of `first_look.py show --json`)")
    else:
        doors.insert(1, "the person's answer `not ours` to the driver's question about the absent side records that side as another "
                        "team's and lifts the hold (the driver runs `arrive` naming it)")
    return {"action": "awaiting_implementation", "cause": cause, "held_from": held_from, "since": hold.get("since"),
            "sides": hold.get("sides"), "packet": hold.get("packet"), "s5_dispatch": hold.get("s5_dispatch"),
            "held": [{"dispatch_id": d.get("id"), "stage": d.get("stage"), "role": d.get("role"),
                      "reason": str(d.get("reason") or "this dispatch never reached an agent")} for d in held_ids],
            "revision": s["revision"],
            "reason": f"this story is held for code ({cause}): no stage from {held_from} runs until " + "; ".join(doors)}


def projection(events):
    state = {"schema_version": 2, "revision": 0, "dispatches": {}, "decisions": {},
             "scope": [], "stages": {}, "invalidation": [], "mutations": {}, "policies": {},
              "cumulative_counters": {}, "leases": {}, "running_jobs": [],
              "unknown_external_writes": [], "window_counters": {}}
    for event in events:
        p, kind = event["payload"], event["type"]
        # A person's word reopening a closed story travels on the event that carries their
        # words (`release`, a `rework` dispatch) rather than on an event of its own: the
        # reopening IS that operation, and a separate record could outlive or precede it.
        if p.get(REOPENED_AT):
            state[REOPENED_AT] = str(p[REOPENED_AT])
            state[REOPENED_BY_WORDS] = str(p.get("reopen_words") or "")
        if kind == "initialize":
            state.update(copy.deepcopy(p))
            # Older initialize accepted unnamed lists. Preserve those historical
            # inputs without guessing which path was the project or plugin root.
            # prepare resolves current named paths from the task/config on disk.
            if isinstance(state.get("known_paths"), list):
                state["legacy_known_paths"] = state["known_paths"]
                state["known_paths"] = {}
            imported = p.get("legacy_import") or {}
            state["stages"].update(copy.deepcopy(imported.get("stages") or {}))
            state["dispatches"].update(copy.deepcopy(imported.get("dispatches") or {}))
            state["decisions"].update(copy.deepcopy(imported.get("decisions") or {}))
        elif kind == "revise_plan":
            state.update(copy.deepcopy(p))
            for decision in state["decisions"].values():
                if decision.get("gate") == "A":
                    decision["status"] = "stale"
        elif kind == "coverage_migration":
            version = p.get("to_version")
            if version != 2:
                raise ValueError("unknown coverage migration target")
            state["coverage_contract_version"] = version
            state["coverage_migration"] = copy.deepcopy(p)
            for decision in state["decisions"].values():
                if decision.get("gate") == "A":
                    decision["status"] = "stale"
        elif kind == "stage_transition":
            # The legacy CLI participates in the same journal during migration — and it wrote
            # the status unconditionally, straight past the monotonic rule `set_stage` states
            # above. TP1-15045: after Gate-A inputs rejected the plan, the orchestrator ran
            # `stage_done --stage S3 --status running` to reopen the strategist. The accepted
            # S3 became `running`, and `stage_done --status done` then refused it because a
            # managed stage may only be closed from an accepted controller stage. The story
            # could neither go forward nor be put back, one step before Gate A.
            # Rework of an accepted stage is now a sub-state: the projection shows it, the
            # decision that was already recorded is not rewritten.
            status = {"done": "completed", "halted": "blocked"}.get(p["status"], p["status"])
            previous = state["stages"].get(p["stage"]) or {}
            if p.get("bind_only"):
                # HF9-1: a bind of a repair dispatch on an accepted stage (`stage_done` writes the flag only for a
                # running dispatch of this stage on a completed one). It carries the agent id and nothing else:
                # NO stage entry is written, so the stage stays completed and shows no `rework` sub-state. The
                # agent block below runs unchanged. A store written before the flag has no `bind_only` and
                # replays exactly as it did.
                pass
            elif previous.get("status") == "completed" and status != "completed":
                state["stages"][p["stage"]] = dict(previous, rework=True, rework_status=status,
                                                   rework_reason=p.get("digest", ""))
            else:
                # The second close of a stage already closed (not reworked): `close_by_code` writes
                # the `code_only` receipt and THEN runs `stage_done`, and the rewrite above erased
                # the receipt's marks, so `s6_closed_by_code` was false for every S6 closed by code
                # (C3-14, critic t-831 F4). A stage that carries `rework` is closed by a real run
                # and gets the fresh entry; `repaired_by_recover` is not a run mark and is not kept.
                # The rule is the one `STAGE_RUN_MARKS` states, shared with `set_stage` (C3-20).
                state["stages"][p["stage"]] = _carry_run_marks(
                    previous, {"status": status, "reason": p.get("digest", "")})
            # The host's own id of the agent running a dispatch, as `stage_done --agent-id` journals it
            # (`story_step.py bind`, the one writer that learns the id, names the dispatch it binds with
            # `--dispatch-id`): it goes onto THAT dispatch of the record, never onto the stage's entry
            # (`agent_id` is not a run mark; the block above is not touched and this one does not read
            # `state["stages"]`). The id is known only after the launch, which is why no `dispatch`
            # request can carry it. Only the dispatch the transition NAMES receives it, and only while
            # it is `running` and of this stage: a transition naming none (every store written before
            # this field existed), a name the record does not know, a dispatch already accepted or
            # settled (on a host where the Agent call returns after the role stopped, `record_return`
            # lands first and the id is dropped), an empty or blank id: nothing changes. Never a guess
            # from "the one running dispatch of the stage". `accept` and `checkpoint` merge their own
            # payload and never clear it. The event's own position is stamped beside the id
            # (`agent_bound_seq`): `_project_pipeline` names the stage's agent by the LAST BIND, which
            # is not the order the dispatches were created in. The stamp is read off the event order
            # here; the transition's identity and idempotency key are not touched.
            agent, named = p.get("agent_id"), p.get("dispatch_id")
            if isinstance(agent, str) and agent.strip() and isinstance(named, str) and named:
                target = state["dispatches"].get(named)
                if (isinstance(target, dict) and target.get("status") == "running"
                        and target.get("stage") == p["stage"]):
                    target["agent_id"] = agent.strip()
                    target["agent_bound_seq"] = event["sequence"]
        elif kind == "state_repair":
            # `recover` repairing the factory's own inconsistency, in the open.
            for fix in p.get("fixes") or []:
                if fix.get("kind") == "stage_completed" and fix.get("stage"):
                    previous = state["stages"].get(fix["stage"]) or {}
                    # The run marks of `previous` are NOT copied wholesale (C3-20): a repair naming the
                    # dispatch that closed the stage re-closes what a ROLE ran, and a `code_only` of the
                    # entry it replaces is no longer true. A repair naming none ran nothing, so the one
                    # rule of `STAGE_RUN_MARKS` decides (a code-closed stage keeps its receipt).
                    entry = {key: value for key, value in previous.items()
                             if key not in STAGE_RUN_MARKS and key != "rework"}
                    entry.update(status="completed", repaired_by_recover=True,
                                 reason=fix.get("reason", ""), dispatch_id=fix.get("dispatch_id"))
                    state["stages"][fix["stage"]] = entry if fix.get("dispatch_id") else _carry_run_marks(previous, entry)
                elif fix.get("kind") == STALE_AFTER_CLOSURE:
                    # The tail of a closed story: nobody is owed this work, because there is
                    # no work left. The dispatch is closed with the liveness vocabulary the
                    # rest of the factory already reads, and the stage goes back to what it
                    # was before the tail — an accepted stage keeps its decision.
                    dispatch = state["dispatches"].get(fix.get("dispatch_id"))
                    if dispatch and dispatch.get("status") in OPEN_AFTER_CLOSURE:
                        dispatch.update(status=fix.get("settled_as") or "superseded",
                                        repaired_by_recover=True, reason=fix.get("reason", ""),
                                        stale_after_closure=fix.get("closed_at", ""))
                    reopen_stage(state, fix.get("stage"), fix.get("reason", ""),
                                 marker="settled_after_closure")
                elif fix.get("kind") in (NEVER_STARTED, RETURNED, ABANDONED) and fix.get("dispatch_id"):
                    # The receipt stays in history — it is how the story learns what became of
                    # this dispatch — but it stops being work anybody waits for, and its stage
                    # goes back to startable. Nothing the role wrote is touched.
                    dispatch = state["dispatches"].get(fix["dispatch_id"])
                    if dispatch and dispatch.get("status") != "running":
                        # B1 (TR4-7): `liveness_fixes` reads `running` rows only, so a row that is anything else NOW was moved by
                        # another writer after the repair read it (accepted, returned, released): the repair does not touch it
                        # and does not reopen its stage
                        continue
                    if dispatch:
                        dispatch.update(status=fix["kind"], repaired_by_recover=True,
                                        reason=fix.get("reason", ""))
                        if fix.get("digest"):
                            dispatch["returned_digest"] = fix["digest"]
                    reopen_stage(state, fix.get("stage"), fix.get("reason", ""))
        elif kind == "returned":
            # A fact written by the hook on the role's stop, never a decision: the dispatch
            # stops being a job to wait for, and `next` asks the orchestrator to settle it.
            dispatch = state["dispatches"].get(p.get("dispatch_id"))
            if dispatch and dispatch.get("status") == "running":
                dispatch.update(status=RETURNED, returned_digest=str(p.get("digest") or ""),
                                returned_at=event.get("created_at"),
                                returned_by=str(p.get("agent") or ""))
        elif kind == "release":
            # A person's word, recorded. It frees the dispatch and nothing else: every
            # artifact the role wrote stays exactly where it is.
            dispatch = state["dispatches"].get(p.get("dispatch_id"))
            if dispatch:
                dispatch.update(status=RELEASED, released_by_person=str(p.get("words") or ""),
                                reason=str(p.get("reason") or p.get("words") or ""))
                settle_by_executor(state, dispatch, ORDER_CANCELLED, event, str(p.get("words") or ""))
                reopen_stage(state, dispatch.get("stage"),
                             "released by a person's word: " + str(p.get("words") or ""),
                             marker="released_by_person")
        elif kind == "reopen_story":
            # A person said `run again` to the never-started work of a CLOSED story (B-331, C1-6a): the reopening itself
            # rode in on `reopened_at` above. What is recorded here is the SET the word covers, and the held work it left
            # out (every relaunch candidate the word did not name, a RELEASED one too); `next` relaunches only the first, and
            # the second stays held (`held_dispatches` lists the never-started ones on the open story, `left_held_ids`).
            covered = {str(did) for did in p.get("dispatch_ids") or []}
            state["reopen_covers"] = sorted(set(state.get("reopen_covers") or ()) | covered)
            state["reopen_left_held"] = sorted((set(state.get("reopen_left_held") or ())
                                                | {str(did) for did in p.get("left_held") or []}) - set(state["reopen_covers"]))
        elif kind == "leave_unlaunched":
            # A person said `leave`: the work that never started is history, and its stage is DONE as far as the factory goes
            # (`completed_by: person_left`), so a later reopen never prepares it again. A stage that was already completed
            # (a rework that never started) keeps its own completion and only gains the person's words.
            said = str(p.get("words") or "")
            for did in p.get("dispatch_ids") or []:
                dispatch = state["dispatches"].get(did)
                if not dispatch:
                    continue
                dispatch.update(status="superseded", left_by_person=said, reason="left by a person's word: " + said)
                entry = state["stages"].get(dispatch.get("stage")) or {}
                if entry.get("status") in ("completed", "skipped"):
                    state["stages"][dispatch["stage"]] = dict(entry, left_by_person=said)
                else:
                    state["stages"][dispatch["stage"]] = {"status": "completed", "completed_by": "person_left",
                                                          "left_by_person": said,
                                                          "reason": "left by a person's word: " + said}
        elif kind == "dispatch":
            # A resumed dispatch names why the work is being done twice. The parent is read
            # BEFORE the supersede below overwrites its status, because the classifier reads
            # the status the parent stopped with. On TP1-15045 10 of 53 dispatches were
            # second attempts and not one of them said why, although every parent's checkpoint
            # reason held the answer.
            retry_stamp = {}
            parent_id = str(p.get("parent_retry") or p.get("relaunch_of") or "")
            if parent_id:
                from contract import retry_reason_for, retry_reason_valid
                old = state["dispatches"].get(parent_id) or {}
                words = str(p.get("words") or p.get("retry_words") or "")
                given = str(p.get("retry_reason") or "")
                retry_stamp["retry_reason"] = (given if retry_reason_valid(given)
                                               else retry_reason_for(old, words))
                if words.strip():
                    retry_stamp["retry_words"] = words
            if p.get("parent_retry"):
                state["dispatches"][p["parent_retry"]]["status"] = "superseded"
            # An imported `legacy:<stage>` receipt has no worker behind it — it is what a
            # pre-controller pipeline (or another host) left as "running". A real dispatch of
            # that stage IS the ownership reconciliation it asks for. Without this the
            # placeholder stayed `incomplete` for the life of the story and sat in every
            # checkpoint as a blocker nobody could clear (TP1-15045, Codex -> Claude).
            for other in state["dispatches"].values():
                if (other.get("imported") and other.get("stage") == p["stage"]
                        and other.get("status") == "incomplete"):
                    other.update(status="superseded", superseded_by=p["id"])
            # `request_binding` is written ONCE, here, from the request as committed: nothing the
            # dispatch goes through afterwards (a checkpoint, an acceptance, a liveness repair)
            # rewrites it, so a continuation can carry the original request. It lives on the
            # record, never in the payload (FR-45: a payload the validator or the projection
            # grew would break the idempotent replay of the same request), and the replay of
            # the journal gives it to every dispatch of a story already in flight.
            state["dispatches"][p["id"]] = dict(p, status="running", **retry_stamp,
                                                request_binding=request_binding(p))
            # the event's own number: "made after the gate B decision" is a comparison of numbers, never of times (two events
            # can share a second)
            state["dispatches"][p["id"]]["dispatched_seq"] = event["sequence"]
            set_stage(state, p["stage"], {"status": "running", "dispatch_id": p["id"]})
            # A rework that carries a person's words may stamp what must run again after it
            # (F6): one more lowering path, in the event itself, so a crash cannot split it
            # from the rework and a replay of the journal gives the same state.
            if isinstance(p.get("rerun_after"), dict):
                apply_rerun_after(state, p["id"], p["stage"], p["rerun_after"])
            # t-2181 PC-6 (B4): the person's rework of S0..held_from-1 on a STOPPED story. Like `reopened_at` above, the word travels
            # on the event that carries the rework (a separate event could outlive a dispatch that never committed): the story is
            # awaiting again, and the rework runs inside the hold.
            if isinstance(p.get("await_reopened"), dict) and isinstance(state.get("awaiting"), dict):
                # `reopened` is the identity of this reopening (the dispatch event's own number): a later stop is a new hold
                state["awaiting"] = dict({key: value for key, value in state["awaiting"].items() if key != "stopped"},
                                         reopened=event.get("sequence"))
        elif kind in ("await", "arrive", "stop_waiting", "first_look_continued"):
            _project_hold(state, kind, p, event)
        elif kind == "request_cancel":
            from worker_lifecycle import cancellation
            state["dispatches"][p["id"]]["cancellation"] = cancellation(p)
        elif kind in ("checkpoint", "accept"):
            d = state["dispatches"][p["id"]]
            # `request_binding` is the request the dispatch was made with: never taken from a
            # completion payload, whether the record has one (it stays) or has none (an imported
            # record - it stays without, and a continuation falls back to the four fields).
            d.update(copy.deepcopy({k: v for k, v in p.items() if k not in ("request_binding", "dispatched_seq")}))
            if kind == "accept" and p.get("status") == "accepted":
                settle_by_executor(state, d, ORDER_DONE, event)
            scope_key = budget_scope(d)
            evidence_hash = content_hash(p.get("evidence_refs") or p.get("checkpoint", {}).get("completed") or [])
            progress = state.setdefault("progress", {}).get(scope_key, {})
            unchanged = progress.get("unchanged", 0) + 1 if progress.get("evidence_hash") == evidence_hash else 0
            state["progress"][scope_key] = {"evidence_hash": evidence_hash, "unchanged": unchanged}
            d["no_progress_warning"] = unchanged >= 2

            delta = p.get("counters")
            if isinstance(delta, dict):
                role = d.get("role", "")
                scope_key = budget_scope(d)
                previous = state["cumulative_counters"].get(scope_key,
                    {"active_seconds": 0, "requests": 0, "output_tokens": 0, "repair_cycles": 0, "batches_per_repo": 0, "batches_per_stage": 0})
                budget = cumulative_budget(role, previous, delta, d.get("limits"))
                state["cumulative_counters"][scope_key] = budget["counters"]
                d["cumulative_counters"] = budget["counters"]
                d["telemetry_unknown"] = budget["telemetry_unknown"]
                notices = warning_milestones(budget["counters"], d.get("limits"),
                    state.setdefault("budget_warning_markers", {}).get(scope_key, []))
                state["budget_warning_markers"][scope_key] = notices["emitted"]
                d["budget_warnings"] = notices["new_markers"]
            set_stage(state, d["stage"], stage_entry_beside_running(state, d, {
                "status": "completed" if p["status"] == "accepted" and p.get("stage_complete")
                else "pending" if p["status"] == "accepted" else p["status"],
                "dispatch_id": p["id"], "reason": p.get("reason", "")}))
        elif kind == "resume":
            # FB-4: the SAME agent goes on with a dispatch stopped for a person. The stop and the first life's return move
            # into `resumes[]` (nothing is lost, and the live record no longer shows the first life's review digest as the
            # second life's result); the record is `running` again and so is its stage (`set_stage`, monotonic: a completed
            # stage stays completed under later work). Absent source keys are omitted, never null-filled.
            d = state["dispatches"][p["id"]]
            entry = {"stop_sequence": p.get("stop_sequence"), "from_status": d.get("status"),
                     "resumed_seq": event["sequence"]}
            for key in ("reason", "checkpoint", "returned_digest", "returned_at", "returned_by"):
                if key in d:
                    entry[key] = d.pop(key)
            if p.get("agent_id"):
                entry["agent_id"] = p["agent_id"]
                if not str(d.get("agent_id") or "").strip():
                    # the resume BINDS an id the record never had (as `stage_transition` does): without the stamp
                    # `contract.request_agent_id` would read it as the parent's agent that a rework came with
                    d["agent_bound_seq"] = event["sequence"]
                d["agent_id"] = p["agent_id"]
            d.setdefault("resumes", []).append(entry)
            d["status"] = "running"
            set_stage(state, d["stage"], {"status": "running", "dispatch_id": d["id"]})
        elif kind == "decision":
            state["decisions"][p["id"]] = copy.deepcopy(p)
            if p.get("gate") == "B":
                # the projection is the ONE writer of these: the event's own number (what "after the decision" compares) and time,
                # and the settled/due halves of the orders (a payload carrying them is refused by `_decision_problems`; dropped here too)
                for key in PROJECTION_OWNED_B_KEYS:
                    state["decisions"][p["id"]].pop(key, None)
                state["decisions"][p["id"]].update(decided_seq=event["sequence"], decided_at=stamp_utc(event.get("created_at")))
        elif kind == "settle_order":
            # an order of gate B settled by a person's word or by the factory's own coded reason (never by a dispatch: `accept`/`release`)
            decision = state["decisions"].get(p.get("decision_id"))
            if isinstance(decision, dict) and p.get("order"):
                entry = {"outcome": p.get("outcome"), "seq": event["sequence"], "at": stamp_utc(event.get("created_at"))}
                entry.update({key: p[key] for key in ("ref", "words", "reason_code") if p.get(key)})
                decision.setdefault("orders_settled", {})[p["order"]] = entry
        elif kind == "technical_normalize":
            state.setdefault("normalizations", []).append(copy.deepcopy(p))
        elif kind == "reconcile_dispatch":
            state["dispatches"][p["id"]].update(status="superseded", superseded_by=p["accepted_dispatch_id"],
                                               reconciliation_reason=p["reason"])
        elif kind == "semantic_reopen":
            state.setdefault("reopens", []).append(copy.deepcopy(p))
            for decision in state["decisions"].values():
                if decision.get("gate") == "A" and set(decision.get("scope") or []).intersection(p["affected_scope"]):
                    decision["status"] = "stale"
            state["stages"]["S4"] = {"status": "pending", "reason": p["reason"], "gate_a_reopened": True}
        elif kind == "handoff":
            state["leases"]["orchestrator"] = copy.deepcopy(p["lease"])
            state["last_handoff"] = copy.deepcopy(p)
            state["window_counters"] = {"model_requests": None}
            state["window_context_percent"] = None
        elif kind == "orchestrator_telemetry":
            state["window_counters"] = {"model_requests": p.get("model_requests")}
            state["window_context_percent"] = p.get("context_percent")
        elif kind == "policy":
            state["policies"][p["id"]] = copy.deepcopy(p)
            # Preparatory work deliberately has no implementation to author or run.  These
            # are typed skips, not successful execution receipts.
            for stage in ("S5", "S6"):
                state["stages"][stage] = {"status": "skipped", "policy_id": p["id"],
                                          "reason": p["reason"], "mode": p["mode"]}
        elif kind == "code_only":
            state["stages"][p["stage"]] = {"status": "completed", "code_only": True,
                                               "reason": p["reason"], "receipt_id": p["id"]}
            # TR1-9 B3/B4: the work this close passed over is set aside BY the receipt: `superseded` is in DISCOUNTED, so `next` does
            # not wait on a closed stage and `dispatch` is not refused by it; the stage entry keeps the names for the report.
            passed = [item for item in p.get("passed_over") or [] if isinstance(item, dict) and item.get("id")]
            if passed:
                state["stages"][p["stage"]]["passed_over"] = copy.deepcopy(passed)
            for item in passed:
                row = state["dispatches"].get(str(item["id"]))
                if isinstance(row, dict):
                    row["status"] = "superseded"
                    row["passed_over_by"] = p["id"]
        elif kind == "invalidate":
            state["invalidation"].append(copy.deepcopy(p))
            if p.get("source_revision"):
                state["source_revision"] = p["source_revision"]
                for decision in state["decisions"].values():
                    if decision.get("gate") and decision.get("source_revision") != p["source_revision"]:
                        decision["status"] = "stale"
                applicability = p.get("gate_a_applicability")
                if applicability:
                    prior_id = str(applicability["decision_id"])
                    prior = state["decisions"][prior_id]
                    carried_id = f"applicability:{prior_id}:{p['source_revision']}"
                    state["decisions"][carried_id] = {
                        "id": carried_id, "gate": "A", "action": prior.get("action", "approve"),
                        "status": "approved", "source_revision": p["source_revision"],
                        "input_revision": applicability["plan_revision"],
                        "scope": copy.deepcopy(applicability["scope"]),
                        "authorization_source": "carried Gate A applicability evidence",
                        "approval_kind": "applicability_carry",
                        "prior_decision_id": prior_id,
                        "prior_authorization_source": prior.get("authorization_source"),
                        "requirements_unchanged": True,
                        "evidence_refs": copy.deepcopy(applicability["evidence_refs"]),
                        "plan_content_hash": prior.get("plan_content_hash"),
                        "source_inventory_hash": prior.get("source_inventory_hash"),
                        "oracle_content_hashes": copy.deepcopy(prior.get("oracle_content_hashes") or {}),
                    }
            stale_records(state, p.get("dispatch_ids", []), p.get("decision_ids", []))
            # Receipts for unrelated windows remain in history, but this logical stage is
            # pending until the invalidated required scope has a fresh acceptance.
            affected_stages = {state["dispatches"][did].get("stage") for did in p.get("dispatch_ids", [])
                               if state["dispatches"][did].get("stage")}
            for stage in affected_stages:
                lower_stage(state, stage, "invalidated scope requires fresh acceptance")
        elif kind == "mutation":
            state["mutations"][p["id"]] = copy.deepcopy(p)
        state["revision"] = event["sequence"]
    # Derive timing from durable lifecycle facts, never from a stage_done projection.
    dispatch_stage = {}
    timing_events = []
    for event in events:
        payload = event["payload"]
        if event["type"] == "dispatch":
            dispatch_stage[payload["id"]] = payload["stage"]
            timing_events.append({"kind": "dispatch_started", "stage": payload["stage"],
                                  "timestamp": event.get("created_at")})
        elif event["type"] == "accept" and payload.get("stage_complete"):
            timing_events.append({"kind": "output_accepted", "stage": dispatch_stage.get(payload.get("id")),
                                  "timestamp": event.get("created_at")})
    state["artifact_index"] = [dict(ref, event_sequence=event["sequence"], event_type=event["type"])
                               for event in events for ref in event["payload"].get("evidence_refs", [])
                               if isinstance(ref, dict) and ref.get("path") and ref.get("sha256")]
    from telemetry_capture import stage_timings
    for stage, timing in stage_timings(timing_events).items():
        state["stages"].setdefault(stage, {}).update(timing)
    return state


class _TierEnds(Exception):
    """A helper the S5 completion collects with refused (`StateConflict`/`ValueError`): its
    refusal is the LAST item of the list, and the tier ends on it. `args` = (class, text)."""


# The three causes of a refused S6 runner packet, per half (`Controller._half_membership_problems`): the other half's / handed / nobody's.
_HALF_CAUSE_TEXTS = {
    "manual": (
        "disposed automate in the plan: {shown} - the automated half runs them "
        "(`story_step.py start --stage S6 --role qa-runner --execution-kind automation`); to check them "
        "by hand, the plan row's disposition changes (S3 rework, then gate A)",
        "handed to the person by their recorded word: {shown} - nobody dispatches them; leave them out of the block",
        "not a manual-agent case of the approved plan: {shown} - "
        "`controller.py --operation stage-scope` with `execution_kind: manual` lists the cases a block may name"),
    "automation": (
        "disposed manual-agent in the plan: {shown} - a manual block runs them "
        "(`story_step.py start --stage S6 --role qa-runner --execution-kind manual --scope <1..{cap} ids>`); "
        "to automate them, the plan row's disposition changes (S3 rework, then gate A)",
        "handed to the person by their recorded word: {shown} - nobody dispatches them; leave them out of the automated run",
        "not an automated case of the approved plan: {shown} - "
        "`controller.py --operation stage-scope` with `execution_kind: automation` lists the cases the automated half may name"),
}


class Controller:
    def __init__(self, task_root, wait_seconds=0.0):
        """`wait_seconds`: how long this controller's commits and recovers wait for an
        in-flight writer. Default 0, which is what every hook-reached caller needs; only a CLI
        entry (`main` here, stage_done, story_step) passes a wait, never a library function.

        Every commit and recover of the store is followed, once the story lock is free, by
        `refresh_derived`: one mechanism, so no commit site can forget the dashboard."""
        self.store = EventStore(task_root, after_commit=self.refresh_derived,
                                wait_seconds=wait_seconds)

    def state(self):
        return self._with_environment_jobs(projection(self.store.read()))

    def _with_environment_jobs(self, state):
        """Merge durable process facts without inventing lifecycle acceptance events."""
        directory = self.store.root / "state" / "environment-jobs"
        jobs = []
        for path in sorted_paths(directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"))
                from environment_preparation import environment_job_status
                if not isinstance(record, dict) or not record.get("idempotency_key"):
                    raise ValueError("missing environment job identity")
                job = environment_job_status(directory, record["idempotency_key"])
                if job.get("status") == "absent":
                    raise ValueError("environment job path does not match its identity")
            except (OSError, ValueError, TypeError):
                job = {"status": "unknown", "settled": False, "reason": "unreadable environment job"}
            jobs.append(dict(job, receipt_ref="state/environment-jobs/" + path.name))
        state["environment_jobs"] = jobs
        state["running_jobs"] = list(state.get("running_jobs") or []) + [
            dict(job, kind="environment_preparation") for job in jobs if not job.get("settled")]
        return state

    def _ref_issue(self, ref, what="evidence"):
        """One sentence about a `{path, sha256}` reference, or `''` when it is sound.

        Every evidence check in this file goes through `contract.evidence_ref_issue`:
        TP2-2553 refused an acceptance with the bare words "missing or outside-task
        evidence" — no path, no root, no hint that the reference was absolute — and the
        orchestrator spent a resume, a retry and two receipts finding out which of its five
        refs was the one.
        """
        from contract import evidence_ref_issue
        return evidence_ref_issue(self.store.root, ref, what)

    def _path_issue(self, raw, what="evidence"):
        """The same sentence for a check that has only a path.

        The hash comes from the file itself, so the answer is about the path and never about
        a digest the caller was never asked for.
        """
        import hashlib
        root = self.store.root.resolve()
        digest = ""
        try:
            path = Path(str(raw))
            path = (path if path.is_absolute() else root / path).resolve()
            if path.is_relative_to(root) and path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            digest = ""
        return self._ref_issue({"path": str(raw), "sha256": digest}, what)

    @staticmethod
    def _found(issues):
        """The sentences among `issues` (one per check, `''` for a sound one), in the order given."""
        return [issue for issue in issues if issue]

    def _ref_issues(self, refs, what="evidence"):
        """`_ref_issue` of every reference of `refs`: one sentence per reference that does not resolve, in the
        order of the references (the per-reference loop of `accept`, `policy`, `code_only`, `reconcile_dispatch`
        and the Gate A carry; the caller puts each sentence in the class its refusal has)."""
        return self._found(self._ref_issue(ref, what) for ref in refs)

    def prepare(self, options=None):
        """Read-only dispatch packet. Model never needs to reverse-engineer state paths."""
        options = options or {}
        state = self.state()
        root = self.store.root.resolve()
        from runtime_paths import resolve_runtime
        import contract
        known = state.get("known_paths") or {}
        # t-329 (B-249): the project is the one THIS process finds from the task's own place; the project_root the
        # state recorded at `initialize` is only the fallback for a task that sits outside any project (a story
        # copied to another machine kept the old worktree's root and prepare resolved everything against it).
        # t-304 N1 (reader #5): that fallback is a HINT, never a location - `project_for_task` adopts it only when
        # its artifact root contains the task, and refuses (naming `--project`) when no project does.
        try:
            runtime = resolve_runtime(root, None)
        except ValueError:
            from runtime_paths import project_for_task
            runtime = resolve_runtime(root, project_for_task(root, hint=known.get("project_root") or known.get("root")))
        paths = {"task_root": str(root), "plan": str(root / "work/test-plan.json"),
                 "source_inventory": str(root / "work/source-inventory.json"),
                 "manifest": str(root / "work/context-manifest.json"),
                 "bundle": str(root / "work/context-bundle.json"), **runtime}
        refs = []
        import hashlib
        for key, raw in paths.items():
            if not isinstance(raw, str):
                continue
            path = Path(raw)
            if path.is_file():
                refs.append({"kind": key, "path": path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path),
                             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        # `_next_action_for_state`, not `next_action()`: the latter closes never-started
        # dispatches and prepare stays read-only.
        packet = {"next_action": self._next_action_for_state(state, self._pipeline()),
                "resolved_paths": paths,
                "expected_revision": state["revision"], "input_refs": refs,
                "input_hash": content_hash(refs), "missing_facts": [key for key in
                    ("source_inventory", "manifest") if not Path(paths[key]).is_file()],
                "instructions": "Use accepted inputs. Prepare evidence files before acceptance; never invent hashes."}
        stage = options.get("stage") or packet["next_action"].get("stage")
        # The orchestrator typed the S5/S6 scope by hand and nothing derived it, so `[]`
        # passed every check and an empty window closed S5. Offer the computed scope
        # in the packet it already reads; it never has to be retyped from the plan.
        derived = None
        if stage in DERIVED_SCOPE_STAGES:
            packet["stage_scope"] = self.stage_scope(stage, state, options.get("execution_kind"))
            derived = packet["stage_scope"]["scope"] if packet["stage_scope"].get("derived") else None
        if stage and options.get("role"):
            request = {"id": options.get("id") or f"{stage}-{state['revision']+1}",
                       "stage": stage, "role": options["role"],
                       "scope": options.get("scope", derived if derived else state["scope"]),
                       "input_hash": packet["input_hash"],
                       # PORTABLE (t-329, B-249): `{project_root}/...` / `{plugin_root}/...`, resolved by `apply`
                       # against the roots of the process that dispatches it; `resolved_paths` above is this machine's
                       "known_paths": contract.portable_known_paths(paths, runtime["project_root"], runtime["plugin_root"]),
                       "budget": options.get("budget", {}), "expected_revision": state["revision"]}
            request["idempotency_key"] = "dispatch:" + request["id"]
            if stage == "S4" and options["role"] == "qa-case-designer":
                # The S4 designer runs before any case id exists, so its receipt carries `scope: []`
                # and could not say what it was sent to design: cmp1's gate A recorded TS-6/7/9/11
                # with author "" (B-224). The rows go beside `scope`, derived here from the plan and
                # never typed (a caller's `plan_rows` is not read), and EVERY row is listed: a row
                # whose disposition changes after the dispatch must still be credited. A plan that
                # cannot be read omits the key - absence means "made before this field", never
                # "zero rows" (`_cover_basis`).
                plan = self._plan_rows()
                if plan is not None:
                    request["plan_rows"] = sorted({str(row["id"]) for row in plan
                                                   if isinstance(row, dict) and str(row.get("id") or "")})
            if options["role"] == "qa-runner" and options.get("purpose") == FIRST_LOOK:
                request["purpose"] = FIRST_LOOK     # the first look carries its purpose from `prepare` on (t-2277 FL-5), so `apply` sees it
            if runner_kind_required(state, options["role"], options.get("purpose")):
                kind = options.get("execution_kind")
                if kind not in {"manual", "automation"}:
                    raise ValueError("new-task qa-runner packet requires execution_kind manual or automation")
                request["execution_kind"] = kind
                if kind == "manual":
                    # the block is read by the map `apply` records it by (F-1): its keys are what the half is judged on and what
                    # the packet carries; the scope it must sit in is read the same way (`apply` respells it too)
                    request["manual_case_ids"] = self._manual_keys(options.get("manual_case_ids"), state)
                    validate_manual_runner_block(
                        self._manual_keys(request["scope"], state), request["manual_case_ids"],
                        extra=self._half_membership_problems(stage, state, request["manual_case_ids"], "manual"))
                else:     # RH1-10 (DC1-15): the automated half names automated cases only, on this road as on every other
                    if derived == [] and "scope" not in options and stage == "S6":
                        # q1: a derived EMPTY half is not "no scope given": it never falls back to the whole approved scope
                        raise StateConflict(
                            "the automated half of the approved plan is empty: no case is disposed automate and left to a runner, "
                            "so there is nothing to dispatch to an automated runner - run the manual-agent cases in a manual block "
                            f"(`story_step.py start --stage S6 --role qa-runner --execution-kind manual --scope <1..{MANUAL_BLOCK_CASES} ids>`), "
                            "or change a plan row's disposition (S3 rework, then gate A)")
                    refused =self._half_membership_problems(stage, state, request["scope"], "automation")
                    if refused:
                        raise StateConflict(self.automation_half_refusal(refused))
            for key in ("repair_cause", "reason"):
                if options.get(key):
                    request[key] = options[key]
            if self._read_first(stage):
                request["read_first"] = self._read_first(stage)
            if options["role"] in REPAIR_LOOP_ROLES:
                # "Round 5 of 2 is the last one" was arithmetic done in a prompt. The numbers
                # the orchestrator tells a role come from the same ledger the cap reads.
                ledger = repair_ledger(state["dispatches"], request)
                policy = dict(DEFAULT_LIMITS, **(options.get("limits") or {}))
                packet["repair_budget"] = {
                    "counted": ledger["counted"], "by_cause": ledger["by_cause"],
                    "cap": policy.get("design_repair_cycles" if "case" in options["role"]
                                      else "repair_cycles"),
                    "mechanical": mechanical_rounds(state["dispatches"], request),
                    "mechanical_cap": self._dispatch_setting("mechanical_rounds"),
                    "passes": repair_passes(state["dispatches"], request),
                    "stand_signal": self._window_stand_signal(state, request)}
            packet["dispatch_request"] = request
        if options.get("dispatch_id"):
            evidence = []
            # K1 (C3-11): the outputs are independent of one another - every unsound one is listed
            self._raise_all([(ValueError, issue) for issue in self._found(
                self._path_issue(raw) for raw in options.get("outputs", []))])
            for raw in options.get("outputs", []):
                path = (root / raw).resolve()
                evidence.append({"path": path.relative_to(root).as_posix(),
                                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            packet["accept_request"] = {"id": options["dispatch_id"], "status": "accepted",
                "stage_complete": options.get("stage_complete", False), "evidence_refs": evidence,
                "expected_revision": state["revision"], "idempotency_key": "accept:" + options["dispatch_id"]}
            # Semantic acceptance inputs must remain explicit; the builder only supplies hashes.
            for key in ("window", "unresolved", "reason", "counters", "open_windows"):
                if key in options: packet["accept_request"][key] = options[key]
        return packet

    def baseline_inputs(self, options):
        from baseline_contract import build_baseline_fields
        state = self.state()
        self._validate_gate_a_content_current(state)
        document = self._plan_document()
        rows = document.get("rows", []) if isinstance(document, dict) else document
        selected = [r for r in rows if r.get("id") == options.get("plan_row")]
        if len(selected) != 1 or not selected[0].get("baseline_required"):
            raise ValueError("baseline requires exactly one approved current-task plan row")
        result = build_baseline_fields(selected[0], self._current_gate_a(state)["id"],
                                       options.get("runtime_provenance") or {})
        return dict(result, plan_content_hash=content_hash(document), plan_row=options["plan_row"])

    def deployment_inputs(self):
        from baseline_contract import deployment_readiness
        document = self._plan_document()
        rows = document.get("rows", []) if isinstance(document, dict) else document
        directory = self.store.root / "work" / "baseline-receipts"
        receipts = []
        for path in sorted_paths(directory.glob("*.json")):
            receipts.append(json.loads(path.read_text(encoding="utf-8-sig")))
        state = self.state()
        self._validate_gate_a_content_current(state)
        if not any(d.get("gate") == "A" and d.get("status") == "approved"
                   and d.get("source_revision") == state.get("source_revision")
                   for d in state.get("decisions", {}).values()):
            raise StateConflict("approved Gate A required before deployment")
        return deployment_readiness(rows, receipts, self.store.root,
                                    expected_gate_ref=self._current_gate_a(state)["id"])

    def _plan_document(self):
        path = self.store.root / "work" / "test-plan.json"
        if not path.is_file():
            raise StateConflict("managed lifecycle requires work/test-plan.json")
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateConflict("structured test plan is unreadable") from exc
        return value

    # --- what the PERSON changed at gate A, marked by code -----------------------------------
    # The retro wants a count of human overrides, and the only record of one used to be the
    # strategist's own prose — a role marking its own work as overridden, which is exactly the
    # shape of claim this factory does not accept anywhere else. So the controller derives it.
    # The baseline is the plan as the ROLE left it (captured when S3/S4 is accepted); anything
    # different by the time `revise_plan` or the gate-A decision lands is the person's doing,
    # and their own words travel with the mark. No role knows the flag exists.
    PLAN_BASELINE = ("state", "plan-baseline.json")

    def _plan_rows(self):
        """The plan's rows as they lie on disk, or None when there is no readable plan yet."""
        try:
            document = self._plan_document()
        except (StateConflict, ValueError, OSError):
            return None
        rows = document.get("rows") if isinstance(document, dict) else document
        return rows if isinstance(rows, list) else None

    def _capture_plan_baseline(self, state):
        rows = self._plan_rows()
        if rows is None:
            return
        by_row = self._row_cases(state, rows)
        atomic_json(self.store.root.joinpath(*self.PLAN_BASELINE), {
            "scope": sorted(str(case) for case in state.get("scope") or []),
            "plan_revision": state.get("plan_revision") or "",
            "rows": {str(row.get("id")): {
                "disposition": str(row.get("disposition") or ""),
                "cases": sorted(by_row.get(str(row.get("id"))) or ())}
                for row in rows if isinstance(row, dict)}})

    def _mark_plan_overrides(self, words):
        """Stamp `overridden` on every plan row the person changed. Returns the row ids.

        A row is theirs when its disposition moved (automate -> manual, say) or when a case
        it owned is no longer in the approved scope. `overridden_by` is always `gate A`: this
        is the only place in the pipeline where a person edits a plan a role wrote.
        """
        baseline_path = self.store.root.joinpath(*self.PLAN_BASELINE)
        if not baseline_path.is_file():
            return []
        baseline = json.loads(baseline_path.read_text(encoding="utf-8-sig"))
        rows = self._plan_rows()
        if rows is None or not isinstance(baseline, dict):
            return []
        state = self.state()
        by_row = self._row_cases(state, rows)
        was = baseline.get("rows") or {}
        # Only a case that WAS in the approved scope can be one the person dropped. A row
        # whose cases are not written yet falls back to `required_scenarios`, which on a real
        # plan is prose — counting those as dropped marked every untouched row.
        was_scope = {str(case) for case in baseline.get("scope") or ()}
        scope_now = {str(case) for case in state.get("scope") or []}
        # M-4: a baseline case is KEPT when the scope now holds it literally or holds every key it resolves to in
        # the index (a respelling - `TC-001` -> `a/TC-001`, `b/TC-001` - is no drop); read through the one helper
        # `dispatch` and rework refuse with. The index is built once for the whole walk, and only when a case needs it;
        # when it cannot be built `index` stays None and `_outside_approved` tries it again on every row that has candidates.
        index = self._index_or_none() if was_scope - scope_now else None
        marked = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_id = str(row.get("id"))
            before = was.get(row_id)
            if not isinstance(before, dict):
                continue
            candidates = sorted((set(before.get("cases") or ()) & was_scope) - scope_now)
            dropped = sorted(member for member, _ in self._outside_approved(
                candidates, state.get("scope") or [], index=index)[1]) if candidates else []
            moved = str(row.get("disposition") or "") != str(before.get("disposition") or "")
            if not dropped and not moved:
                continue
            row["overridden"] = True
            row["overridden_by"] = "gate A"
            row["overridden_words"] = str(words or "")
            row["overridden_change"] = ("; ".join(filter(None, [
                f"disposition {before.get('disposition') or 'none'} -> "
                f"{row.get('disposition') or 'none'}" if moved else "",
                "cases dropped: " + ", ".join(dropped) if dropped else ""])))
            marked.append(row_id)
            by_row.pop(row_id, None)
        if marked:
            path = self.store.root / "work" / "test-plan.json"
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(document, dict):
                document["rows"] = rows
            else:
                document = rows
            atomic_json(path, document)
        return marked

    def _after_commit(self, operation, request, key=None, revision=None):
        """Derived marks that follow an accepted event. Never a reason to lose the event.

        `key`, `revision`: what the request was committed under, so a `revise_plan` the CODE wrote (`code_scope_write`) is told
        from a person's: it marks no plan row and writes no `human_answer`, because it carries no word of a person - and a mark
        would overwrite the words an earlier hand-written record left on the row (CX2-17 C-4, AR-24)."""
        try:
            if operation == "accept" and request.get("stage_complete"):
                stage = (self.state().get("dispatches") or {}).get(
                    str(request.get("id")), {}).get("stage")
                if stage in ("S3", "S4"):
                    self._capture_plan_baseline(self.state())
                return
            # `revise_plan` ONLY. A gate-A decision binds `plan_content_hash`, so marking the
            # rows after it records would change the very file the receipt swears to
            # ("Gate A plan content changed after approval"). Nothing is lost: `revise_plan`
            # is the only writer of `scope`, and a decision whose scope differs from the
            # controller's is refused — so every person's change passes through here first.
            if operation != "revise_plan":
                return
            if code_scope_write(key, revision, request.get("reason"), self._ticket()):
                return
            words = request.get("reason")
            marked = self._mark_plan_overrides(words)
            if marked:
                import log_append
                log_append.write([log_append.build_record({
                    "event": "human_answer", "task": self._ticket(),
                    "notes": f"gate A override on plan row(s) {', '.join(marked)}: "
                             + str(words or "")})])
        # SystemExit too: `log_append.require_project` exits when the journal has no project
        # around it, and a committed lifecycle fact must not be lost to a derived courtesy.
        except (OSError, ValueError, KeyError, TypeError, ImportError, StateConflict,
                SystemExit) as exc:
            print(f"controller: the gate-A override marks could not be written "
                  f"({type(exc).__name__}: {exc}); the committed event stands", file=sys.stderr)

    def _record_person_pass(self, stage, dispatch_id, passed):
        """An informed pass is a fact worth keeping: the block, the words, and where.

        Not in the event payload, which is where this record went first: `event_store.commit`
        compares the payload of a repeated idempotency key against the one it stored, so a
        validator that adds a field turns the next replay of the SAME request into "idempotency
        key reused with different inputs". And not on the projected dispatch either - that copy
        is rebuilt from the events and thrown away, which is why `window_passed_by_person` read
        empty in every run that used it. Its own journal, then: the words themselves live in
        `pipeline.json.stage_overrides[]`, and this is the line that says which block they
        passed and when (FR-4)."""
        if not passed:
            return
        path = self.store.root / "state" / "passed-by-person.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                for item in passed:
                    handle.write(json.dumps({
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "+00:00",
                        "stage": str(stage or ""), "dispatch": str(dispatch_id or ""),
                        "block": str((item or {}).get("error") or "")[:400],
                        "decision": str((item or {}).get("decision") or "")[:1000],
                        "by": str((item or {}).get("by") or "human"),
                    }, ensure_ascii=False) + "\n")
        except OSError as exc:  # a record that cannot be written must not fail the pass itself
            print(f"passed-by-person: not recorded ({type(exc).__name__}: {exc})", file=sys.stderr)

    def _passed_by_person(self, stage, errors):
        """(still blocking, passed by a person's recorded word) — the factory's standing rule.

        A check stops a silent pass, never an informed one. The words live in
        `pipeline.json.stage_overrides[]`, written by `waiver.py --stage ... --block ...`;
        `stage_done.py` already reads them the same way for the S1 source check.
        """
        try:
            pipeline = json.loads((self.store.root / "pipeline.json").read_text(encoding="utf-8"))
            from waiver import split_overridden
            return split_overridden(list(errors), pipeline if isinstance(pipeline, dict) else {}, stage)
        except (OSError, ValueError, ImportError):
            return list(errors), []

    def _case_rows(self, state):
        """case id -> plan row id for the approved scope, with every row's disposition.

        The case names its plan row in its own front matter, which is the binding
        `check_delivery.py` already uses at S8; a plan whose cases are not written yet falls
        back to the row's `required_scenarios`.
        """
        document = self._plan_document()
        rows = document.get("rows") if isinstance(document, dict) else document
        if not isinstance(rows, list):
            raise StateConflict("structured test plan rows must be a list")
        dispositions = {str(row.get("id")): str(row.get("disposition") or "")
                        for row in rows if isinstance(row, dict)}
        approved = [str(case) for case in state.get("scope") or []]
        mapping, basis = {}, "case_index"
        index = self._index_or_none() or {}        # an index that cannot be built, or an empty one: no key is read from it
        for case in approved:
            # Two areas may both hold TC-001 (FB-2428-1): case_index keys those
            # `<area>/TC-NNN`, and a bare scope entry names both.
            for key in (getattr(index, "matching", lambda c: [])(case) or [case]):
                row = str((index.get(key) or {}).get("plan_row") or "")
                if row in dispositions:
                    mapping[key] = row
        if not mapping and approved:
            basis = "required_scenarios"
            for row in rows:
                for case in row.get("required_scenarios") or []:
                    if str(case) in approved and str(row.get("id")) in dispositions:
                        mapping[str(case)] = str(row.get("id"))
        return mapping, dispositions, basis

    # --- the approved scope is PINNED CASES, compared by KEYS (CX1-11) ---------------------------------
    # `state["scope"]` is written by `revise_plan` (the controller's, and the driver's after S4) in the spelling
    # the case index keys (`TC-001`, `<area>/TC-003` for a number two areas hold). Every reader asks the same two
    # questions through the same two helpers: "is this member a pinned case" (`_scope_membership`) and "is this
    # member approved" (`_outside_approved`), and the error direction is REFUSAL (I3): a member that resolves to
    # nothing, or to a key nobody approved, is refused; the approved side is never widened at a read.
    def _ticket(self):
        """THE reader of the story's name (CX2-17, AR-13): the folder name as the caller WROTE it, which is what a recording
        command's `--task` takes and what `brief_pack.answers_of` compares exactly - a record written under another spelling
        is a record its reader never finds (FR-8, AR-24). Resolved only where the written name names no folder: a root given
        as `.` or `..` has an empty or a dotted `.name`, and a door that names no story is no door (FR-2, t-964 M-1).
        Whether a worker's receipt is THIS story's is another question, `_story_names`."""
        return _folder_name(self.store.root)

    def _story_names(self, project):
        """Every spelling of this story's name a receipt of the host may carry, `_ticket()` first - for the VETOES only.

        A receipt is written with the `--task` of its writer (`story_step`, `host_dispatch`), and the readers compare it
        exactly, so a receipt under `TP1-1` is no receipt of the story `tp1-1` on a case-blind disk, nor of a
        folder reached through a link. Here every receipt whose folder (`artifact_root(project) / task_id`) IS this
        story's folder (`os.path.samefile`) adds its own spelling. ERROR DIRECTION: a name added by mistake only holds a
        veto longer; a name missed would lift the veto of a live worker - so a receipt that cannot be judged adds nothing
        but never removes `_ticket()`. A task id that is not one path component is no name (the reader of
        `worker_lifecycle.binding_is_active` keeps such a receipt active instead). A story outside the artifact root keeps
        the one name, as before."""
        names = [self._ticket()]
        try:
            from hooklib import artifact_root, is_one_component
            from worker_lifecycle import bindings
            base = artifact_root(None, root=project)
            for binding in bindings(project):
                task = binding.get("task_id") if isinstance(binding, dict) else None
                if not is_one_component(task) or task in names:
                    continue
                try:
                    if os.path.samefile(base / task, self.store.root):
                        names.append(task)
                except (OSError, ValueError):       # a receipt that cannot be judged (a NUL byte is a ValueError) adds nothing
                    continue                        # and never stops the walk: the receipts after it are still read (F-2)
        except Exception:       # a project the receipts cannot be read in keeps the names found so far: `_ticket()` is always there
            pass
        return names

    def _liveness(self, project, record, now=None, names=None):
        """`dispatch_liveness.state` for every spelling of this story's name, ONE verdict by seniority:
        ALIVE > UNKNOWN > RETURNED > ABANDONED > NEVER_STARTED. A receipt of any spelling of the folder is this story's
        worker, so the answer that keeps it is the one that stands, and a dispatch is closed by inference only when no name
        holds it (the invariant of `dispatch_liveness._state`: a non-terminal receipt of THIS dispatch is never closed by
        inference). A state outside the list ranks as UNKNOWN, the side that closes nothing. With one name the call is the
        one `dispatch_liveness.state` always got."""
        import dispatch_liveness
        order = (dispatch_liveness.ALIVE, dispatch_liveness.UNKNOWN, dispatch_liveness.RETURNED,
                 dispatch_liveness.ABANDONED, dispatch_liveness.NEVER_STARTED)

        def rank(verdict):
            return order.index(verdict.get("state")) if verdict.get("state") in order else 1
        best = None
        for name in names if names is not None else self._story_names(project):
            verdict = (dispatch_liveness.state(project, name, record) if now is None
                       else dispatch_liveness.state(project, name, record, now))
            if best is None or rank(verdict) < rank(best):
                best = verdict
            if rank(best) == 0:
                break
        return best

    def _verdicts_of(self, state, ids):
        """dispatch id -> `_liveness` verdict, for each of `ids` that names a row of `state`: THE one reading of "is this running row
        alive" for every site that blocks or closes on a `running` row (AR-13; `_close_verdicts` and `_holding` are views of it). A reader
        that raises, or no project to read in, gives an `unknown` verdict: it holds (FR-59, AR-28). Reads only the rows it is asked for."""
        verdicts = {}
        dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
        rows = {_dispatch_ident(row, key): row for key, row in dispatches.items() if isinstance(row, dict)}
        wanted = [ident for ident in ids if ident in rows]
        if not wanted:
            return verdicts
        project = None
        try:
            project = self._project_root()
            starts = self._dispatch_starts() if project is not None else {}
        except Exception:
            project, starts = None, {}
        for ident in wanted:
            try:
                if project is None:
                    raise LookupError("no project to read the session in")
                verdicts[ident] = self._running_verdict(project, dict(rows[ident], id=ident), starts)
            except Exception as error:
                verdicts[ident] = {"state": "unknown", "evidence": [f"the liveness reader failed: {error}"]}
        return verdicts

    def _close_verdicts(self, state, stage):
        """The verdicts of every row `code_close_facts` reads as running (any stage's, the closing stage's own too): `_verdicts_of`."""
        return self._verdicts_of(state, code_close_facts(state, stage)["running"])

    def _running_verdict(self, project, dispatch, starts, now=None):
        """The `_liveness` verdict of ONE row read as running: the one call `liveness_fixes` and `_close_verdicts` share (its start
        time comes from `starts`, the dispatch ids' launch times). Raises what the reader raises; the callers say what that means."""
        return self._liveness(project, dict(dispatch, started_at=starts.get(str(dispatch.get("id")))), now)

    def _holding(self, state, ids=None):
        """What holds a plan, a gate or a record change, and is it alive: THE one reading for every "checkpoint active work" refusal
        (TR4-7; AR-13, AR-25), a view of `_verdicts_of` (the reader TR1-9 and the close use).

        Returns `{"holders": [ids], "dead": [ids], "verdicts": {id: verdict}}` over the rows whose status is `running` (and, with `ids`,
        only those of them: liveness is read for no other row), in the state's order (none is picked by position: the refusal names
        every holder). A row is `dead` only when the liveness verdict says the session is over (`code_close_passed_label`); `alive`,
        `unknown`, a reader that raises, no project to read in and a verdict that is no dict all keep the row a HOLDER (FR-59, AR-28):
        a live dispatch is never read as dead. Pure: it reads, it writes nothing (FR-45); `apply` records a dead holder before it validates."""
        dispatches = state.get("dispatches") if isinstance(state.get("dispatches"), dict) else {}
        running = [_dispatch_ident(row, key) for key, row in dispatches.items()
                   if isinstance(row, dict) and row.get("status") == "running"]
        if ids is not None:
            running = [ident for ident in running if ident in ids]
        verdicts = self._verdicts_of(state, running)
        dead = [ident for ident in running if code_close_passed_label(verdicts.get(ident))]
        return {"holders": [ident for ident in running if ident not in dead], "dead": dead, "verdicts": verdicts}

    def _holders_tail(self, state, ids=None):
        """The sentence tail naming the live holders (`ids`: only those of them, else all), or `""` when none holds (dead ones do
        not). The caller raises its own pinned sentence plus this tail."""
        held = self._holding(state, ids)
        holders = held["holders"]
        return _code_close_holders_words(state, holders, held["verdicts"], checkpoint=True) if holders else ""

    def _pinned_links(self):
        """The story's pinned CaseVersions: the links that carry a case id AND a version (one filter for the
        Gate A pin check, the design reviews and a rework's `case_version_links`)."""
        from contract import story_case_links
        return [link for link in story_case_links(self.store.root) if link.get("case_id") and link.get("version")]

    @staticmethod
    def _listed(items, sep=", "):
        """At most `SCOPE_SHOWN` of `items` (each once), joined by `sep`, and `(N in all)` when there are more (E9, FR-41):
        the one cut of every scope text, `detector_verdict.named` with the count as its tail. `sep` is `"; "` for items that
        hold commas themselves."""
        from detector_verdict import named
        return named(items, SCOPE_SHOWN, sep=sep, tail=" ({n} in all)")

    def _index_or_none(self, strict=False):
        """The story's `contract.case_index`, or None when it cannot be built (a collision, a mismatch) - the one `try` of
        that reading: the three errors are `(OSError, ValueError, TypeError)`. `strict` raises the error instead (the writer
        names it, `_scope_membership`)."""
        from contract import case_index
        try:
            return case_index(self.store.root)
        except (OSError, ValueError, TypeError):
            if strict:
                raise
            return None

    def _index_door(self):
        """The way out of a case index that cannot be built: fix the files the message names, pin again (m-c)."""
        return (f"; fix the case files the message names, then run `case_versions.py --task-root {self.store.root} "
                "--all` and pin the cases again")

    def _scope_membership(self, members, strict=False):
        """`(pinned case ids, [(member, keys, why)])`: the one answer to "is this scope member a pinned case?".

        The Gate A pin check, `revise_plan` and `_scope_door` all read it. Pinned = `_pinned_links()` (M-2); a member is
        resolved by `contract.scope_member_resolution` over the index entries whose link is pinned; no pinned link
        at all: every member is unpinned. When the index cannot be built, `strict` re-raises its error (the writer
        names it), otherwise the pins themselves answer literally (a bare id or a link key)."""
        from contract import case_link_key, scope_member_resolution
        links = self._pinned_links()
        ids = sorted({str(link["case_id"]) for link in links})
        members = list(members or [])
        if not ids:
            return ids, [(member, [], "no case is pinned") for member in members]
        # A pin the index does not read as a case id (an id form the project does not list) is still the pin it is:
        # a member that IS a pinned id or a link's key is pinned, as it was before the index was asked (I5).
        known = set(ids) | {case_link_key(link) for link in links}
        index = self._index_or_none(strict)
        if index is None:
            return ids, [(member, [member], "") if isinstance(member, str) and member in known
                         else (member, [], "not pinned") for member in members]
        return ids, [(member, [member], "") if why and isinstance(member, str) and member in known
                     else (member, keys, why)
                     for member, keys, why in scope_member_resolution(members, index, pinned_only=True)]

    def _scope_door(self, scope, wanted=None):
        """The door out of an approved scope that holds no pinned case id, or "" when none applies.

        TP2-2406: `revise_plan` is the one writer of the scope and the refusals never named it. Offered only
        where it helps: the story has pins, NO member of the stored scope is one of them, and EVERY case the caller
        asked for is pinned (a case nobody pinned is not reached by recording the scope, I2)."""
        ids, stored = self._scope_membership(scope)
        _, asked = self._scope_membership(wanted)
        if not ids or any(not why for _, _, why in stored) or any(why for _, _, why in asked):
            return ""
        return ("; the stored scope holds no pinned case id - `case_versions.py --all` records the pinned ones unless the scope "
                "was set by hand; otherwise record the pinned ones with "
                f"`--operation revise_plan` (scope = {self._listed(ids)}; with plan_revision and reason), then repeat this")

    def _manual_keys(self, ids, state):
        """The cases of a manual runner block in the keys the approved scope holds (CX2-17 C2, AR-19): `canonical + refused`
        of `_outside_approved` against `state["scope"]`, a member the map cannot resolve left as written. THE one reading of the
        block's spelling: `apply`, `prepare` and `story_step.py start` call it, so a bare `TC-3` that two areas hold is counted,
        checked against the half and registered as every one of its keys on every road. Not a list, or empty: returned as
        given (the caller's own check speaks, E31)."""
        if not isinstance(ids, list) or not ids:
            return ids
        canonical, refused = self._outside_approved(ids, state.get("scope") or [])
        return canonical + [member for member, _ in refused]

    def _outside_approved(self, members, approved, index=None):
        """`(canonical, refused)`: ONE reading of "is this scope member approved", for rework and dispatch alike.

        `_outside_approved(members, approved, index)` returns `(canonical, refused)`. A member equal to an approved
        member (`_within([m], approved)`) stays as is. A member whose keys `scope_member_resolution` finds, with every key
        approved, becomes those keys. Any other member stays AS WRITTEN and is refused: `refused` is `[(member,
        why)]`, `canonical` the members that passed. `apply` writes `canonical + refused` into its copy. `validate`
        and `build_rework_request` call the same helper. The index is built only when some member is not literal.
        If the index fails, members stay as written (§L F-10 (a)).

        Literal first (I5, `main`'s rule): a legacy store holding a bare `TC-003` or the story's key still answers
        to itself; then the keys (I1: no refusal by a spelling `_split_case_key` reads); a bare id of a number two
        areas hold is approved only when EVERY one of its keys is (I2, C3-12 - never the intersection)."""
        allowed = set()
        for item in approved or []:
            try:
                allowed.add(item)
            except TypeError:
                continue

        def held(member):
            try:
                return member in allowed
            except TypeError:
                return False
        members = list(members)
        todo = [member for member in members if not held(member)]
        answers = iter(())
        if todo:
            index = index if index is not None else self._index_or_none()
            if index is not None:
                from contract import scope_member_resolution
                answers = iter(scope_member_resolution(todo, index))
        canonical, refused, changed = [], [], False
        for member in members:
            if held(member):
                canonical.append(member)
                continue
            found = next(answers, None)
            if found is None:
                refused.append((member, "not an approved member"))
            elif found[2] or not all(key in allowed for key in found[1]):
                refused.append((member, found[2] or "not approved: " + ", ".join(k for k in found[1] if k not in allowed)))
            else:
                canonical.extend(found[1])
                changed = True
        return (list(dict.fromkeys(canonical)) if changed else canonical), refused

    def _unapproved_text(self, refused, approved):
        """What follows "scope expansion requires plan/gate revision" (R4): the members, the door, and - when the
        approved scope holds a spelling the index no longer keys (R4-legacy, M-5) - the spelling to record."""
        text = (": " + self._listed(member for member, _ in refused) + "; the door is controller.py --operation "
                "revise_plan with the new scope, then a new gate A decision")
        index = self._index_or_none()
        if index is None:
            return text
        from contract import scope_member_resolution
        stored = [member for member in approved or [] if isinstance(member, str)]
        notes = [f"{member}, which the case index keys as {', '.join(keys)}"
                 for member, keys, why in scope_member_resolution(stored, index) if not why and keys != [member]]
        if not notes:
            return text
        return (text + "; the approved scope holds " + self._listed(notes, sep="; ")
                + " - record it in that spelling with revise_plan (every stored spelling the index keys differently is listed)")

    @staticmethod
    def _scope_not_recorded(p, state):
        """True for a dispatch at S4 in a story that has no gate A decision of ANY status: the scope is the cases S4 pins and
        nothing approved depends on it yet. With a decision (even a stale one) the old text, with its door, stays true (HF8-6)."""
        return p.get("stage") == "S4" and not any(
            isinstance(d, dict) and d.get("gate") == "A" for d in (state.get("decisions") or {}).values())

    def _own_key_problem(self, members):
        """`(ValueError, R2)` when a scope member is the story's own key, else None (initialize, and revise_plan
        at any state of the pins, F-9). Only a NEW write is checked: a store that holds the key is read as before."""
        story = self._ticket().strip().casefold()
        own = [str(member) for member in members if story and str(member).strip().casefold() == story]
        if not own:
            return None
        return (ValueError, f"scope holds case ids, and {', '.join(own)} is the story's own key, not a case; at S0 "
                            "the scope is [] - the pinned case ids are recorded at S4 by `case_versions.py --all`")

    def _revise_scope_problems(self, scope):
        """The problems of a `revise_plan` scope, collected for `_raise_all` (K1): the story's own key (R2), the
        case index that cannot be built (M-1), and the members no pin names (R1, ONE problem with all of them)."""
        problems = []
        own = self._own_key_problem(scope)
        if own:
            problems.append(own)
        story = self._ticket().strip().casefold()
        rest = [member for member in scope if not (story and str(member).strip().casefold() == story)]
        try:
            ids, resolution = self._scope_membership(rest, strict=True)
        except (OSError, ValueError, TypeError) as exc:
            problems.append((StateConflict, "the case index cannot be built: " + str(exc) + self._index_door()))
            return problems
        refused = [(member, why) for member, _, why in resolution if why]
        if ids and refused:
            from contract import case_link_issues
            areas = [f"{member}: {why}" for member, why in refused if why.startswith("pinned in:")]
            issues = case_link_issues(self.store.root)
            problems.append((ValueError, "scope member(s) that are not pinned case ids: "
                             + self._listed(member for member, _ in refused)
                             + "; the scope holds pinned case ids - the story's own key, another story's key and a plan "
                               "row id are not cases, and an area must be one the case is pinned in"
                             + (" (" + self._listed(areas, sep="; ") + ")" if areas else "")
                             + "; the pinned ids are " + self._listed(ids)
                             + f"; a new case is pinned (`case_versions.py --task-root {self.store.root} --all`) before "
                               "the scope names it"
                             + ("; broken pins: " + self._listed(issues, sep="; ") if issues else "")))
        return problems

    def _normalise_revise_scope(self, request):
        """The scope `revise_plan` WRITES: the keys of the members that resolve (`sorted(set)`, a bare number two areas
        hold is every one of its keys, F-1), then the members that do not, as written, for `validate` to refuse
        (never a `set()` over them, E4). On `request`, the caller's own copy (FR-45). Returns {member: keys} for the
        members spelt otherwise than the index keys them (the receipt lists them, m-13). Nothing happens without
        pins, and an index that cannot be built is `validate`'s refusal."""
        scope = request.get("scope")
        if not isinstance(scope, list):
            return {}
        try:
            ids, resolution = self._scope_membership(scope, strict=True)
        except (OSError, ValueError, TypeError):
            return {}
        if not ids:
            return {}
        request["scope"] = self._resolved_keys(resolution) + [member for member, _, why in resolution if why]
        return {str(member): found for member, found, why in resolution if not why and found != [member]}

    @staticmethod
    def _resolved_keys(resolution):
        """The keys a `scope_member_resolution` answer resolved, each once, sorted: the ONE expression of "the keys of these
        members" (`_normalise_revise_scope` writes them, `case_versions._scope_plan` keys its request by them). A refused member
        resolves to no key."""
        return sorted({key for _, found, why in resolution if not why for key in found})

    def _revise_key_fields(self, exc, operation):
        """The names of the fields that differ, when `exc` is the store's "idempotency key reused" for a `revise_plan` whose
        difference is in the plan's own fields (A6: a hand-written key reused for another request); None otherwise. By TYPE and
        FIELDS (FR-12), never by the store's words: any other difference, an empty list of fields and any other store refusal
        pass on untouched. `apply` raises the refusal itself, so the blocks census sees it (F-1)."""
        if (operation != "revise_plan" or not isinstance(exc, IdempotencyKeyReused) or not exc.fields
                or not set(exc.fields) <= {"scope", "reason", "plan_revision", "required_quality_checks"}):
            return None
        return exc.fields

    def _replayed_with_other_scope(self, exc, operation, request, current):
        """The scope a dispatch was COMMITTED with, when `exc` is the store's "idempotency key reused" for a dispatch
        whose scope now differs from it (N-2); None when `exc` is something else. The invariant: a replay of the
        same words is never refused here, and another store refusal is passed on untouched. `apply` raises the
        refusal itself, inside its `raise`, so the blocks census sees it (F-1)."""
        existing = (current.get("dispatches") or {}).get(request.get("id")) if operation == "dispatch" else None
        # By TYPE and FIELDS (FR-12), not by the store's words. N-2 is the answer ONLY when the scope (and the
        # known_paths a scope's respelling drags along) are the whole difference: any other field that differs
        # (brief_sha, input_hash, rework_of ...) passes the store's refusal on UNTOUCHED, with every field named,
        # because `revise_plan` is not the door for those (F-3, FR-2).
        if (not isinstance(existing, dict) or not isinstance(exc, IdempotencyKeyReused)
                or not exc.fields or not set(exc.fields) <= {"scope", "known_paths", "manual_case_ids"}
                or existing.get("scope") == request.get("scope")):
            return None
        return existing.get("scope") or []

    def _other_scope_text(self, committed, request, respelled):
        """The rest of the N-2 refusal after its head: TWO causes, two sentences (F-2). The request was rewritten into
        other keys than it was sent in: the case index moved since the commit. Not rewritten: the caller sent another
        scope under the same id, and the index moved nothing."""
        sent = self._listed(request.get("scope") or [])
        before = f" was committed with scope [{self._listed(committed)}]"
        door = "`controller.py --operation revise_plan` with the new scope, then a new gate A decision"
        if respelled:
            return (before + f"; the case index moved since the dispatch was committed (this request reads as [{sent}] "
                    "now). A replay carries the scope it was committed with; a case the approved scope does not name "
                    "is " + door)
        return (before + f"; a different scope under the same id is not a replay (this request names [{sent}]): "
                + door)

    def _row_cases(self, state, rows):
        """plan row id -> the approved cases on it. ONE mapping for the whole controller.

        Gate A used to read `required_scenarios` while `stage-scope` read the case front
        matter, and on TP1-15045 the plan's `required_scenarios` were sentences of
        prose: the design-review check then looked for a case named "button opens visual
        popup" and refused a decision the person had already made. A row with no case of
        its own still falls back to `required_scenarios`, so a plan written before the
        cases exist is not refused for a file nobody has authored yet.
        """
        try:
            mapping, _, _ = self._case_rows(state)
        except (StateConflict, ValueError):
            mapping = {}
        by_row = {}
        for case, row in mapping.items():
            by_row.setdefault(row, set()).add(str(case))
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id"))
            if not by_row.get(key):
                by_row[key] = {str(case) for case in row.get("required_scenarios") or []}
        return by_row

    def _rollcall_reviewed(self):
        """Case ids the case critic's own roll-call marks as reviewed, or an empty set.

        The roll-call is the reviewer's record of what it actually read. It is what makes
        an S4 dispatch recorded with an empty `scope` (every dispatch before 0.7.5) still
        evidence that a particular case was reviewed.
        """
        reviewed = set()
        try:
            from critic_rollcall import derive, findings_files, parse_rollcall
            for path in findings_files(self.store.root):
                rows = parse_rollcall(path.read_text(encoding="utf-8", errors="replace"))
                facts = derive(rows)
                for row in rows:
                    if row.get("reviewed") and row.get("case"):
                        reviewed.add(str(row["case"]))
                reviewed.difference_update(str(case) for case in facts.get("unreviewed") or [])
        except (ImportError, OSError, ValueError, TypeError, KeyError):
            return set()
        return reviewed

    @staticmethod
    def _legacy_designer_evidence(dispatch, cases):
        """Does the opener's own evidence list every one of these cases? Exact id only.

        A case id must equal a whole path part or the file stem of an `evidence_refs[].path`
        (`work/test-cases/cases/<id>/cv_x.md`): never a substring (`TC_01` is not `TC_011`).
        Anything that is not a list of dicts with a string path is skipped, never raised on.
        """
        refs = dispatch.get("evidence_refs")
        if not isinstance(refs, list) or not cases:
            return False
        names = set()
        for ref in refs:
            path = ref.get("path") if isinstance(ref, dict) else None
            if not isinstance(path, str) or not path:
                continue
            parts = [part for part in path.replace("\\", "/").split("/") if part]
            names.update(parts)
            if parts:
                names.add(Path(parts[-1]).stem)
        return all(case in names for case in cases)

    @staticmethod
    def _cover_basis(dispatch, cases, reviewed, row=None):
        """HOW this S4 dispatch covers these cases, or "" when it does not.

        `scope` | `plan_rows` | `legacy_evidence` | `rollcall`, tried in that order. ONE rule
        body for the rehearsal, the recording and the author/critic pick, so they cannot disagree.

        The first two clauses were the whole rule until B-224. The S4 designer opens before any
        case id exists, so its scope is empty and gate A could not name it the author of anything
        (cmp1: TS-6/7/9/11 with author ""). The two new clauses reach ONLY the designer role: a
        critic is credited by its scope or its roll-call, never by rows or by evidence. The error
        direction is "does not cover" - a refusal with doors - never a credit by default.
        """
        scope = {str(case) for case in dispatch.get("scope") or []}
        if cases.issubset(scope):
            return "scope"
        if dispatch.get("role") == "qa-case-designer":
            plan_rows = dispatch.get("plan_rows")
            # A list and an exact element: a string is never iterated (`"TS-10"` holds `TS-1`),
            # and an empty or absent row never matches.
            if isinstance(plan_rows, list):
                if isinstance(row, str) and row and any(isinstance(item, str) and item == row
                                                        for item in plan_rows):
                    return "plan_rows"
            # A receipt made before the field existed has no KEY at all. Its own evidence is then
            # the only record of what it designed; a PRESENT list (even `[]`) is the new receipt
            # speaking, and the evidence is not consulted (builder-rules 9: no story in flight is
            # refused for lacking the field - and no case is credited without designer evidence).
            elif ("plan_rows" not in dispatch and dispatch.get("stage") == "S4"
                    and dispatch.get("status") == "accepted" and not scope
                    and not dispatch.get("rework_of")
                    and Controller._legacy_designer_evidence(dispatch, cases)):
                return "legacy_evidence"
        # A designer receipt that carries the `plan_rows` KEY has said what it was sent to design
        # (`[]` = nothing), so a critic's roll-call must not credit it for another row: the
        # fallback is for critics and for receipts made before the field (E-2, section 5 inv. 8).
        speaks_in_rows = dispatch.get("role") == "qa-case-designer" and "plan_rows" in dispatch
        if not scope and bool(cases) and cases.issubset(reviewed) and not speaks_in_rows:
            return "rollcall"
        return ""

    @staticmethod
    def _covers(dispatch, cases, reviewed, row=None):
        """Did this S4 dispatch cover these cases? An empty historical scope is not a no."""
        return bool(Controller._cover_basis(dispatch, cases, reviewed, row))

    def accept_order(self):
        """dispatch id -> the position of its `accept` event in `state/events.jsonl`: the order work was accepted in
        (dispatch numbers and registration order say nothing about it). THE one reader of that order (AR-13):
        the design-review binding below and the driver's `review_precondition` both read it here. {} when the
        log cannot be read - an unknown order never refuses and never passes anything (E-D3)."""
        order = {}
        try:
            events = self.store.read()      # the store's own verified reader (hash chain checked): a broken chain is "unknown", never a partial order
        except (StateConflict, OSError):
            return order
        for row in events:
            payload = row.get("payload") if isinstance(row, dict) else None
            if isinstance(payload, dict) and row.get("type") == "accept" and isinstance(payload.get("id"), str):
                order[payload["id"]] = row.get("sequence")
        return order

    @staticmethod
    def review_is_stale(review, order):
        """True when this review's author was accepted AFTER its reviewer: the critic has not seen the cases as the
        designer left them. False for a review with no author or no reviewer, or when either has no accept event
        in `order` (E-D1, E-D2, E-D3: the rule only adds a refusal where both positions are known)."""
        if not isinstance(review, dict):
            return False
        author, critic = str(review.get("author_dispatch_id") or ""), str(review.get("reviewer_dispatch_id") or "")
        return bool(author and critic and author in order and critic in order and order[author] > order[critic])

    def _design_review_problems(self, p, state, rows, pinned):
        """Every critical plan row whose independent design review does not hold up.

        One message per row, naming the row and what is missing: the single sentence
        "critical plan row needs independent accepted design review" sent a person to
        rebuild a plan that was never the problem.
        """
        reviews = {str(item.get("plan_row")): item for item in p.get("design_reviews", [])
                   if isinstance(item, dict)}
        order = self.accept_order()
        by_row = self._row_cases(state, rows)
        reviewed = self._rollcall_reviewed()
        problems = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("design_review_required"):
                continue
            # A row nobody designs a case for has nothing to design-review: a `skip` or
            # `manual-human` row carries its reason in the plan, not in a case file. On
            # TP1-13797 four such rows (a dev-owned regression, two rows blocked on an
            # owner question) refused a gate the person had approved, and no waiver reached
            # this check (experiment/qa-factory-judge, FB-7).
            # `unverifiable` belongs in that list for the same reason, and it was missing:
            # TP1-13797, 26.09 — TS-19 carried the register's own contradiction (AC7 has no
            # observable in this story's code), so the strategist wrote `required_scenarios:
            # ["pending Gate-A scope decision"]`, and this check went looking for a pinned case
            # version of that sentence. The gate the person had just approved would not record,
            # and the driver re-asked gate A in a loop.
            if str(row.get("disposition") or "") in {"skip", "manual-human", "unverifiable"}:
                continue
            row_id = str(row.get("id"))
            review = reviews.get(row_id)
            if not review:
                problems.append(f"plan row {row_id} requires an independent design review and the "
                                f"decision carries none; build the request with "
                                f"`{person_words.door('--operation gate-decision --gate A')}`")
                continue
            author = state["dispatches"].get(str(review.get("author_dispatch_id")), {})
            critic = state["dispatches"].get(str(review.get("reviewer_dispatch_id")), {})
            cases = set(by_row.get(row_id) or ())
            relevant_versions = {pinned[case] for case in cases if case in pinned}
            why = []
            if review.get("verdict") != "accepted":
                # A word read per row says where it came from: the sentence branches on `verdict_basis` (never on the
                # prose of `verdict_source`), and only a word the critic wrote is called the critic's. The older
                # sentence stays for the rows the older rule decided, where the critic's declared word IS the source.
                basis, word = review.get("verdict_basis"), review.get("verdict")
                waiver = person_words.door(f"waiver.py --task {self._ticket()} --stage S4 --block \"design review\"")
                said = {"column": f"the case critic's verdict for this row is {word!r}",
                        "round_word": f"no per-case verdict for this row; the case critic's round says {word!r}",
                        "receipt_mismatch": "gate A cannot read the case critic's review of this row: its findings "
                                            "file was edited after that review was accepted, so the receipt no "
                                            "longer matches it - the critic's word is not in question, the bytes "
                                            "it was given for are gone",
                        "round_word_rule": "the case critic's Verdict line contradicts its cells; the critic rewrites the "
                                           "line - the cases were not changed",
                        }.get(basis, "gate A cannot read an approving word of the case critic for this row")
                why.append(f"{said} ({review.get('verdict_source')}) — run the critic round again (`--operation "
                           f"rework --stage S4 --role qa-case-critic --brief`) or, when the person approves the row as it "
                           f"stands, record their words and reason with `{waiver}`" if basis else
                           f"the case critic's own declared verdict is {word!r}, not an approving one — send the "
                           "round back (`--operation rework --stage S4 --role qa-case-critic --brief`) or record the "
                           f"person's word with `{waiver}`")
            if review.get("plan_revision") != p.get("input_revision"):
                why.append(f"plan_revision {review.get('plan_revision')!r} is not the reviewed "
                           f"input_revision {p.get('input_revision')!r}")
            if not cases:
                why.append("no case names this plan row in its front matter and the row lists no "
                           "required_scenarios, so nothing binds the review to a pinned case")
            elif not relevant_versions:
                why.append(f"none of its cases ({', '.join(sorted(cases))}) has a pinned version")
            elif set(review.get("case_versions") or []) != relevant_versions:
                why.append(f"case_versions {sorted(review.get('case_versions') or [])} are not the "
                           f"pinned versions {sorted(relevant_versions)}")
            if review.get("author_dispatch_id") == review.get("reviewer_dispatch_id"):
                why.append("author and reviewer are the same dispatch; the review is not independent")
            elif self.review_is_stale(review, order):
                # The pins above cannot tell (they are read at build time, from the same pins), so the receipt is bound
                # by ORDER: a designer accepted after the critic changed what the critic saw (RN1-20).
                why.append(f"the case designer's dispatch {review.get('author_dispatch_id')} was accepted after the "
                           f"case critic's {review.get('reviewer_dispatch_id')}: the critic has not reviewed the "
                           "cases as they stand")
            no_author = not str(review.get("author_dispatch_id") or "")
            if no_author:
                # No designer dispatch covers the row at all: one sentence with the two doors,
                # instead of "author '' is not ..." and "does not cover" (B-224, cmp1 TS-6).
                named = ", ".join(sorted(cases)) if cases else f"plan row {row_id}"
                why.append(
                    f"no accepted S4 qa-case-designer dispatch is recorded as having designed {named}: "
                    f"its receipt names neither the cases nor their plan row, and its evidence does "
                    f"not list them. Send the designer back over them with `--operation rework "
                    f"--stage S4 --role qa-case-designer --cases {','.join(sorted(cases)) or '<ids>'} "
                    f"--reason \"<why>\" --brief` and then a case-critic round, or record the person's word "
                    f"with `"
                    + person_words.door(f"waiver.py --task {self._ticket()} --stage S4 "
                                        "--block \"design review\"") + "`")
            elif author.get("role") != "qa-case-designer" or author.get("stage") != "S4":
                why.append(f"author {review.get('author_dispatch_id')!r} is not an S4 qa-case-designer")
            if critic.get("role") != "qa-case-critic" or critic.get("stage") != "S4":
                why.append(f"reviewer {review.get('reviewer_dispatch_id')!r} is not an S4 qa-case-critic")
            # The author half of the next two checks is skipped when no author exists: the one
            # sentence above already says so, and a second one would contradict it (FR-10).
            if (not no_author and author.get("status") != "accepted") or critic.get("status") != "accepted":
                why.append("both the designer and the critic dispatch must be accepted")
            if not review.get("input_hash"):
                why.append("the review names no input_hash")
            elif (not no_author and author.get("input_hash") != review["input_hash"]) \
                    or critic.get("input_hash") != review["input_hash"]:
                why.append("designer and critic did not work from the review's input_hash")
            if cases and not no_author and not self._covers(author, cases, reviewed, row_id):
                why.append(f"the designer dispatch does not cover {', '.join(sorted(cases))}")
            if cases and not self._covers(critic, cases, reviewed, row_id):
                why.append(f"the critic dispatch does not cover {', '.join(sorted(cases))} and its "
                           "roll-call does not name them reviewed")
            if why:
                problems.append(f"plan row {row_id}: independent accepted design review bound to this "
                                f"revision is missing — " + "; ".join(why))
        # The person's recorded word passes a design-review problem the same way it passes
        # every other stage block: `waiver.py --stage S4 --block "design review"` (the hint
        # the verdict message already gives) — a check stops a silent pass, never an informed one.
        blocking, _ = self._passed_by_person("S4", problems)
        return blocking

    def _decision_problems(self, p, state):
        """[(exception class, message)] for a `decision` request — the whole rule body.

        `decision` refuses with all of these (`_raise_all`, the class of the first);
        `check_decision` returns the same list and writes nothing. Before 0.7.6 the rules lived inline in `validate`, so the only way
        to find out whether a decision would record was to try to record it: on
        TP1-15045 the person's approved gate was refused twice after the fact.
        """
        problems = []
        try:
            validate_record("Decision", p)
        except (ValueError, KeyError) as exc:
            return [(ValueError, "decision record invalid: " + str(exc))]
        if not all(p.get(k) for k in ("id", "action", "authorization_source", "source_revision")):
            problems.append((ValueError, "decision must name action, revision and authorization"))
        if p.get("status") not in ("approved", "declined", "deferred"):
            problems.append((ValueError, "status must be one of: approved, declined, deferred"))
        if p.get("source_revision") != state["source_revision"]:
            problems.append((StateConflict, "decision references stale source revision "
                             f"({p.get('source_revision')!r}); current is {state['source_revision']!r}"))
        if not p.get("gate"):
            return problems
        if not isinstance(p.get("scope"), list) or set(p["scope"]) != set(state["scope"]):
            problems.append((StateConflict, "gate decision must bind the exact approved scope "
                             f"({len(state.get('scope') or [])} case(s) in the controller)"))
        expected_input = state.get("plan_revision") or state.get("source_revision")
        if p.get("input_revision") != expected_input:
            problems.append((StateConflict, "gate decision must bind the current reviewed input "
                             f"revision {expected_input!r}, not {p.get('input_revision')!r}"))
        prior = "S4" if p["gate"] == "A" else "S8" if p["gate"] == "B" else None
        if not prior or state["stages"].get(prior, {}).get("status") != "completed":
            # Naming the stage is not enough: on TP2-2553 the stage's own roles had
            # all been accepted and only the flag was missing, so "stage not completed" sent
            # the orchestrator to a duplicate dispatch over unchanged evidence. The repair of
            # the factory's own bookkeeping is one command, and it is named here.
            status = (state["stages"].get(prior) or {}).get("status") if prior else ""
            problems.append((StateConflict, "gate before prerequisite completion: gate must be A "
                             f"(after S4) or B (after S8), got {p['gate']!r}"
                             + (f"; {prior} is {status or 'not started'}. If its last role was "
                                "already accepted, this is the factory's own bookkeeping: "
                                f"`controller.py --task-root {self.store.root} --operation "
                                "recover` closes it from its own receipts, with no new dispatch."
                                if prior else "")))
        if p["gate"] == "B":
            drafts = p.get("selected_drafts")
            if not isinstance(drafts, list) or any(not isinstance(ref, str) or not ref for ref in drafts):
                problems.append((ValueError, "Gate B receipt requires selected_drafts array of original "
                                 "approved draft refs (may be empty)"))
            orders = p.get("orders")
            if orders is not None and (not isinstance(orders, dict) or any(
                    not isinstance(name, str) or value not in (ORDER_DUE, ORDER_NOT_ORDERED) for name, value in orders.items())):
                problems.append((ValueError, "Gate B `orders` is an object of order -> due | not_ordered "
                                 "(--operation gate-decision --gate B --bugs ordered|not_ordered --mr open|do_not_open|not_offered "
                                 "writes it); omit it for a decision that orders nothing"))
            owned = [key for key in PROJECTION_OWNED_B_KEYS if key in p]
            if owned:
                problems.append((ValueError, f"Gate B decision request carries {', '.join(owned)}: the controller's projection writes "
                                 "these (the settled orders, the event's number and time), a request never does; leave "
                                 "them out and keep `orders` only"))
            return problems
        if p["gate"] != "A":
            return problems
        try:
            sources = self.source_inputs(state)
        except (StateConflict, ValueError) as exc:
            return problems + [(StateConflict, str(exc))]
        if sources and p.get("source_inventory_hash") != sources["source_inventory_hash"]:
            problems.append((StateConflict, "Gate A must bind current source inventory hash"))
        try:
            plan_doc = self._plan_document()
        except (StateConflict, ValueError) as exc:
            return problems + [(StateConflict, str(exc))]
        from planning_contract import validate_plan
        rows = plan_doc.get("rows") if isinstance(plan_doc, dict) else plan_doc
        if not isinstance(rows, list):
            return problems + [(ValueError, "structured test plan rows must be a list")]
        if state.get("scope") and not rows:
            problems.append((StateConflict, "managed Gate A cannot approve a nonempty scope with an "
                             "empty structured plan"))
        # The mirror of that rule: an approved scope of nothing under a plan full
        # of rows approves nobody's work, and every later `if state["scope"]` guard
        # then passes silently (I-03c).
        if rows and not state.get("scope"):
            named = ", ".join(str(row.get("id")) for row in rows[:5] if isinstance(row, dict))
            errors = [f"Gate A cannot approve an empty scope while the plan has "
                      f"{len(rows)} row(s) ({named}{', ...' if len(rows) > 5 else ''})"]
            blocking, _ = self._passed_by_person("S4", errors)
            if blocking:
                problems.append((StateConflict,
                                 blocking[0] + "; record the reviewed scope with "
                                 f"`case_versions.py --task-root {self.store.root} --all` (or `--operation revise_plan`) "
                                 "before the decision, or, if the person "
                                 "decided this story approves nothing, record their words: `"
                                 + person_words.door("waiver.py --task <TICKET> --stage S4 "
                                                     "--block \"empty scope\"") + "`."))
        plan_errors = validate_plan(rows, require_v2=state.get("coverage_contract_version", 1) == 2)
        if plan_errors:
            problems.append((StateConflict, "structured test plan invalid: " + "; ".join(plan_errors)))
        if p.get("plan_content_hash") != content_hash(plan_doc):
            problems.append((StateConflict, "Gate A receipt must bind exact current structured plan "
                             "content_hash; copy `--operation gate-inputs` unchanged"))
        if p.get("plan_semantic_hash") != self._plan_semantic_hash(plan_doc):
            problems.append((StateConflict, "Gate A receipt must bind server-derived semantic plan hash"))
        if p.get("oracle_content_hashes") != self._oracle_hashes(rows):
            problems.append((StateConflict, "Gate A receipt must bind exact requirement oracle content hashes"))
        try:
            revisions = self._coverage_contract_revisions(rows, state.get("plan_contract_mode") == "legacy")
        except StateConflict as exc:
            return problems + [(StateConflict, str(exc))]
        if p.get("coverage_contract_revisions", []) != revisions:
            problems.append((StateConflict, "Gate A receipt must bind exact coverage-contract revisions"))
        actions = plan_doc.get("lifecycle_actions", []) if isinstance(plan_doc, dict) else []
        from case_lifecycle import validate_actions
        lifecycle_errors = validate_actions(actions)
        if lifecycle_errors:
            problems.append((StateConflict, "lifecycle actions invalid: " + "; ".join(lifecycle_errors)))
        elif actions:
            problems.extend(self._lifecycle_problems(p, state, actions))
        pinned = {str(link.get("case_id")): str(link.get("version")) for link in self._pinned_links()}
        if state.get("scope"):
            # CX1-11: a member is pinned when the index keys it under a pinned case (a bare id, or the area-qualified
            # key `revise_plan` wrote), the one reading `revise_plan` and the door share (I1, I2)
            ids, resolution = self._scope_membership(state["scope"])
            missing = sorted({str(member) for member, _, why in resolution if why})
            if not ids or missing:
                problems.append((StateConflict, "managed Gate A requires nonempty pinned case versions for "
                                 "the approved scope; unpinned: " + (self._listed(missing) or "all")
                                 + self._scope_door(state["scope"])))
        problems.extend((StateConflict, message)
                        for message in self._design_review_problems(p, state, rows, pinned))
        return problems

    def _lifecycle_problems(self, p, state, actions):
        problems = []
        if p.get("lifecycle_actions_hash") != content_hash(actions):
            problems.append((StateConflict, "Gate A receipt must bind exact lifecycle actions hash"))
        if any(action.get("kind") == "retire" and not action.get("proposed_code_changes")
               for action in actions):
            problems.append((StateConflict, "retirement needs approved reviewable code removal at Gate A"))
        decisions = p.get("lifecycle_decisions")
        if p.get("lifecycle_actions") != actions and not isinstance(decisions, list):
            problems.append((StateConflict, "Gate A must include lifecycle actions or explicit "
                             "lifecycle decisions"))
        if isinstance(decisions, list):
            by_id = {str(d.get("action_id")): d for d in decisions if isinstance(d, dict)}
            for action in actions:
                item = by_id.get(str(action.get("action_id")))
                if (not item or item.get("status") not in {"approved", "deferred"}
                        or item.get("source_revision") != state["source_revision"]
                        or item.get("action_hash") != content_hash(action)):
                    problems.append((StateConflict, "each lifecycle decision must bind action, source "
                                     "revision and exact hash; status must be approved or deferred"))
                elif action.get("kind") == "retire" and item.get("status") != "approved":
                    problems.append((StateConflict,
                                     "retirement needs approved reviewable code removal at Gate A"))
        return problems

    def check_decision(self, payload):
        """Every problem `decision` would raise on this request, without writing anything.

        The rehearsal package (`gate_preflight`) calls it before the gate is shown, so a
        refusal that is computable in advance never arrives after a person has approved.
        """
        try:
            return [message for _, message in self._decision_problems(dict(payload or {}), self.state())]
        except (StateConflict, ValueError, KeyError, OSError, TypeError) as exc:
            return [f"the decision could not be checked: {type(exc).__name__}: {exc}"]

    _items_memo = None       # {(gate, pipeline.json fingerprint): the rehearsal's read} while an `items_scope` is open, else None

    @contextlib.contextmanager
    def items_scope(self):
        """One decision, one rehearsal (M5, AR-12): inside this scope `_read_gate_items` runs the gate rehearsal once per distinct
        pipeline.json - the CLI's first read, the check inside `apply` and the one `validate` makes under the store lock all reuse it. A
        write of a person's word changes pipeline.json, so the next read is fresh. Outside a scope nothing is remembered."""
        outer = self._items_memo is not None
        if not outer:
            self._items_memo = {}
        try:
            yield
        finally:
            if not outer:
                self._items_memo = None

    def _read_gate_items(self, gate, fresh=False):
        """`gate_brief.open_rehearsal_items` for the story, reused inside an `items_scope` while pipeline.json is unchanged (`fresh`: never)."""
        import gate_brief
        try:
            fingerprint = hashlib.sha1((self.store.root / "pipeline.json").read_bytes()).hexdigest()
        except OSError:
            fingerprint = ""
        key = (str(gate).upper(), fingerprint)
        if self._items_memo is not None and not fresh and key in self._items_memo:
            return self._items_memo[key]
        read = gate_brief.open_rehearsal_items(self.store.root, str(gate).upper())
        if self._items_memo is not None:
            self._items_memo[key] = read
        return read

    def open_gate_items(self, gate, factory_problems=False, fresh=False):
        """`(problems, items)`: the `person_decides` items of the gate's FRESH rehearsal that no recorded word has answered.

        RH1-6, the owner's F-2 (27.10.2026): every such item stops a gate A decision - the factory records an approval only over what
        the person has worded, never over a question it showed them and nobody answered (FR-9, FR-59). Called by the two recording roads
        beside `_decision_problems`, never inside it: `check_decision` is what the rehearsal itself runs, so an item check inside it would
        make the rehearsal read its own result. "Answered" has ONE reading, `gate_brief.open_rehearsal_items` (the rehearsal's own drop,
        AR-13). Gate B: `([], [])` - its questions have their own executors.

        `problems` are one human sentence per item (`[<id>] <message> - needs your word: <says>`, no script, no block), the first
        `OPEN_ITEMS_LISTED` of them and `and N more`, then one closing sentence; `items` is the machine list, whole. A rehearsal that cannot
        run is no pass (AR-28): one problem with its doors, unless the person's word at S4 (`GATE_A_ITEMS_UNREADABLE`) is recorded.

        `factory_problems`: the caller holds problems that are the factory's own, which `approve as is` does not pass (`--as-is` is
        skipped while they stand): the closing sentence then does not offer that word (M2, FR-3, FR-46)."""
        if str(gate or "").upper() != "A":
            return [], []
        import gate_brief
        ticket = self._ticket()
        word = "" if factory_problems else gate_brief.as_is_word_of("A")
        read = self._read_gate_items("A", fresh)
        if read["status"] != "read":
            door = person_words.door(f'waiver.py --task {ticket} --stage S4 --block "{GATE_A_ITEMS_UNREADABLE}"')
            text = (f"the gate A open items could not be listed ({read['why']}) - the person's word passes this: `{door}`"
                    + (f"; or they answer `{word}`" if word else "") + "; or retry")
            return ([text], []) if self._passed_by_person("S4", [text])[0] else ([], [])
        items = read["items"]
        problems = []
        for item in items[:OPEN_ITEMS_LISTED]:
            sentence = f"[{item['id']}] {item['message']} — needs your word: {item['door']['says']}"
            problems.append(sentence if len(sentence) <= OPEN_ITEM_SENTENCE else sentence[:OPEN_ITEM_SENTENCE] + "…")
            if item["door"]["kind"] == "none":
                problems.append(f"item {item['id']}: the factory cannot name a block a recorded word would pass (owner factory)")
        if len(items) > OPEN_ITEMS_LISTED:
            problems.append(f"and {len(items) - OPEN_ITEMS_LISTED} more: `gate_preflight.py --task {ticket} --gate A --text`")
        if items:
            problems.append("Your approval is kept; it records once each item above has your word"
                            + (f" — or answer `{word}` to approve over all of them, each recorded with your words." if word else "."))
        return problems, items

    def record_as_is(self, gate, words):
        """`approve as is` (the owner's word, a closed data word of gate A): one waiver per open item, each with the person's words
        as the decision, at the item's own block - never `*` (A-AC3b). Returns the ids it covered (`[]`: nothing was open).

        A `line` item is recorded at its door's block, a `words` item at its self-verified block, a `none` item at its OWN block at S4
        (`gate_brief.none_item_block`, which `open_rehearsal_items` reads back as answered), an unreadable list at
        `GATE_A_ITEMS_UNREADABLE` (S4). The entries are stored by `waiver.record_stage_overrides` - the one place a person's word over a
        block is stored AND journalled as a `human_answer` line (AR-14, FR-8); a block already recorded is replaced, so a retry is
        harmless. The re-read after recording is FRESH and must find nothing open: what it still finds is refused and named, and the
        decision is NOT recorded (FR-9). The caller declares the word was said (the driver's one normaliser); the words go in verbatim."""
        import contract
        import gate_brief
        import waiver
        if str(gate or "").upper() != "A":
            return []            # the CLI refuses `--as-is` at any other gate before this is reached (`main`)
        read = self._read_gate_items("A")
        if read["status"] == "read":
            targets = [(i["id"], i["door"]["stage"], i["door"]["block"]) if i["door"]["kind"] != "none"
                       else (i["id"], gate_brief.AS_IS_STAGE, gate_brief.none_item_block("A", i)) for i in read["items"]]
        else:
            targets = [("the open items", gate_brief.AS_IS_STAGE, GATE_A_ITEMS_UNREADABLE)]
        if not targets:
            return []
        label = targets[0][0]
        try:
            # `accept - the person wrote: <words>`: a stand-gap card's reader takes the decision's FIRST word as the option
            # (`contract.stand_gap_decisions`), so the words alone would read as "in your own words" and ask the card again
            decision = contract.person_decision("accept", str(words).strip())
            waiver.record_stage_overrides(self.store.root / "pipeline.json", self._ticket(),
                                          [(stage, block, decision) for _, stage, block in targets], quiet=True)
        except (OSError, ValueError) as exc:
            raise StateConflict(f"approve as is: the word for {label} could not be recorded ({type(exc).__name__}: {exc}); no decision "
                                "was recorded - retry, or record the person's word with waiver.py") from None
        left = self.open_gate_items("A", fresh=True)
        if left[1] or left[0]:
            raise StateConflict("approve as is: still open after recording: " + "; ".join(left[0][:OPEN_ITEMS_LISTED])
                                + " - no decision was recorded")
        return [label for label, _, _ in targets]

    def build_gate_decision(self, gate, words, drafts=None, bugs=None, mr=None, risks=None):
        """The whole `decision` request for the state as it stands, built by code.

        The orchestrator used to read this file to learn the shape, and still got it wrong
        twice (TP1-15045). Everything here is derived: nobody types a hash, a scope or
        a design review, and `authorization_source` is the person's words verbatim.

        `risks` (HF8-23, gate B only): the person's reason to deliver with known gaps, as they gave it; it becomes the request's
        `deliver_with_risks: {reason}` and `gate_b_record` projects it unchanged. None = no such decision. Refused, with a door: at
        gate A (it orders a delivery, which gate A does not), a blank reason (never invented: ask once), and next to `--mr
        do_not_open` or `not_offered` (the packet would contradict itself, FR-10).
        """
        gate = str(gate or "").upper()
        problems = []   # K1 (C3-11): the gate and the words are independent fields of the call
        if gate not in ("A", "B"):
            problems.append((ValueError, "gate must be one of: A, B"))
        for flag, value, allowed in (("--bugs", bugs, BUGS_FLAG_VALUES), ("--mr", mr, MR_FLAG_VALUES)):
            if value is None:
                continue
            if gate == "A":
                problems.append((ValueError, f"{flag} orders work of gate B (the bug reporter, the MR) and is gate B only: "
                                             f"leave {flag} out of the gate A decision"))
            elif value not in allowed:
                problems.append((ValueError, f"{flag} must be one of: {', '.join(allowed)}; got {value!r}"))
        if gate == "B" and bugs == "not_ordered" and any(str(ref).strip() for ref in (drafts or [])):
            # FR-10: one packet does not contradict itself - chosen drafts ARE the order to file them
            problems.append((ValueError, "--bugs not_ordered says no bug is to be filed, but --drafts chose drafts to file: the "
                                         "decision would contradict itself. Drop --drafts (no bug is filed), or record --bugs ordered "
                                         "(the chosen drafts are filed)"))
        if risks is not None:
            if gate == "A":
                problems.append((ValueError, "--risks-file records a decision to deliver with known gaps, which orders a delivery and is "
                                             "gate B only: leave --risks-file out of the gate A decision"))
            elif not str(risks).strip():
                problems.append((ValueError, "the decision to deliver with known gaps carries no reason: a reason is never invented. Ask the "
                                             "person once for it, then give it whole: `deliver with known gaps: <reason>` on a line of "
                                             "their words, or --risks-file <file holding the reason>"))
            elif mr in ("do_not_open", "not_offered"):
                problems.append((ValueError, f"a decision to deliver with known gaps and --mr {mr} contradict each other: delivering opens "
                                             "the MR. Drop the risks (leave --risks-file out and take the line out of the words), or record "
                                             "--mr open (with a verdict of no the MR is offered only by that word)"))
        if not str(words or "").strip():
            problems.append((ValueError, "--words must carry the person's own words; they are the "
                                         "authorization_source of the recorded decision. Pass --words-file <path "
                                         "to their words, as they were given>"))
        self._raise_all(problems)
        state = self.state()
        ticket = self._ticket()
        base = f"gate{gate}-{ticket}"
        identifier, suffix = base, 2
        while identifier in state.get("decisions", {}):
            identifier, suffix = f"{base}-{suffix}", suffix + 1
        request = {"id": identifier, "gate": gate,
                   "action": "approve_plan_and_cases" if gate == "A" else "approve_delivery",
                   "status": "approved", "authorization_source": str(words),
                   "source_revision": state.get("source_revision"),
                   "input_revision": state.get("plan_revision") or state.get("source_revision"),
                   "scope": sorted(state.get("scope") or []),
                   "expected_revision": state.get("revision"),
                   "idempotency_key": "decision:" + identifier}
        if gate == "B":
            # Which drafts a person chose is a person's answer, not a derivation; an empty
            # list is a valid Gate B. `--drafts` carries it, because a caller who had to add
            # the refs to the printed request afterwards was hand-building the very JSON
            # s0.md forbids (0.7.7 review, finding D-F3).
            request["selected_drafts"] = [str(ref).strip() for ref in (drafts or [])
                                          if str(ref).strip()]
            # What the person decided is carried out by executors (t-1509): the bug reporter files the chosen drafts (or all
            # that were ordered by `--bugs ordered`), the delivery step opens the MR unless the person said not to. No flag
            # is "as before 0.10.5 for the MR": it is ordered. `--bugs not_ordered` with drafts chosen is refused above (FR-10).
            request["orders"] = {
                "bugs": ORDER_DUE if request["selected_drafts"] or bugs == "ordered" else ORDER_NOT_ORDERED,
                "mr": ORDER_NOT_ORDERED if mr in ("do_not_open", "not_offered") else ORDER_DUE}
            if risks is not None:
                request["deliver_with_risks"] = {"reason": str(risks)}     # the person's reason verbatim (E6: no limit); projected whole
            return request
        request.update(self.gate_inputs())
        document = self._plan_document()
        rows = document.get("rows") if isinstance(document, dict) else document
        rows = rows if isinstance(rows, list) else []
        actions = document.get("lifecycle_actions", []) if isinstance(document, dict) else []
        if actions:
            request["lifecycle_actions"] = actions
        request["design_reviews"] = self._build_design_reviews(state, rows)
        return request

    @staticmethod
    def _declared_review_verdict(task_root):
        """`accepted`, or the critic's own non-approving word, from `critic-findings.md`.

        The gate-A design review used to be built with the constant `accepted` whatever the
        critic had actually declared, so a `reject` or a `partial` roll-call reached the
        person as an accepted independent review (0.7.7 review, finding B-F6). An unreadable
        or absent findings file keeps `accepted`: a story from 0.7.4 has none, and a missing
        file is not evidence of a bad review.
        """
        try:
            from critic_rollcall import APPROVING_VERDICTS, declared_verdict, findings_files
            declared = [declared_verdict(path.read_text(encoding="utf-8", errors="replace"))
                        for path in findings_files(task_root)]
        except (ImportError, OSError, ValueError, TypeError):
            return "accepted"
        refusing = [word for word in declared if word and word not in APPROVING_VERDICTS]
        return refusing[-1] if refusing else "accepted"

    @staticmethod
    def _findings_refs(dispatch):
        """`[(ref, area)]`: the evidence refs of one critic dispatch that name a case critic's `critic-findings.md`
        under `test-cases/` (the file `critic_rollcall.findings_files` scans - one name rule), with the area folder
        the file sits in (`""` when directly under `test-cases/`)."""
        from critic_rollcall import FINDINGS_FILE_NAME
        refs = (dispatch or {}).get("evidence_refs")
        found = []
        for ref in refs if isinstance(refs, list) else []:
            parts = ([part for part in str(ref.get("path") or "").replace("\\", "/").split("/") if part]
                     if isinstance(ref, dict) else [])
            if parts and parts[-1] == FINDINGS_FILE_NAME and "test-cases" in parts:
                found.append((ref, "/".join(parts[parts.index("test-cases") + 1:-1])))
        return found

    def _read_findings_ref(self, ref, area, cases, memo, why=None, accepted=()):
        """`critic_rollcall.scoped_verdict` of one findings ref over `cases`: `(word, listed)`, the `(basis, reason)`
        of a word that is not `accepted` appended to the list `why`. A path that is not a sound relative file under
        the story (`_path_issue`) is `unreadable` and `partial`, its issue named. The ref's own sha256 is NOT checked
        as a whole here: the file moves on when a later round is prepended, and `scoped_verdict` accepts only the
        suffix of it that the receipt measured, and only that suffix's first round - which ends where the receipt
        of the next-older accepted round of the SAME file begins (the receipts of `accepted` are passed for that)."""
        from critic_rollcall import scoped_verdict
        why = why if why is not None else []
        raw = str(ref.get("path") or "")
        if raw not in memo["files"]:
            issue = self._path_issue(raw, "case critic findings")
            memo["files"][raw] = issue or (self.store.root.resolve() / raw).read_bytes()
        if isinstance(memo["files"][raw], str):
            why.append(("unreadable", f"{raw}: {memo['files'][raw]}"))
            return "partial", {str(case) for case in cases}
        def parts(path):
            return [part for part in str(path or "").replace("\\", "/").split("/") if part not in ("", ".")]
        receipts = [str(other.get("sha256") or "") for dispatch in accepted or ()
                    if dispatch.get("role") == "qa-case-critic"
                    for other, _ in self._findings_refs(dispatch) if parts(other.get("path")) == parts(raw)]
        notes = []
        word, listed = scoped_verdict(memo["files"][raw], ref.get("sha256"), cases, self.store.root, area,
                                      memo["tails"], notes, receipts)
        # The file whose bytes moved is named: the refusal has to say WHICH file changed under its receipt (FR-1).
        why.extend((basis, f"{raw}: {reason}" if basis == "receipt_mismatch" else reason) for basis, reason in notes)
        return word, listed

    def _later_refusal(self, critic, accepted, wanted, memo):
        """`(word, why, dispatch_id)` of the first accepted critic round LATER than `critic` that refuses one of
        `wanted`, scope or not (M-5), or None. Its `reject` refuses, and so does a declared word outside the
        critic's list (kept as written, FR-35). A later round whose bytes were edited after its receipt may be
        rejecting them: that doubt is `partial`, never skipped (I1; m-2 of t-1103); so is a round whose `Verdict:` line
        says `reject` over cells that all approve (`round_word_rule`: not an acceptance until the critic rewrites the
        line). Its own `partial` - an
        unreviewed row, or the word itself - does not refuse what the covering round approved."""
        from critic_rollcall import CASE_CRITIC_VERDICTS
        at = next((i for i, d in enumerate(accepted) if d is critic), None)
        newer = [] if at is None else [d for d in list(accepted)[at + 1:] if d.get("role") == "qa-case-critic"]
        for dispatch in newer:
            for ref, area in self._findings_refs(dispatch):
                notes = []
                word, listed = self._read_findings_ref(ref, area, wanted, memo, notes, accepted)
                # a word that contradicts its own cells is not an acceptance until the critic rewrites it (HF4-11, the error
                # direction: toward not `accepted`), exactly like bytes edited after the receipt
                stale = bool(notes) and notes[0][0] in ("receipt_mismatch", "round_word_rule")
                if listed and (word == "reject" or word not in CASE_CRITIC_VERDICTS + ("accepted",) or stale):
                    return word, notes, str(dispatch.get("id") or "")
        return None

    def _dispatch_review_verdict(self, critic, cases, accepted=(), memo=None, why=None):
        """The verdict of ONE plan row, read from the accepted critic dispatch that covered it.

        FB-19: `_build_design_reviews` stamped `_declared_review_verdict` - the last refusing word over ALL
        findings files on disk - onto every row, so a findings file nobody accepted decided a gate and a scoped
        repair round's `approve` on top of the file cleared rows it never reviewed. Only the selected dispatch's
        receipt counts: each findings ref it carries is read for the cases its roll-call names
        (`scoped_verdict`: the receipt's bytes, ONE round, the `verdict` column, or the round's own word where
        the table has none). A case no ref names, a ref that does not resolve or whose bytes the receipt did
        not measure, and any exception, are `partial` - never `accepted` on a doubt (I1, FR-59). A `reject` of
        any ref decides first, then the first other non-approving word; a case no ref names adds its own reason
        and never hides a `reject` (FR-35). A LATER accepted critic round that refuses one of these cases counts
        too, scope or not (`_later_refusal`). No critic, no findings ref (an older receipt) or a row with no cases
        keep the older rule (I4). A list passed as `why` gets `(basis, reason, dispatch_id)` per reason of a word
        that is not `accepted`, the deciding one first: the dispatch is the one whose round produced the word."""
        found = self._findings_refs(critic)
        if not found or not cases:
            return self._declared_review_verdict(self.store.root)
        why = why if why is not None else []
        memo = memo if memo is not None else {"files": {}, "tails": {}}
        wanted = {str(case) for case in cases}
        own = str((critic or {}).get("id") or "")
        try:
            reads, remaining = [], set(wanted)
            for ref, area in found:
                notes = []
                word, listed = self._read_findings_ref(ref, area, wanted, memo, notes, accepted)
                if listed:
                    reads.append((word, notes))
                    remaining -= listed
            unnamed = ([("no_review", "its roll-call does not name " + ", ".join(sorted(remaining or wanted)))]
                       if remaining or not reads else [])
            refusing = sorted((read for read in reads if read[0] != "accepted"), key=lambda read: read[0] != "reject")
            word = refusing[0][0] if refusing else "partial" if unnamed else "accepted"
            notes = [note for _, read_notes in refusing for note in read_notes] + unnamed
            later = self._later_refusal(critic, accepted, wanted, memo) if word == "accepted" else None
            if later:
                said = ("a later accepted critic round refuses it: " if later[0] != "partial" else
                        "a later accepted critic round may refuse it and cannot be read: ")
                word, notes, own = later[0], [(basis, said + reason) for basis, reason in later[1]], later[2]
            why.extend((basis, reason, own) for basis, reason in notes)
            return word
        except Exception:
            why.append(("unreadable", "its roll-call could not be read", own))
            return "partial"

    def _build_design_reviews(self, state, rows):
        """One review per critical plan row, from the case index, the pins and S4 receipts.

        `case_versions` here are the CURRENT pins, so the check that compares them with the current pins can never
        fail on the build->check path; a review does not bind the case bytes the critic saw. What binds it is the
        ORDER of the accept events (`accept_order`, `_design_review_problems`, `review_is_stale`): a designer accepted
        after the critic voids the receipt. A case re-pinned by code after the critic (apply-fixes) has no designer
        dispatch, so the binding stands - the known limit (E-D4)."""
        pinned = {str(link.get("case_id")): str(link.get("version")) for link in self._pinned_links()}
        by_row = self._row_cases(state, rows)
        reviewed = self._rollcall_reviewed()
        accepted = [d for d in state.get("dispatches", {}).values()
                    if d.get("stage") == "S4" and d.get("status") == "accepted"]
        memo = {"files": {}, "tails": {}}   # each findings file read, and its receipt suffix found, once per build
        reviews = []
        for row in rows:
            if not isinstance(row, dict) or not row.get("design_review_required"):
                continue
            row_id = str(row.get("id"))
            cases = set(by_row.get(row_id) or ())
            author = self._last_covering(accepted, "qa-case-designer", cases, reviewed, row_id)
            critic = self._last_covering(accepted, "qa-case-critic", cases, reviewed, row_id)
            why = []
            review = {
                # FB-19: the verdict is this row's, from the receipt that reviewed it (`_dispatch_review_verdict`).
                "plan_row": row_id, "verdict": self._dispatch_review_verdict(critic, cases, accepted, memo, why),
                # How the author was credited, from the same rule body the gate check reads.
                "author_basis": (self._cover_basis(author, cases, reviewed, row_id) if author else "none"),
                "plan_revision": state.get("plan_revision") or state.get("source_revision"),
                "case_versions": sorted({pinned[case] for case in cases if case in pinned}),
                "input_hash": (critic or author or {}).get("input_hash", ""),
                "author_dispatch_id": (author or {}).get("id", ""),
                "reviewer_dispatch_id": (critic or {}).get("id", "")}
            if why and review["verdict"] != "accepted":
                # Where the word came from: `verdict_basis` is what code branches on (the refusal's sentence, the
                # driver's routing of a doubt), `verdict_source` the prose naming the round that produced the word -
                # never a word the critic did not write. Reasons past the third are counted, not dropped silently.
                basis, _, origin = why[0]
                shown = "; ".join(reason for _, reason, _ in why[:3])
                review["verdict_basis"] = basis
                review["verdict_source"] = (f"round of dispatch {origin}: {shown}"
                                            + (f" (and {len(why) - 3} more)" if len(why) > 3 else ""))
            reviews.append(review)
        return reviews

    @staticmethod
    def _last_covering(dispatches, role, cases, reviewed, row=None):
        """The latest accepted dispatch of `role` that covered these cases (or this plan row)."""
        candidates = [d for d in dispatches
                      if d.get("role") == role and Controller._covers(d, cases, reviewed, row)]
        return candidates[-1] if candidates else None

    def build_rework_request(self, stage, role, cases, reason, purpose="repair_verify", rows=None,
                             cause=None, words_given=False, parallel_window=False):
        """A dispatch request that sends a role back over part of its own accepted work.

        Rework was guesswork: the orchestrator hand-built the packet three times and was
        refused three times, once by a bare `KeyError` (TP1-15045). Everything a repeat
        of accepted work needs is already in that work's receipt — input hash, paths,
        budget — so only the cases and the reason are arguments.

        S1–S3 have no cases yet: their roles work on sources, requirements and plan rows.
        `--cases` is optional there and `--rows` names the plan rows to go back over
        (TP2-2523 built that request by hand because `--cases` was mandatory).

        `words_given` is True when the reason is a PERSON's words (`--words-file`): only then does
        the request carry the `rerun_after` stamp (`_rerun_stamp`). A reason typed by code
        (`--reason`: the driver's repairs, the conductor's refusal repairs) is the factory's own
        finding, and a rework it asks for never stales a stage it did not name.

        `parallel_window` (t-1937 TR3-4) is the driver's scheduler asking for this round to run beside a running S5 window
        (`--parallel-window`): the request then carries `parallel_window: True`, which `_window_beside_running` reads at dispatch.
        Anything but the boolean True adds nothing, so every other caller builds the request it always built.
        """
        state = self.state()
        stage, role = str(stage or ""), str(role or "")
        # K1 (C3-11): every check of the call is collected and refused whole - all are the call's fault
        # (`ValueError`). Two read the stage as a number, so they run only for a stage that parsed: the
        # case count (S4 and later need cases) and the accepted dispatch (a stage that is no stage has none).
        problems = []
        stage_ok = stage.startswith("S") and stage[1:].isdigit() and 0 <= int(stage[1:]) <= 9
        if not stage_ok:
            problems.append((ValueError, f"stage {stage!r} must be one of: " + ", ".join(f"S{i}" for i in range(10))))
        if purpose not in PURPOSES:
            problems.append((ValueError, f"purpose {purpose!r} must be one of: " + ", ".join(sorted(PURPOSES))))
        reopen = self._reopen_stamp(state, reason)
        if not str(reason or "").strip():
            if reopen:
                problems.append((ValueError, "this story is closed (gate B is decided and S8 is done), and "
                                             "rework of a closed story REOPENS it — which is a person's "
                                             "decision, not the factory's. `--reason \"<their own words>\"` "
                                             "records it; it is written into pipeline.json as "
                                             "`reopened_by_words` beside `reopened_at`."))
            else:
                problems.append((ValueError, "--reason must say what this round repairs; it is what the role reads"))
        if cause and cause not in REPAIR_CAUSES:
            problems.append((ValueError, f"--cause {cause!r} must be one of: " + ", ".join(REPAIR_CAUSES)))
        # t-2181 PC-6 (C12; t-2277 J-C8): a story HELD FOR CODE refuses the rework of any stage from `held_from` (the story's state,
        # so a StateConflict, FR-46) and, once the person stopped the wait, any rework of the stages below it that is not their
        # words. INVARIANT: no dispatch of a stage the hold keeps closed is built here, and a STOPPED story is reopened only by
        # a person's word (`await_reopened` rides on the rework's own dispatch event, the projection removes `stopped`), never
        # by a reason typed by code. Every refusal names the doors (FR-2, AR-9).
        hold, held_number = _hold_of(state)
        reopens_hold = False
        if stage_ok and hold["state"] != "none":
            number = int(stage[1:])
            door = _hold_doors(held_number)
            doors = f"doors: {door['arrive']}; {door['stop']}; {door['rework']}"
            if number >= held_number:
                problems.append((StateConflict, f"this story is held for code ({hold['cause']}) from S{held_number}: a rework of {stage} "
                                                f"would run a stage the hold keeps closed. {doors}"))
            elif hold["state"] == "stopped":
                if words_given:
                    reopens_hold = True
                else:
                    problems.append((StateConflict, f"this story was stopped while it waited for code: a rework of {stage} reopens it, "
                                                    f"which is the person's word - `--reason` (typed by code) is refused; pass "
                                                    f"`--words-file <file>` with their own words. {doors}"))
        wanted = [str(case).strip() for case in (cases or []) if str(case).strip()]
        wanted_rows = [str(row).strip() for row in (rows or []) if str(row).strip()]
        # X7-6c (B2): the author of a stage its CONSUMER sent back (a `reject` record of S6 / S7) is reworked over the scope of the dispatch the
        # record reviewed - that is the unit the consumer judged, one half for the runner, and the repair ledger counts the round under the
        # same key as the first dispatch. The call carries no `--cases`: the record is the reason's source, not a case list.
        sent_back = self._consumer_reject_parent(state, stage, role) if stage_ok and not wanted else None
        if sent_back:
            wanted = [str(case) for case in sent_back.get("scope") or [] if str(case).strip()]
        if stage_ok and not wanted and int(stage[1:]) > 3:
            # RH1-10 (DC1-13, B-AC4): the refusal names a door. Its receivers are the direct `--operation rework` callers (the
            # driver's roads never reach it: `no_move.check_args` and `answer_pairs_owed` stop an empty S4+ list first). It names
            # only what `rework` takes: `--cases`; `execution_kind` is a `stage-scope` parameter, not a `rework` one.
            problems.append((ValueError, "--cases must name at least one case of the approved scope: `controller.py --operation "
                                         "stage-scope` lists them"
                                         + (f"; S6 is reworked one half per call: `--cases` of the manual half (at most "
                                            f"{MANUAL_BLOCK_CASES}) or of the automated half — `stage-scope` with `execution_kind` "
                                            "lists each" if stage == "S6" and role == "qa-runner"
                                            and state.get("plan_contract_mode") == "new" else "")))
        # N-3: `wanted` is canonicalised ONCE, by the helper `dispatch` refuses with (I1: a person writes `TC-004`, or
        # `session-feedback/TC-004`); the canonical list feeds the scope, the pins' links and `_rerun_stamp` alike.
        canonical, outside = self._outside_approved(wanted, state.get("scope") or [])
        unknown = [member for member, _ in outside]
        if unknown:
            problems.append((ValueError, f"case(s) outside the approved scope: {', '.join(unknown)}; the approved "
                                         f"scope is {', '.join(sorted(map(str, state.get('scope') or []))) or 'empty'}"
                                         + self._scope_door(state.get("scope"), wanted)))
        if wanted_rows:
            known = []
            try:
                document = self._plan_document()
                plan_rows = document.get("rows") if isinstance(document, dict) else document
                known = [str(row.get("id")) for row in plan_rows or [] if isinstance(row, dict) and row.get("id")]
            except (StateConflict, ValueError, AttributeError, TypeError):
                known = []
            missing = [row for row in wanted_rows if known and row not in known]
            if missing:
                problems.append((ValueError, f"plan row(s) not in the approved plan: {', '.join(missing)}; "
                                             f"the plan has {', '.join(known)}"))
        prior = [d for d in state.get("dispatches", {}).values()
                 if d.get("stage") == stage and d.get("role") == role and d.get("status") == "accepted"]
        # FB-9 (R12): a new-mode qa-runner packet says which half it runs, and a manual rework is a manual BLOCK. The kind comes
        # from the CASES (their disposition in the plan); the parent is of that kind, so `rework_of`, `input_hash`, the budget and
        # the resumed agent are the half's own. Every problem joins the call's other problems (one refusal).
        kind = None
        if stage_ok and role == "qa-runner" and state.get("plan_contract_mode") == "new":
            kind, kind_problems = self._rework_kind(stage, state, canonical, prior)
            problems.extend((ValueError, text) for text in kind_problems)
            if kind:
                prior = [d for d in prior if self._record_kind(d) == kind]
            if kind == "manual":
                problems.extend((ValueError, text) for text in self._rework_block_problems(stage, state, canonical))
            elif kind == "automation":     # RH1-10: cause 2 (a handed case) and an unreadable plan; `_rework_kind` already refused the rest
                problems.extend((ValueError, text) for text in self._half_membership_problems(stage, state, canonical, "automation"))
        # SC1-14 B1a (E31): S5 holds two kinds of dispatch of one role, the plan and the windows. The parent of a rework is of the
        # kind the rework is FOR (`--purpose s5_plan` = the plan), so the door the plan names ("plan stale -> rework --purpose
        # s5_plan") is not closed by the last window. A story with no plan record has every record a window: unchanged.
        other_kind = []
        if stage == "S5":
            for_plan = purpose == S5_PLAN
            other_kind = [d for d in prior if (s5_part_of(d) == "plan") != for_plan]
            prior = [d for d in prior if (s5_part_of(d) == "plan") == for_plan]
        if stage_ok and not prior:
            roles = sorted({str(d.get("role")) for d in state.get("dispatches", {}).values()
                            if d.get("stage") == stage and d.get("status") == "accepted"})
            # C1-6a A11 (t-698 §12.3): a LIVE dispatch of this role on this stage is not "nothing to rework" - it is work
            # that has not been accepted, and a rework sends back accepted work only. Both doors are the conductor's own.
            live = [d for d in state.get("dispatches", {}).values()
                    if d.get("stage") == stage and d.get("role") == role and d.get("status") in OPEN_AFTER_CLOSURE
                    and (stage != "S5" or (s5_part_of(d) == "plan") == (purpose == S5_PLAN))]
            if stage == "S5" and purpose == S5_PLAN and not live:
                problems.append((ValueError, f"no accepted S5 plan dispatch of {role} to rework; a plan never accepted is "
                                             f"dispatched with `story_step.py start --purpose s5_plan`"))
            elif stage == "S5" and other_kind and not live:
                problems.append((ValueError, f"no accepted S5 window of {role} yet; the plan is reworked with "
                                             f"`--purpose s5_plan`"))
            elif live:
                found = live[-1]
                problems.append((ValueError, f"no accepted {role} dispatch on {stage} to rework: {found.get('id')} is "
                                             f"{found.get('status')}, not accepted, and a rework sends back accepted work only. "
                                             f"To give {found.get('id')} another turn, the driver resumes it (answer `continue` "
                                             "after recording nothing); to start it again from its brief, "
                                             f"`release --dispatch {found.get('id')} --words-file <their words>` and `next` "
                                             f"relaunches it; accepted roles on {stage}: {', '.join(roles) or 'none'}"))
            else:
                problems.append((ValueError, f"no accepted {role} dispatch on {stage} to rework"
                                             + (f" ({kind} half)" if kind else "") + f"; accepted roles on "
                                             f"{stage}: {', '.join(roles) or 'none'}"))
        parent, resumable = None, True       # None: the last accepted record of the kind (S1-S4, S6-S9, the plan)
        if stage_ok and kind == "manual" and prior:
            # E25: the parent of a manual rework is the block that HOLDS the case (the last accepted one of the half meeting the
            # cases; cases of two blocks take the later); none holds it -> the last of the half. Its input_hash/budget/paths are its own.
            held = [d for d in prior if set(map(str, d.get("manual_case_ids") or [])) & set(canonical)]
            parent = held[-1] if held else None
        if sent_back and prior:
            parent = sent_back       # X7-6c: the consumer judged THIS dispatch; a later one (an S7 investigation) is no parent of its repair
        if stage_ok and stage == "S5" and purpose != S5_PLAN and prior:
            parent, resumable, spans = self._s5_window_parent(state, prior, canonical)
            if len(spans) > 1 and not words_given:      # F5: a person's words over several windows are not refused
                problems.append((ValueError, f"--cases meets {len(spans)} windows of S5 ({'; '.join(spans)}); a rework of a window "
                                             f"names the cases of ONE window. Door: rework each window by its own cases (`controller.py "
                                             f"--operation rework --stage S5 --role {role} --cases <the cases of one window> --reason "
                                             "<what to mend> --brief`); a rework over several windows is a person's words (`--words-file "
                                             "<their words>`)"))
        if not stage_ok:   # FR-59: the two checks that did not run say so, they never read as a pass
            problems = self._noted(problems, "(the cases-required and accepted-dispatch checks did not run: "
                                             "they read the stage as a number)")
        self._raise_all(problems)
        wanted = canonical
        last = parent or prior[-1]
        taken = set(state.get("dispatches", {}))
        number = len([d for d in state.get("dispatches", {}).values()
                      if d.get("stage") == stage and d.get("role") == role]) + 1
        identifier = f"{stage}-{role}-{number}"
        while identifier in taken:
            number += 1
            identifier = f"{stage}-{role}-{number}"
        known = last.get("known_paths") or {}
        if not known:
            try:
                known = self.prepare({"stage": stage})["resolved_paths"]
            except (OSError, ValueError, KeyError):
                known = {"task_root": str(self.store.root)}
        # t-335 A1: built by THIS package - portable, and stamped with this package's fingerprint (the record's own
        # stamp names the package of the old dispatch, and `dispatch` would refuse every rework after a package change)
        known = Controller._stamped_paths(known)
        request = {"id": identifier, "stage": stage, "role": role, "scope": sorted(wanted),
                   "input_hash": last.get("input_hash"), "known_paths": known,
                   "budget": last.get("budget") or {}, "purpose": purpose,
                   "rework_of": last.get("id"), "reason": str(reason),
                   "expected_revision": state.get("revision"),
                   "idempotency_key": "dispatch:" + identifier}
        if kind == "manual":      # a manual rework is a manual BLOCK: the scope IS the block (FB-9 R12 c)
            request["scope"] = list(dict.fromkeys(sorted(wanted)))
            request["manual_case_ids"] = list(request["scope"])
        if kind:
            request["execution_kind"] = kind
        # SC1-14 B1a (E3): a stage whose rework RESUMES its role (`rework_mode: resume`) hands the parent's host agent id on the
        # request; a fresh-agent stage, or a mode that cannot be read, carries none (the packet card names `bind`).
        resumed = str(last.get("agent_id") or "").strip() if resumable else ""
        if resumed:
            try:
                mode = self._rework_mode(stage)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                mode = "fresh"   # unreadable: the direction is a fresh launch, whose door (`bind`) stays alive
            if mode == "resume":
                request["agent_id"] = resumed
        # A repair works on the CURRENT pinned CaseVersion of each case it was sent for, never
        # on a version only a prior receipt still remembers (the S4 designer's accepted receipt
        # kept a stale link and the repair was done against it). Matching is the contract's own
        # (`case_matches`: a bare id matches a pin of any area), so a bare id pinned in two areas
        # brings both; a case with no pin brings nothing - the role is not handed an invented one;
        # a caseless request, or a story with no pin file, carries an empty list.
        from contract import case_link_key, case_matches
        request["case_version_links"] = [
            copy.deepcopy(link) for link in self._pinned_links()
            if any(case_matches(case_link_key(link), case) for case in wanted)]
        if wanted_rows:
            # Plan rows are not cases: `scope` stays the approved case ids (empty on S1–S3),
            # and the rows travel beside it so the guard's scope check keeps its meaning.
            request["plan_rows"] = sorted(wanted_rows)
        if cause:
            request["repair_cause"] = cause
        request.update(reopen)
        if reopens_hold:
            request["await_reopened"] = {"words": str(reason)}
        # The record says whose reason this is (t-694, F1): only a rework built from the person's words file carries the mark,
        # and the gate note quotes only such a reason as "your words". Same input as the stamp below (`words_given`), not a second test.
        if words_given:
            request["person_words"] = True
        # The B-364 road (`ticket_changed`) re-runs its own stages, and a closed story's rework is a
        # reopen (C1-6): two writers of one re-run never, so neither gets the stamp.
        if words_given and not reopen and cause != "ticket_changed":
            stamp = self._rerun_stamp(state, stage, role, wanted)
            if stamp:
                request["rerun_after"] = stamp
        if self._read_first(stage):
            request["read_first"] = self._read_first(stage)
        if parallel_window is True:
            request["parallel_window"] = True
        return request

    def _consumer_reject_parent(self, state, stage, role):
        """The dispatch record a CONSUMER role sent back (X7-6c): the `reviewed_dispatch` of the stage's latest acceptance record when that
        record is a `reject` of a stage with a consumer, the dispatch is an accepted one of `stage` by `role`, and `role` is the stage's author.
        None otherwise - then nothing about the call changes (a stage with no `acceptance_by`, no record, an `accept`, another role). Reads only."""
        import acceptance
        stage_def = acceptance.stage_def_of(stage)
        roles = stage_def.get("roles") or []
        if not acceptance.consumer_of(stage) or not roles or roles[0] != role:
            return None
        record = acceptance.stage_acceptance(self._pipeline(), stage)
        if not (isinstance(record, dict) and record.get("verdict") == "reject"):
            return None
        parent = (state.get("dispatches") or {}).get(str(record.get("reviewed_dispatch") or ""))
        ok = isinstance(parent, dict) and parent.get("stage") == stage and parent.get("role") == role and parent.get("status") == "accepted"
        return parent if ok else None

    @classmethod
    def _record_kind(cls, dispatch):
        """`manual` / `automation` / "" - the half a dispatch record ran (the request it was committed with, then its own field)."""
        return str(cls._original_request(dispatch).get("execution_kind") or dispatch.get("execution_kind") or "")

    def _rework_block_problems(self, stage, state, cases) -> list:
        """The sentences for a manual runner rework BLOCK (FB-9, R12 c): the shared block rules, the size with its ONE door (the
        first block's rework command, then the rest counted), and the plan membership. `[]` when the block is fine."""
        from detector_verdict import named
        scope_ids = list(dict.fromkeys(sorted(cases)))
        blocks = manual_blocks(scope_ids)
        door = (f". Door: rework the first block (`controller.py --operation rework --stage S6 --role qa-runner "
                f"--cases {','.join(blocks[0])} --reason <what to mend> --brief`), then {len(blocks) - 1} more block(s) of "
                f"at most {MANUAL_BLOCK_CASES} for: {named([c for b in blocks[1:] for c in b], SCOPE_SHOWN)}"
                if len(scope_ids) > MANUAL_BLOCK_CASES else "")
        problems = ["manual runner block: " + text + (door if text.endswith("split the block") else "")
                    for text in manual_block_problems(scope_ids, scope_ids)]
        return problems + self._half_membership_problems(stage, state, scope_ids, "manual")

    def _rework_kind(self, stage, state, cases, prior):
        """`(kind | None, [problems])` - the half a new-mode qa-runner rework runs (FB-9, R12 a), from its CASES.

        All `manual-agent` in the approved plan -> `manual`; all `automate` -> `automation`; both -> ONE problem with two doors
        (one packet, one half); a plan that DERIVES the scope and a case in neither half -> a problem naming it with the
        `stage-scope` door (F1: nobody's dispatch never rides along); a plan that derives no scope -> the half of the accepted
        S6 runner record(s) whose scope holds every case, and none or two halves is a problem that says the kind cannot be established
        (FR-59: an unknown never becomes a guess). `cases` empty -> `(None, [])`: the caller's own "--cases" problem speaks."""
        if not cases:
            return None, []
        from detector_verdict import named
        derived = self.stage_scope(stage, state)
        groups = derived.get("by_disposition") or {} if derived.get("derived") else {}
        manual = [case for case in cases if case in set(groups.get("manual-agent") or [])]
        automated = [case for case in cases if case in set(groups.get("automate") or [])]
        if manual and automated:
            return None, [f"--cases names both halves of {stage}: {named(manual, SCOPE_SHOWN)} are manual-agent cases and "
                          f"{named(automated, SCOPE_SHOWN)} are automated cases, and one packet runs one half. Door: rework each "
                          f"half by its own cases (`controller.py --operation rework --stage {stage} --role qa-runner --cases "
                          f"{','.join(manual)} --reason <what to mend> --brief`, and the same with `--cases {','.join(automated)}`)"]
        if derived.get("derived"):
            # the plan has answered: a case in neither half is nobody's dispatch (FR-4, AR-28), never a rider on the other half
            neither = [case for case in cases if case not in manual and case not in automated]
            if neither:
                return None, [f"not a case of either runner half in the approved plan: {named(neither, SCOPE_SHOWN)} - a case "
                              "disposed to a person or to no runner is nobody's dispatch. Door: `controller.py --operation "
                              f"stage-scope` with `execution_kind: manual` or `automation` lists the cases of each half; "
                              f"rework only those (`--cases <the cases of one half>`)"]
            return ("manual" if manual else "automation"), []
        wanted = set(cases)
        kinds = {self._record_kind(d) for d in prior if wanted <= {str(c) for c in d.get("scope") or []}} - {""}
        if len(kinds) == 1:
            return kinds.pop(), []
        return None, [f"the kind of this {stage} qa-runner rework cannot be established: the plan gives no manual or automated "
                      f"disposition to {named(cases, SCOPE_SHOWN)}, and "
                      + ("two halves of the accepted runner records hold them" if kinds
                         else "no accepted runner record holds them")
                      + f". Door: rework within one half (`controller.py --operation rework --stage {stage} --role qa-runner "
                        "--cases <the cases of one half> --reason <what to mend> --brief`)"]

    def _s5_window_parent(self, state, prior, wanted):
        """`(parent | None, resumable, spans)` for a rework of S5 WINDOW work (SC1-14 t-CF, B3 and F5; FJ-C edge 4). `prior` is the
        role's accepted window records in the journal's order; `wanted` the canonical cases asked for; `spans` one `window N: cases`
        text for each window that `wanted` meets. A window is the AUTHOR'S CHAIN (`_written_windows`, spec t-1314 section 2 item 5),
        not a slice of the cut: a rework, a retry and a relaunch are members of the window they continue, so the agent that holds
        the window's tests is the latest accepted member of its chain.

        - The parent is the LAST accepted member of the chains whose scope meets `wanted` - the window the cases are in - not the
          last record of the role: window 2's author is not the agent that wrote window 1's tests (a role other than the author has
          no chain: its parent is the last accepted record whose own scope meets `wanted`). No chain meets `wanted` (or none
          of its members is accepted): `None` (the caller keeps the last accepted record, for its `input_hash` and `budget` only)
          and not resumable, so the request carries no `agent_id` and the packet card names `bind`.
        - `wanted` that meets several written windows is refused with the door (one window's cases each), unless it is a person's
          words (`words_given`: the driver's rework on what a person said, F5): their words are not the factory's own repair, so it
          is not refused - and it resumes no agent, for no one agent holds several windows."""
        want = {str(case) for case in wanted}
        try:
            derived = self.stage_scope("S5", state).get("scope") or []
        except (StateConflict, ValueError, OSError):
            derived = []
        written = self._written_windows(state, derived or list(state.get("scope") or []))     # not derived: the approved cases
        hit = [(number, window) for number, window in enumerate(written, 1) if want & set(window["scope"])]
        spans = [f"window {number}: " + ", ".join(sorted(want & set(window["scope"]))) for number, window in hit]
        members = {member for _, window in hit for member in window["members"]}
        # Only the author's records form chains; a record of any other role (the critic of a window) is the parent by its own scope.
        meets = [d for d in prior if (str(d.get("id")) in members if d.get("role") == "qa-automator"
                                      else {str(case) for case in d.get("scope") or []} & want)]
        return (meets[-1] if meets else None), bool(meets) and len(hit) <= 1, spans

    @staticmethod
    def _rework_mode(stage):
        """`"resume"` or `"fresh"`: how a rework of `stage` reaches its role (the stage's `rework_mode` in `references/stages.json`;
        `resume` = the same agent gets the package, `fresh` = a new agent does). THE one seam of this reading in the controller
        (AR-13), and a call to THE reader (`contract.rework_mode`, SC1-1 part B): no parsing of `stages.json` here. The reader
        answers `fresh` for a stage the table does not name, a stage with no field and a table that cannot be used; a field that
        is neither word raises its `ValueError`, which `build_rework_request` reads as `fresh` (a typo is no reason to resume
        an agent, and the fresh launch's door, `bind`, stays alive)."""
        import contract
        return contract.rework_mode(stage)

    @staticmethod
    def _rerun_stamp(state, stage, role, wanted):
        """What a person's-words rework of a COMPLETED stage makes run again, or {} (F6, I3).

        `stages`: the completed stages after it, up to S8. `reviews`: the accepted dispatches of
        this stage by its closing role (not the reworked one) over the reworked cases - the
        review of work that no longer stands. `decisions`: the approved gate decisions after it
        (gate A when the stage is S4 or before, gate B up to S8). Empty on every list is no
        stamp at all: the rework then changes nothing but itself.

        A stage that is `pending` stamps too when an earlier STAMPED rework of it was accepted (C1-4b,
        t-679 queue (d)): a second person's rework of another window of the same stage, while the first
        one's re-run is still due. Its `reviews` are the closing-role dispatches still `accepted` over
        THIS rework's cases (the staled ones are not named again), so the window the first stamp did
        not reach is set aside now and not left to approve work that no longer stands (I3). A pending
        stage that no stamped rework reopened (an in-stage round) stamps nothing, as before."""
        status = (state["stages"].get(stage) or {}).get("status")
        if status == "pending":
            if not any(d.get("stage") == stage and d.get("status") == "accepted" and isinstance(d.get("rerun_after"), dict)
                       for d in state["dispatches"].values()):
                return {}
        elif status != "completed":
            return {}
        number = int(stage[1:])
        stamp = {
            "stages": [name for name in (f"S{i}" for i in range(number + 1, 9))
                       if (state["stages"].get(name) or {}).get("status") == "completed"],
            "reviews": [_dispatch_ident(d, name) for name, d in state["dispatches"].items()
                        if Controller._is_review_of(d, stage, role) and set(d.get("scope") or []) & set(wanted)],
            "decisions": [_dispatch_ident(d, name) for name, d in state["decisions"].items()
                          if Controller._is_decision_after(d, number)]}
        return stamp if any(stamp.values()) else {}

    @staticmethod
    def _is_review_of(dispatch, stage, role):
        """An accepted dispatch of `stage` by its closing role, which is not the reworked `role`:
        the review of work that no longer stands (the one predicate of the stamp and its validator)."""
        from contract import stage_closes_with
        # The S5 plan critic's review is of the PLAN, not of a window's code: a person's-words rework of a window never stales
        # it (the plan is redone by its own door, `--purpose s5_plan`; SC1-14 B1a, E32).
        return (dispatch.get("stage") == stage and dispatch.get("status") == "accepted"
                and s5_part_of(dispatch) != "plan"
                and dispatch.get("role") != role and stage_closes_with(stage, str(dispatch.get("role") or "")))

    @staticmethod
    def _is_decision_after(decision, number):
        """An approved gate decision a rework of stage S<number> sets aside: gate A when the stage
        is S4 or before, gate B up to S8 (the one predicate of the stamp and its validator)."""
        return decision.get("status") == "approved" and (
            (decision.get("gate") == "A" and number <= 4) or (decision.get("gate") == "B" and number <= 8))

    @staticmethod
    def _validate_rerun_after(p, state, number):
        """A `rerun_after` the controller did not build is refused whole, naming the field; nothing
        is written. It may lower only stages AFTER the reworked one, stale only the accepted
        dispatches of the reworked stage's closing role (never the reworked role's own), stale only
        the approved gate decisions `_rerun_stamp` would name, and ride only on a rework request."""
        # K1 (C3-11): every defect of the stamp in one refusal (all the call's fault, `ValueError`). What reads
        # the stamp as an object runs only when it is one; what reads a list runs only for a list of ids.
        stamp = p["rerun_after"]
        problems = []
        shaped = isinstance(stamp, dict) and not set(stamp) - {"stages", "reviews", "decisions"}
        if not shaped:
            problems.append((ValueError, "rerun_after must be an object with the lists stages, reviews, decisions "
                                         "only; build it with `--operation rework --words-file`, never by hand"))
        if not p.get("rework_of"):
            problems.append((ValueError, "rerun_after belongs to a rework request, which names the dispatch it reworks "
                                         "in `rework_of`; build it with `--operation rework --words-file`"))
        if not shaped:   # FR-59: the checks that did not run say so (`_noted`), they never read as a pass
            Controller._raise_all(Controller._noted(
                problems, "(the checks of the stages, reviews and decisions lists did not run: they read the "
                          "stamp as an object with those lists)"))
        listed = set()
        for field in ("stages", "reviews", "decisions"):
            ids = stamp.get(field, [])
            if not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids):
                problems.append((ValueError, f"rerun_after.{field} must be a list of ids"))
            else:
                listed.add(field)
        for name in (stamp.get("stages", []) if "stages" in listed else []):
            if name not in {f"S{i}" for i in range(number + 1, 9)}:
                problems.append((ValueError, f"rerun_after.stages must be a stage after {p['stage']}, up to S8 "
                                             f"(it can run again after this rework); got {name!r}"))
        for did in (stamp.get("reviews", []) if "reviews" in listed else []):
            if not Controller._is_review_of(state["dispatches"].get(did) or {}, p["stage"], p["role"]):
                problems.append((ValueError, f"rerun_after.reviews must be an accepted dispatch of {p['stage']} by its "
                                             f"closing role, not by {p['role']} (the role being reworked); got {did!r}"))
        for did in (stamp.get("decisions", []) if "decisions" in listed else []):
            if not Controller._is_decision_after(state["decisions"].get(did) or {}, number):
                problems.append((ValueError, f"rerun_after.decisions must be an approved gate decision a rework of "
                                             f"{p['stage']} sets aside (gate A only when the stage is S4 or before, "
                                             f"gate B up to S8); got {did!r}"))
        if len(listed) < 3:   # the member checks of a field that is no list of ids did not run (FR-59)
            problems = Controller._noted(problems, "(the checks of the members of " + ", ".join(
                f"rerun_after.{field}" for field in ("stages", "reviews", "decisions") if field not in listed)
                + " did not run: they read a list of ids)")
        Controller._raise_all(problems)

    @staticmethod
    def _cases_by_disposition(mapping, dispositions):
        """`{"automate": [cases], "manual-agent": [cases]}`, each in case order: THE one reading of the S5 scope from the plan rows
        (`stage_scope`, `s5_windows_for` with no scope given and `s5_plan.window_slice` read it; AR-13, SC1-14 FJ fix M2)."""
        groups = {"automate": [], "manual-agent": []}
        for case, row in sorted(mapping.items()):
            if dispositions.get(row) in groups:
                groups[dispositions[row]].append(case)
        return groups

    def stage_scope(self, stage, state=None, execution_kind=None):
        """The scope S5/S6 must cover, computed from the approved plan. Read-only, no event.

        S5 is every approved case whose plan row is disposed `automate`. S6 adds the
        `manual-agent` rows, because it also re-runs automated instances whose evidence went
        stale; a `qa-runner` packet that already declares its `execution_kind` gets exactly
        the half it will execute. `manual-human` is nobody's dispatch and appears in neither.
        """
        state = self.state() if state is None else state
        if stage not in DERIVED_SCOPE_STAGES:
            given = list(state.get("scope") or [])
            return {"stage": stage, "scope": given, "derived": False, "windows": [],
                    "instances": self.scope_instances(given),
                    "reason": "only S5 and S6 scope follows from plan dispositions"}
        try:
            mapping, dispositions, basis = self._case_rows(state)
        except (StateConflict, ValueError) as exc:
            return {"stage": stage, "scope": [], "derived": False, "instances": {},
                    "windows": [], "reason": str(exc)}
        # A plan authored before 0.7.5 carries no disposition on its rows. Nothing is derived from it, and this function refuses
        # nothing because of it. An S5 that already has a live window keeps the earlier form (`s5_plan.mode`, rule 2); the FIRST
        # window of an S5 with no record, on a desktop process, meets the plan order (E21 rule 3, B1b) and is refused with the
        # door `plan before windows` - an underived scope cannot be planned (`s5_plan.init` refuses it).
        if not any(dispositions.values()):
            return {"stage": stage, "scope": [], "derived": False, "instances": {},
                    "windows": [],
                    "reason": "plan rows declare no disposition; the approved scope stands as given"}
        groups = self._cases_by_disposition(mapping, dispositions)
        if stage == "S5" or execution_kind == "automation":
            scope = list(groups["automate"])
        elif execution_kind == "manual":
            scope = list(groups["manual-agent"])
        else:
            scope = sorted(set(groups["automate"]) | set(groups["manual-agent"]))
        # The cases of a profile the person took over. S5 keeps them — the automator writes
        # the tests and the critic reviews them statically — and S6 does not: the runner
        # would have nothing to launch them with (TP2-2536).
        handed = self._handed_cases()
        if stage == "S6":
            scope = [case for case in scope if case not in handed]
        windows, cut = self._scope_windows(stage, scope, mapping, state)
        result = {"stage": stage, "execution_kind": execution_kind, "scope": scope,
                  "by_disposition": groups, "derived": True, "basis": basis,
                  "instances": self.scope_instances(scope),
                  "windows": windows,
                  "unmapped_scope": [case for case in (state.get("scope") or [])
                                     if str(case) not in mapping]}
        if cut is not None:     # only an S5 on the plan form with a plan on disk or a written window (SC1-14 FJ-B); else the key is absent
            result["window_cut"] = cut
        if handed:
            result["handed_to_person"] = {case: handed[case] for case in sorted(handed)}
            for window in result["windows"]:
                marked = [case for case in window["scope"] if case in handed]
                if marked:
                    window["handed"] = True
                    window["handed_cases"] = marked
        return result

    @staticmethod
    def automation_half_refusal(problems) -> str:
        """The ONE text a refused automated runner packet carries (`prepare`, `validate`, `story_step.py start`): the half's
        membership sentences as one compound answer, like the manual block's (RH1-10, DC1-15)."""
        from detector_verdict import compound
        return compound(problems, prefix="automated runner packet must name only cases of the automated half of the approved plan:")

    def _unreadable_plan_problems(self, state, subject, stage="S6") -> list:
        """`[]` when the plan can be read, or when the person's word is recorded (`S6 half membership: unreadable` at S6,
        `S5 scope: unreadable` at S5); otherwise ONE sentence saying the plan could not be read to judge `subject`, with its door.
        The unknown is never a pass (AR-28, FR-59): the S6 half-membership check and the empty-scope check of `validate`
        (both stages) share this one road (q3)."""
        block = "S5 scope: unreadable" if stage == "S5" else "S6 half membership: unreadable"
        try:
            self._case_rows(state)
        except (StateConflict, ValueError) as exc:
            why = " ".join(str(exc).split())
            text = (f"the plan could not be read to judge {subject} ({why}) - repair the "
                    f"plan (S3 rework) or record the person's word (`waiver.py --stage {stage} --block \"{block}\"`)")
            return self._passed_by_person(stage, [text])[0]
        return []

    def _half_membership_problems(self, stage, state, ids, kind) -> list:
        """The sentences for the cases of an S6 runner packet of half `kind` ("manual" / "automation") the approved plan does not give
        to that half (FB-9 R1b for the manual half; RH1-10, DC1-15 for the automation half), one per cause, each with its door.
        `[]` when the packet is fine, when `ids` is not a list (the caller's own check speaks), when it names no case, or when the
        plan is READABLE and declares no dispositions (the DECLARED skip: the approved-scope check of `validate` still runs).
        THE one membership check (AR-15): `prepare`, `validate`, `build_rework_request` and `story_step.py start` call it for both
        halves, so no road registers a packet over a case of the other half, a handed case, or nobody's case.
        Runs only for S6 (the only stage with two halves). Error direction: a refusal with a door; an id spelt differently from
        the plan's is refused (cause 3), never passed (B-E8, B-E13). A plan that cannot be read (missing or unparsable) is an
        UNKNOWN, never a pass (AR-28, FR-59): one sentence with the person's-word door `S6 half membership: unreadable`."""
        if stage != "S6" or kind not in ("manual", "automation") or not isinstance(ids, list):
            return []
        from detector_verdict import named
        wanted = list(dict.fromkeys(case for case in ids if isinstance(case, str) and case))
        if not wanted:
            return []
        unreadable = self._unreadable_plan_problems(state, f"which half {named(wanted, SCOPE_SHOWN)} belong to")
        if unreadable:
            return unreadable
        derived = self.stage_scope("S6", state)
        if not derived.get("derived"):
            return []
        groups = derived.get("by_disposition") or {}
        automate, manual = set(groups.get("automate") or []), set(groups.get("manual-agent") or [])
        handed = set(derived.get("handed_to_person") or {})
        # ONE cause partition for both halves (AR-13, RH1-10 q2). A HANDED case is judged handed FIRST (m1): `stage_scope` takes it
        # out of both halves, so it belongs to no runner whatever its row says, and the door of its refusal must not lead to the
        # other half's refusal of the same case (FR-2). Sentences keep the order: the other half's, handed, nobody's.
        own, other = (automate, manual) if kind == "automation" else (manual, automate)
        by_cause = [[case for case in wanted if case not in handed and case in other],
                    [case for case in wanted if case in handed],
                    [case for case in wanted if case not in handed and case not in other and case not in own]]
        return [text.format(shown=named(cases, SCOPE_SHOWN), cap=MANUAL_BLOCK_CASES)
                for text, cases in zip(_HALF_CAUSE_TEXTS[kind], by_cause) if cases]

    def _handed_cases(self) -> dict:
        """case id -> the profile the person runs it under, from their recorded word.

        The decision lives where every block a person's word passes lives — `stage_overrides[]`
        written by `waiver.py` — and the mapping from a case to a profile is the same one the
        gate rehearsal keyed its question on, so the answer covers exactly what was asked."""
        try:
            import contract
            from gate_preflight import s5_profiles
            pipeline = json.loads((self.store.root / "pipeline.json").read_text(encoding="utf-8-sig"))
            handed = contract.handed_profiles(pipeline)
            if not handed:
                return {}
            project = self._project_root()
            if project is None:
                return {}   # no project, no word recorded there
            config = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
            out = {}
            for profile_id, entry in s5_profiles(config, self.store.root).items():
                if profile_id in handed:
                    out.update({case: profile_id for case in entry.get("cases") or []})
            return out
        except Exception:
            return {}  # a scope that cannot read the decision hands nothing over, silently

    def _dispatch_setting(self, name):
        """`config.dispatch.<name>` as a non-negative int, or the shipped default.

        Read from the project's own file next to this task, the way `_project_root` finds
        it; no project, an absent, unreadable or nonsensical value is the default, never a refusal."""
        default = DISPATCH_DEFAULTS[name]
        project = self._project_root()
        if project is None:
            return default      # `except` below does not catch the TypeError of `None / "qa-factory"`
        try:
            config = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
            value = (config.get("dispatch") or {}).get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return default
            return value
        except (OSError, ValueError, AttributeError):
            return default

    def _s5_window_cases(self):
        """How many non-UI cases one S5 window takes: `config.execution.s5_window_cases`
        when the project set it (the driver experiment runs windows of 8 - one window per
        area, its repair through `--resume` of the same dispatch), else today's
        `dispatch.api_window_cases`. UI rows keep their own limit either way: a UI window
        of six cost 130-178 tool calls on TP1-15045, and nothing here reopens that."""
        project = self._project_root()
        try:
            if project is not None:     # none: the `dispatch` default below (a TypeError would not be caught here)
                config = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8-sig"))
                value = (config.get("execution") or {}).get("s5_window_cases")
                if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                    return value
        except (OSError, ValueError, AttributeError):
            pass
        return self._dispatch_setting("api_window_cases") or 1

    def _read_first(self, stage):
        """The S5 notes files that exist, task-relative: the old single file first, then every per-dispatch file in name order
        (TR3-15). A folder that cannot be listed adds nothing (the old file still stands); other stages: []."""
        if stage != "S5":
            return []
        found = [S5_NOTES] if (self.store.root / S5_NOTES).is_file() else []
        try:
            found += [f"{S5_NOTES_DIR}/{p.name}" for p in sorted((self.store.root / S5_NOTES_DIR).glob("*.md"), key=lambda p: p.name)
                      if p.is_file()]
        except OSError:
            pass
        return found

    def _window_stand_signal(self, state, dispatch):
        """The `stand_signal` of the latest run summary of this window, or None.

        `run_suite.py` stores what `stand_health.observe` said in the run summary under
        `evidence/runs/*/`. A summary names no dispatch, so "of this window" is "written since
        the window's first dispatch was journalled" — dispatches are sequential, so nothing
        else ran in between. A window nobody has been dispatched on yet has no runs of its own
        and therefore no signal, whatever an earlier window left behind."""
        try:
            key = window_key(dispatch)
            starts = self._dispatch_starts()
            opened = [starts.get(str(d.get("id"))) for d in (state.get("dispatches") or {}).values()
                      if isinstance(d, dict) and window_key(d) == key]
            opened = [value for value in opened if isinstance(value, (int, float))]
            if not opened:
                return None
            runs = [path for path in (self.store.root / "evidence" / "runs").glob("*/*.json")
                    if path.is_file() and path.stat().st_mtime >= min(opened)]
            for path in sorted(runs, key=lambda item: item.stat().st_mtime, reverse=True):
                summary = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(summary, dict) or "exit_code" not in summary:
                    continue  # a request or a results file beside the summaries
                signal = summary.get("stand_signal")
                if not isinstance(signal, dict) or not signal:
                    return None
                return {"summary": path.relative_to(self.store.root).as_posix(),
                        "reason": str(signal.get("reason") or signal.get("signal") or ""),
                        "sentence": str(signal.get("sentence") or "")}
        except (OSError, ValueError, TypeError, KeyError):
            return None
        return None

    def _stamp_dispatch(self, request, state):
        """What the controller knows about a dispatch and the orchestrator should not retype.

        `read_first` — the story's own S5 notes, once a window has written them. The receipt
        is what `inject_context.py` hands the role as its task packet, so a pointer stamped
        here reaches the role whatever the prompt says.
        `repair_cause: environment` — when the window's latest run carries a `stand_signal`
        and nobody named a cause. Six of six UI cases failed with one line on TP1-15045
        and the rounds spent proving the tests innocent were charged to the tests.
        A replay of a committed dispatch gets the stamps it was committed with: the journal
        compares payloads, and the disk may have moved since."""
        try:
            existing = (state.get("dispatches") or {}).get(request.get("id"))
            if isinstance(existing, dict):
                for key in ("repair_cause", "repair_cause_source", "read_first"):
                    if key in existing and key not in request:
                        request[key] = copy.deepcopy(existing[key])
                return
            if "read_first" not in request and self._read_first(request.get("stage")):
                request["read_first"] = self._read_first(request.get("stage"))
            # A continuation resumes the work its parent was opened for, with the cause that
            # round carried: it is not classified again from whatever the stand says today.
            # Only a packet that names a dispatch THAT EXISTS gets this - a made-up
            # `relaunch_of` is a new dispatch to this stamp (and `validate` refuses it).
            continues = bool(request.get("parent_retry")
                             or str(request.get("relaunch_of") or "") in (state.get("dispatches") or {}))
            if (request.get("repair_cause") is None and not continues
                    and request.get("role") in REPAIR_LOOP_ROLES):
                signal = self._window_stand_signal(state, request)
                if signal:
                    request["repair_cause"] = "environment"
                    request["repair_cause_source"] = "stand_signal:" + signal["summary"]
        except (OSError, ValueError, TypeError, AttributeError):
            return  # a stamp is a courtesy; the dispatch itself is validated below

    def _is_ui_case(self, mapping):
        """`case -> True | False | None`: is the case UI by its S3 row. "UI" is the plan row's `level == "e2e-ui"`
        (`contract.PLAN_LEVELS`), reached through the case's own `plan_row` — the binding `_case_rows` already made. It is the one
        field in the plan that names the execution surface; a test name or an area never did (the dashboard once filed component
        tests under UI by the substring "ui"). `None` is UNKNOWN: the case has no row, or the row's level is no word of
        `contract.PLAN_LEVELS`; a plan that cannot be read makes every case unknown. `None` is falsy, so the cut by cases
        (`split_windows`) reads it as "not UI", exactly as before; `s5_plan.case_groups` tells it from `False` (FR-59, AR-13: the
        S3 level is read here and nowhere else)."""
        import contract
        try:
            document = self._plan_document()
            rows = document.get("rows") if isinstance(document, dict) else document
            levels = {str(row.get("id")): str(row.get("level") or "")
                      for row in rows or [] if isinstance(row, dict)}
        except (StateConflict, ValueError, AttributeError):
            levels = {}

        def is_ui(case):
            level = levels.get(mapping.get(case))
            return None if level not in contract.PLAN_LEVELS else level == "e2e-ui"
        return is_ui

    def _scope_windows(self, stage, scope, mapping, state):
        """`(windows, cut)`: the stage's scope cut into dispatch windows, with what each window already has: the accepted author
        and reviewer dispatch that covered it. `cut` is None except for an S5 on the plan form (SC1-14 FJ-B).

        The cut by cases (`split_windows`) is the cut of S6, of `legacy` S5 and of an S5 with no plan file and no written window.
        An S5 on the plan form (`s5_plan.mode`) is cut by the groups of the plan, after the review, and keeps the windows its
        author has written (`s5_windows_for`); that branch comes BEFORE the `accepted_by` loop and leaves the plan filter of
        that loop as it was (B1a): legacy and S6 windows are what they were, byte for byte. A plan or a state that cannot be
        read, or any failure of the plan's cut, falls back to the cut by cases and says why in `cut["why"]` (AR-28), never raises."""
        windows, cut = None, None
        if stage == "S5" and scope:
            import s5_plan as SP
            try:
                if SP.mode(self.store.root, state, self._run_mode())[0] == SP.PLANNED:
                    windows, cut = self.s5_windows_for(SP.load(self.store.root), state, scope, mapping)
            except Exception as exc:        # a plan or a history that cannot be read: the cut by cases, with the reason
                windows, cut = None, {"grown": [], "why": f"the windows are cut by cases, the plan cut failed: {exc}"}
        if windows is None:
            windows = split_windows(list(scope), self._is_ui_case(mapping),
                                    self._dispatch_setting("ui_window_cases") or 1, self._s5_window_cases())
        self._mark_accepted_by(state, stage, windows)
        return windows, cut

    @staticmethod
    def _mark_accepted_by(state, stage, windows):
        """Sets `accepted_by` on every window: role -> the accepted dispatch of `stage` whose scope holds the whole window. THE one
        reader (`_scope_windows` and `_planned_cut`).

        The accepted S5 PLAN dispatch covers every case, so it would sit in `accepted_by` of EVERY window: the plan critic
        would close window 1 for the stage. A plan is not a window's author or reviewer (SC1-14 B1a, E29-E30)."""
        accepted = [d for d in (state.get("dispatches") or {}).values()
                    if isinstance(d, dict) and d.get("stage") == stage
                    and d.get("status") == "accepted" and s5_part_of(d) != "plan"]
        for window in windows:
            wanted = set(window["scope"])
            window["accepted_by"] = {
                str(d.get("role")): str(d.get("id")) for d in accepted
                if wanted.issubset({str(case) for case in d.get("scope") or []})}

    def _written_windows(self, state, scope):
        """`[{"root": id, "members": [id...], "scope": [cases]}]`: the S5 windows already WRITTEN, one per chain of the author
        (spec t-1314 section 2 item 5), numbered by the order of their roots. A window is the chain, not a scope: every record of
        `qa-automator` in S5 that is not the plan is joined to the record it continues - `parent_retry`, `relaunch_of` or
        `rework_of`, the first that names a record of this set - and the root of a chain is the record that continues none.
        A chain is LIVE when any member is not `DISCOUNTED`; a record the critic wrote never makes a window.
        The cases of `scope` are given to chains in two passes, so a rework that touches another window's cases does not take
        them: first the scope of the ROOT of every live chain, in journal order (a case an earlier root took is not the later
        one's), then the scope of the other live members, in journal order, for the cases still free. A case outside `scope`
        drops out; a chain left with no case is no window. Reads the state as it is and never raises on a record it cannot
        read: the error direction is "the window is written" (its cases are not cut again), never a lost window."""
        wanted = {str(case) for case in scope or []}
        dispatches = state.get("dispatches") if isinstance(state, dict) else None
        records = {_dispatch_ident(d, name): d for name, d in (dispatches.items() if isinstance(dispatches, dict) else ())
                   if isinstance(d, dict) and d.get("stage") == "S5" and d.get("role") == "qa-automator"
                   and s5_part_of(d) != "plan"}
        order = list(records)
        root_of, chains = {}, {}
        for identifier in order:
            root, seen = identifier, {identifier}
            while True:
                named = next((str(records[root].get(key)) for key in ("parent_retry", "relaunch_of", "rework_of")
                              if str(records[root].get(key) or "") in records), None)
                if named is None or named in seen:
                    break
                root = named
                seen.add(root)
            root_of[identifier] = root
            chains.setdefault(root, []).append(identifier)
        roots = sorted(chains, key=order.index)

        def cases_of(identifier):
            value = records[identifier].get("scope")
            return [str(case) for case in value] if isinstance(value, list) else []

        def live(identifier):
            return records[identifier].get("status") not in DISCOUNTED

        taken = {}
        for root in (r for r in roots if any(live(m) for m in chains[r])):
            for case in cases_of(root):
                if case in wanted:
                    taken.setdefault(case, root)
        for identifier in order:
            if root_of[identifier] != identifier and live(identifier):
                for case in cases_of(identifier):
                    if case in wanted:
                        taken.setdefault(case, root_of[identifier])
        out = []
        for root in roots:
            own = [case for case in dict.fromkeys(str(c) for c in scope or []) if taken.get(case) == root]
            if own:
                out.append({"root": root, "members": list(chains[root]), "scope": own})
        return out

    def s5_windows_for(self, plan, state=None, scope=None, mapping=None, written=None):
        """`(windows, cut)`: the S5 windows of a story on the plan form (spec t-1314 section 2 items 3-8), THE one cut (AR-13).

        The windows already written come first, numbered 1..k, each the chain of its author (`_written_windows`) and never cut
        again. A free case tied by a test of the plan to a written window joins it - the EARLIER window when it is tied to two -
        and the window lists it in `grown` until the author's chain has been sent back over it (a case the chain covers is part of
        the window and no longer free). What no written window touches is cut by the groups of the plan, the cases one test covers
        being one window (`pack_windows`, numbered from k+1); a group over the cap is one window with `over_cap: true, cap: M`,
        and so is a written window that holds more than its cap. `cut` is `{"grown": [numbers of the grown windows], "why": text}`,
        or None when there is no plan and no written window: the cut is then the cut by cases and S5 has not begun to be planned.
        `scope` and `mapping` are the stage scope's (case -> plan row); None reads them as `stage_scope` does. `written` is
        `_written_windows(state, scope)` when the caller already has it (one validate call reads the chains once); None reads it.
        Writes nothing and raises on what it cannot read."""
        import s5_plan as SP
        state = self.state() if state is None else state
        if scope is None or mapping is None:
            found, dispositions, _basis = self._case_rows(state)
            if scope is None:
                scope = self._cases_by_disposition(found, dispositions)["automate"]
            mapping = found if mapping is None else mapping
        scope = list(dict.fromkeys(str(case) for case in scope))
        is_ui = self._is_ui_case(mapping)
        caps = {"ui": self._dispatch_setting("ui_window_cases") or 1, "other": self._s5_window_cases()}
        if written is None:
            written = self._written_windows(state, scope)
        taken = {case: number for number, window in enumerate(written, 1) for case in window["scope"]}
        grown, free = {}, []
        for group in SP.case_groups(plan, scope, is_ui):
            touched = sorted({taken[case] for case in group["cases"] if case in taken})
            if not touched:
                free.append(group)
                continue
            added = [case for case in group["cases"] if case not in taken]
            if added:
                grown.setdefault(touched[0], []).extend(added)
        windows = []
        for number, window in enumerate(written, 1):
            cases = window["scope"] + grown.get(number, [])
            surface = "ui" if any(g["surface"] == "ui" for g in SP.case_groups(plan, cases, is_ui)) else "other"
            entry = {"index": number, "surface": surface, "scope": cases}
            if number in grown:
                entry["grown"] = list(grown[number])
            if len(cases) > caps[surface]:
                entry.update(over_cap=True, cap=caps[surface])
            windows.append(entry)
        windows += pack_windows(free, caps["ui"], caps["other"], start=len(written) + 1)
        if not scope or (plan is None and not written):
            return windows, None        # nothing planned and nothing written: a plan-less cut is the cut by cases (groups of one)
        return windows, {"grown": sorted(grown), "why": f"the windows follow the plan: {len(written)} written, "
                                                         f"{len(windows) - len(written)} cut from its groups"}

    def scope_instances(self, cases):
        """case id -> the test instances the manifest already has for it.

        The stage guard refused "selected instances exceed the active dispatch scope" five
        times on TP1-15045 because `stage-scope` handed out case ids and a run request
        names instances. Both halves of that conversation now come from the same place; a
        story with no manifest yet gets an empty list per case, never a refusal.
        """
        wanted = [str(case) for case in (cases or [])]
        found = {case: [] for case in wanted}
        if not wanted:
            return found
        try:
            import contract
            path = Path(contract.artifact(self.store.root, "automation-manifest.json"))
            if not path.is_file():
                return found
            manifest = contract.load_json(path)
            # the one definition of "one test"; absent on an older install, where the
            # manifest's own case links are the only mapping.
            case_of = getattr(contract, "instance_case", None)
            manifest_tests = contract.manifest_tests
            manifest_test_links = contract.manifest_test_links
            test_instance_id = contract.test_instance_id
            for entry in manifest_tests(manifest):
                identifier = test_instance_id(entry)
                if not identifier:
                    continue
                cases_of_entry = list(manifest_test_links(entry))
                if not cases_of_entry and case_of:
                    cases_of_entry = [case_of(identifier)]
                for case in cases_of_entry:
                    if case in found and identifier not in found[case]:
                        found[case].append(identifier)
        except Exception:
            return {case: [] for case in wanted}
        return {case: sorted(ids) for case, ids in found.items()}

    def _s6_completion_problems(self, dispatch, state):
        """The half of S6 nobody ran, asked before the stage closes.

        S6 is two packets of one stage: the automated instances (`execution_kind:
        automation`) and the manual-agent cases (`execution_kind: manual`), both derived by
        `stage_scope`. On TP1-13797 the automation packet (TC-001..006, 008) was accepted
        with `stage_complete` and S6 closed with TC-007, the manual-agent case of the same
        derived scope, never dispatched; the orchestrator then reworked it by hand. The rule
        is the S5 one: the stage completes when its derived scope is covered by accepted
        dispatches — this one included — and a missing half is named, never assumed run.
        """
        try:
            derived = self.stage_scope("S6", state)
        except Exception:
            return []
        if not derived.get("derived"):
            return []
        covered = {str(case) for case in dispatch.get("scope") or []}
        for other in (state.get("dispatches") or {}).values():
            if other.get("stage") == "S6" and other.get("status") == "accepted":
                covered.update(str(case) for case in other.get("scope") or [])
        missing = [str(case) for case in derived.get("scope") or [] if str(case) not in covered]
        if not missing:
            return []
        manual_cases = {str(case) for case in (derived.get("by_disposition") or {}).get("manual-agent") or []}
        manual = [case for case in missing if case in manual_cases]
        automated = [case for case in missing if case not in manual_cases]
        problems = []
        if manual:
            problems.append("S6 derived scope: manual-agent case " + ", ".join(manual)
                            + " has no accepted S6 dispatch (a qa-runner packet with "
                              "`execution_kind: manual`)")
        if automated:
            problems.append("S6 derived scope: " + ", ".join(automated)
                            + " has no accepted S6 dispatch (a qa-runner packet with "
                              "`execution_kind: automation`)")
        return problems

    # The `unresolved[]` reasons that mean "no instance can exist here": not a stand to
    # repair, not an implementation to wait for — nothing to run, by the manifest's own word.
    NO_INSTANCE_REASONS = ("impossible", HANDED_OUTCOME)

    def _cases_without_instances(self):
        """scope key -> reason, for the manifest's `unresolved[]` rows whose reason says the
        case has no instance to list (`impossible`, `handed_to_person`). The keys are the ones a
        window may use for the row's cell (`contract.scope_keys`: the exact cell, plus each bare id
        of a compound one), so an area-keyed scope `speakers/TC-009` finds its row. A cell two rows
        share is read from the LATER row only when that row is ALSO a no-instance reason; a later row
        with any other reason is not read here, and the earlier one stands. A story with no manifest yet, or an unreadable one,
        answers nothing — never a refusal here."""
        try:
            import contract
            path = Path(contract.artifact(self.store.root, "automation-manifest.json"))
            if not path.is_file():
                return {}
            cfg = contract.case_config()
            out = {}
            for entry in contract.manifest_unresolved(contract.load_json(path)):
                reason = str(entry.get("reason") or "")
                if reason in self.NO_INSTANCE_REASONS:
                    for key in contract.scope_keys(entry.get("case"), cfg=cfg):
                        out[key] = reason
            return out
        except Exception:
            return {}

    @staticmethod
    def _oracle_hashes(rows):
        hashes = {}
        for row in rows:
            for obligation in row.get("coverage_obligations") or []:
                oid = obligation.get("obligation_id")
                if oid:
                    hashes[str(oid)] = content_hash({
                        "behavior": obligation.get("behavior"),
                        "requirement_refs": obligation.get("requirement_refs"),
                        "oracle_source_ref": obligation.get("oracle_source_ref"),
                        "oracle_status": obligation.get("oracle_status"),
                        "completion_condition": obligation.get("completion_condition"),
                    })
        return hashes

    @staticmethod
    def _plan_semantic_hash(document):
        # JSON canonicalization removes formatting/key-order noise but retains every plan field;
        # a caller cannot redefine semantics by submitting a friendly hash.
        return content_hash(document)

    @staticmethod
    def _coverage_contract_revisions(rows, allow_legacy=False):
        """New authored plans declare an observation-contract revision per row.

        A wholly omitted set is a legacy plan and remains readable until an explicit migration;
        a mixed set is never silently repaired because that would turn missing proof into green.
        """
        values = [row.get("coverage_contract_revision") for row in rows]
        if any(value is not None for value in values) and any(not value for value in values):
            raise StateConflict("COVERAGE_CONTRACT_REVISION_REQUIRED")
        if values and not any(values) and not allow_legacy:
            raise StateConflict("COVERAGE_CONTRACT_REVISION_REQUIRED")
        return sorted(set(str(value) for value in values if value))

    def _current_gate_a(self, state):
        approved = [d for d in state["decisions"].values()
                    if d.get("gate") == "A" and d.get("status") == "approved"
                    and d.get("source_revision") == state.get("source_revision")]
        return approved[-1] if approved else None

    def _validate_gate_a_content_current(self, state):
        decision = self._current_gate_a(state)
        if not decision:
            # t-893 F-6: with no decision there is nothing to compare the sources and the plan for drift, and the refusal says
            # so (`_noted`, FR-59) - their own refusals (`source_inputs`, `_plan_document`) are not read here
            self._raise_all(self._noted(
                [(StateConflict, "current Gate A decision required")],
                "(the sources and the plan were not checked for drift: drift is measured against this decision)"))
        # K1 (C3-11): the sources and the plan are two records that drift independently of one another, so
        # what each one's own judge refuses (`source_inputs`, `_plan_document`) is collected beside the drift.
        problems = []
        try:
            sources = self.source_inputs(state)
        except StateConflict as exc:
            sources = None
            problems.append((StateConflict, str(exc)))
        if sources and decision.get("source_inventory_hash") != sources["source_inventory_hash"]:
            problems.append((StateConflict, "Gate A sources changed; review affected requirements"))
        try:
            problems += self._plan_drift(decision, self._plan_document(), state)
        except StateConflict as exc:
            problems.append((StateConflict, str(exc)))
        self._raise_all(problems)

    def _plan_drift(self, decision, document, state):
        """The FIRST way the plan differs from what Gate A approved, as a one-item problem list, or [].

        Not a chain to collect: the semantic, oracle and coverage-contract hashes are all functions of the
        document, so each can differ only when the content hash already does - the later ones refine the
        first, they are not further defects."""
        if decision.get("plan_content_hash") != content_hash(document):
            return [(StateConflict, "Gate A plan content changed after approval; re-review affected scope")]
        if decision.get("plan_semantic_hash", decision.get("plan_content_hash")) != self._plan_semantic_hash(document):
            return [(StateConflict, "Gate A semantic plan content changed after approval")]
        rows = document.get("rows") if isinstance(document, dict) else document
        if not isinstance(rows, list) or decision.get("oracle_content_hashes") != self._oracle_hashes(rows):
            return [(StateConflict, "Gate A oracle content changed after approval")]
        if decision.get("coverage_contract_revisions", []) != self._coverage_contract_revisions(rows, state.get("plan_contract_mode") == "legacy"):
            return [(StateConflict, "Gate A coverage-contract revisions changed after approval")]
        return []

    def source_inputs(self, state=None):
        """Validate the canonical local source snapshot before handoff or approval."""
        state = self.state() if state is None else state
        path = self.store.root / "work/source-inventory.json"
        if not path.exists():
            if state.get("source_inventory_required"):
                raise StateConflict("source inventory required before completed discovery")
            return {}
        from source_inventory import load_inventory, validate_inventory, completeness, verify_inventory_files, class_kwargs
        inventory = load_inventory(path)
        errors = validate_inventory(inventory)
        integrity = verify_inventory_files(self.store.root, inventory)
        # A story whose S1 is already completed keeps the OLD meaning of an acceptance it recorded
        # (t-114 G3: nothing re-blocks at a later dispatch); one whose S1 is not completed - the S1
        # checkpoint itself, gate A's first read - is judged by the point rule. The kinds of gap the person answered
        # about (`work/gap-classes.json`, C2-9) are read here too, or a point they closed would block S1 again.
        summary = completeness(inventory, s1_closed=((state.get("stages") or {}).get("S1") or {}).get("status") == "completed",
                               **class_kwargs(self.store.root))
        if errors or not integrity["valid"] or summary["gate_blocked"]:
            raise StateConflict("sources pending/invalid: " + "; ".join(errors + integrity["errors"] or [str(summary)]))
        return {"source_inventory_hash": content_hash(inventory), "source_completeness": summary}

    def gate_inputs(self):
        """Return deterministic Gate-A bindings without writing state or invoking a role."""
        document = self._plan_document()
        rows = document.get("rows") if isinstance(document, dict) else document
        problems = []   # K1 (C3-11): the rows and the actions are two independent fields of the plan
        if not isinstance(rows, list):
            problems.append((ValueError, "structured test plan rows must be a list"))
        actions = document.get("lifecycle_actions", []) if isinstance(document, dict) else []
        if not isinstance(actions, list):
            problems.append((ValueError, "lifecycle_actions must be an array"))
        self._raise_all(problems)
        return {"plan_content_hash": content_hash(document),
                "plan_semantic_hash": self._plan_semantic_hash(document),
                "oracle_content_hashes": self._oracle_hashes(rows),
                "coverage_contract_revisions": self._coverage_contract_revisions(rows, self.state().get("plan_contract_mode") == "legacy"),
                "lifecycle_actions_hash": content_hash(actions), **self.source_inputs()}

    def _pipeline(self):
        """pipeline.json as it stands on disk, or {} — the reader of the closure facts."""
        try:
            data = json.loads((self.store.root / "pipeline.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _project_pipeline(self, state):
        """Write the controller's stages, gates and closure into the story's own file."""
        pipeline_path = self.store.root / "pipeline.json"
        pipeline = self._pipeline()
        if not state.get("source_revision"):
            return pipeline
        pipeline.setdefault("ticket", self._ticket())
        if "source_inventory_required" in state:
            pipeline["source_inventory_required"] = state["source_inventory_required"]
        stages = pipeline.setdefault("stages", {})
        # The id the host gave the agent that ran the stage: the agent of the LAST BIND of that
        # stage (`agent_bound_seq`, the position of the bind event the projection stamped), never
        # of the last dispatch CREATED - two dispatches of one stage (S8 scribe and reporter) can be
        # bound in the reverse of their creation order. A dispatch that carries an id but no stamp
        # (an imported record) ranks below any bound one and among its kind by creation order, as
        # before. `stage_done.py --agent-id` writes the same field and stays the route for a stage
        # no dispatch recorded; a state written before this field existed keeps whatever
        # pipeline.json already holds.
        agent_ids, ranks = {}, {}
        for d in state.get("dispatches", {}).values():
            agent = str(d.get("agent_id") or "").strip()
            if not (d.get("stage") and agent):
                continue
            rank = d.get("agent_bound_seq")
            rank = rank if isinstance(rank, int) and not isinstance(rank, bool) else 0
            if rank >= ranks.get(str(d["stage"]), -1):
                agent_ids[str(d["stage"])], ranks[str(d["stage"])] = agent, rank
        for name, stage in state["stages"].items():
            entry = stages.setdefault(name, {})
            entry.update(stage)
            if agent_ids.get(name):
                entry["agent_id"] = agent_ids[name]
            # `update` never removes, and a stage that was reworked and then closed again
            # would keep claiming it: the rework marks are rewritten, not accumulated.
            if not stage.get("rework"):
                for key in ("rework", "rework_status", "rework_reason"):
                    entry.pop(key, None)
            # The same for the marks of the run a stage WAS (a lowered stage, a stage closed
            # again by a real run): `rerun_after`, the code-only receipt, the later-work marks.
            for key in STAGE_RUN_MARKS:
                if key not in stage:
                    entry.pop(key, None)
            entry["status"] = {"completed": "done"}.get(stage["status"], stage["status"])
        for decision in state["decisions"].values():
            if decision.get("gate"):
                pipeline.setdefault("gates", {})[decision["gate"]] = dict(decision,
                    decision="approved" if decision["status"] == "approved" else decision["status"])
        latest = latest_gate_b(state)
        if latest is not None:      # the orders of gate B beside the decision: the produced statuses (AR-14, one writer)
            pipeline.setdefault("gates", {})["B"] = gate_b_record(state, latest)
        pipeline["controller_revision"] = state["revision"]
        # t-2181 PC-6: the hold beside the stages and gates (AR-14, the controller is its one writer). `contract.awaiting` reads it
        # from here for every reader that has the story's file and no controller state (the guard, the doctor, the archive); an
        # `arrive` removes the key, and `first_look_continue` stays a record until a new first look replaces it.
        if isinstance(state.get("awaiting"), dict):
            pipeline["awaiting"] = copy.deepcopy(state["awaiting"])
        else:
            pipeline.pop("awaiting", None)
        if isinstance(state.get("first_look_continue"), dict):
            pipeline["first_look_continue"] = copy.deepcopy(state["first_look_continue"])
        stamp_closure(pipeline, state)
        atomic_json(pipeline_path, pipeline)
        return pipeline

    def project(self, events):
        """The bounded projection, run UNDER the story writer lock: pipeline.json, next_action,
        the source fields, controller.json, checkpoint.json and `finalize_task.refresh` (which
        serialises the run-report and triage writers, so it stays in here). The dashboard is
        NOT rendered here: that is `refresh_derived`, which the store runs after the lock is
        released. A render of any length used to hold the lock and stall the lifecycle."""
        state = self._with_environment_jobs(projection(events))
        # pipeline.json is written FIRST, because `next_action` reads it back: whether this
        # story is closed is a fact of that file (`closed_at`), and a projection that
        # computed the answer before stamping it would answer `await_gate` on a story whose
        # gate B it had just recorded (TP2-2534).
        pipeline = self._project_pipeline(state)
        # A durable projection consumer can show the next controller action without a
        # host/model invocation.  Derive it from this event list to avoid recursive writes.
        state["next_action"] = self._next_action_for_state(state, pipeline)
        inventory_path = self.store.root / "work/source-inventory.json"
        if inventory_path.is_file():
            from source_inventory import load_inventory, completeness, verify_inventory_files, class_kwargs
            inventory = load_inventory(inventory_path)
            state["source_completeness"] = completeness(
                inventory, s1_closed=((state.get("stages") or {}).get("S1") or {}).get("status") == "completed",
                **class_kwargs(self.store.root))
            state["source_integrity"] = verify_inventory_files(self.store.root, inventory)
            state["source_gaps"] = [{"source_id": item.get("source_id"),
                                    "ref": item.get("canonical_ref"), "status": item.get("status"),
                                    "relevance": item.get("relevance"),
                                    "reason": item.get("exclusion_or_error")}
                                   for item in inventory.get("sources", [])
                                   if item.get("status") != "read" and item.get("status") != "excluded"]
        # The journal remains authoritative; these revision-bound files are atomically refreshed
        # after every accepted event so a resumed host never has to reconstruct progress by LLM.
        from session_handoff import continuation_packet
        state["durable_checkpoint"] = continuation_packet(state, reason="event_projection")
        atomic_json(self.store.root / "state" / "controller.json", state)
        atomic_json(self.store.root / "state" / "checkpoint.json", state["durable_checkpoint"])
        # Only refresh when evidence exists; pre-run stages must not manufacture runs.
        if (any((self.store.root / "work" / name).exists() for name in ("run-blocks", "manual-blocks"))
                or any(event["type"] == "code_only" and event["payload"].get("stage") in {"S6", "S7"}
                       for event in events)):
            from finalize_task import refresh
            refresh(self.store.root)

    def refresh_derived(self):
        """Refresh the dashboard — the view derived from the projection — AFTER the story writer
        lock is released (the store's `after_commit` step). It only reads controller.json and
        never commits to or recovers this store, so it cannot re-enter the lock it follows.

        The event is committed and controller.json is current by now, so a failure here is not
        a stale projection and never writes `projection-stale.json`. A file the factory does
        not own exclusively is the one tolerated failure: `recover` died with PermissionError
        on `state/telemetry/hook-*.aggregate.json` because a hook process of the same session
        held it — someone else's open handle on a latency aggregate is not a reason to lose a
        committed lifecycle fact. Retry briefly, then leave the dashboard for the next event and
        say so on disk. Anything else leaves the same marker and is refused out loud: the
        action is NOT to be repeated (it is committed), `--operation recover` refreshes.

        EVERYTHING in here, the import and the marker write of the tolerated branch included,
        ends as that one refusal. A raise outside it reached the store's generic after-commit
        wrapper, whose third text ("the step that follows it did not finish") the driver's
        `committed_event` row does not match, so a conductor `retry` repeated a committed action."""
        deferred = self.store.root / "state" / "dashboard-deferred.json"
        try:
            from dashboard_refresh import refresh_for_task
            result = retry_shared(lambda: refresh_for_task(self.store.root))
            # What the marker says ("could not be refreshed ... recover refreshes it") stops being
            # true only when the view IS current: `refresh_for_task` answers `current` for that
            # (a cached receipt returned unchanged too). `skipped` (QA_FACTORY_SKIP_DASHBOARD_
            # REFRESH), `not_configured` (no qa-factory/config.json above the task) and `pending`
            # (inputs changed while rendering, another writer active) mean the view was NOT
            # brought up to date, so the marker stays (FR-41). The success removes it the way
            # `projection-stale.json` goes; a marker that cannot be removed does not undo the
            # refresh that just worked.
            if isinstance(result, dict) and result.get("status") == "current":
                try:
                    deferred.unlink(missing_ok=True)
                except OSError:
                    pass
            return
        except PermissionError as exc:
            if shared_file(getattr(exc, "filename", "")):
                try:
                    atomic_json(deferred,
                                {"status": "deferred", "owner": "factory", "file": str(exc.filename),
                                 "reason": "telemetry file held by another process; the committed "
                                           "event is durable and the dashboard refreshes on the next one"})
                    return
                except Exception as marker_failure:
                    # the tolerated case needs its marker on disk (FR-41: a deferral nobody can
                    # see is a silent one); without it this is the refusal below, not a pass
                    failure = marker_failure
            else:
                failure = exc
        except Exception as exc:
            failure = exc
        what = f"{type(failure).__name__}: {failure}"
        recorded_in = "state/dashboard-deferred.json"
        try:
            atomic_json(deferred,
                        {"status": "deferred", "owner": "factory",
                         "file": str(getattr(failure, "filename", "") or ""), "error": what,
                         "reason": "the dashboard could not be refreshed after the event was "
                                   "committed; `controller.py --operation recover` refreshes it"})
        except Exception:
            # the refusal below carries the same facts, and says that nothing on disk does (t-434):
            # it used to claim the marker was recorded also when this write had just failed (FR-41)
            recorded_in = ""
        where = (f"(recorded in {recorded_in})" if recorded_in else
                 "(nothing on disk records that the view is stale: state/dashboard-deferred.json "
                 "could not be written either)")
        raise DerivedViewStale(
            f"event committed; derived view not refreshed ({what}); do not repeat the action; "
            f"`controller.py --task-root {self.store.root} --operation recover` refreshes it "
            f"{where}", recorded_in=recorded_in) from failure

    def _is_replay(self, request):
        """Does the store already hold an event under this request's `idempotency_key` (the key `event_store` answers a replay
        by)? No key, or a store that cannot be read, is no replay (the prelude then runs: its repair is guarded by the revision
        and the row's status, and the commit that follows meets the same unreadable store)."""
        key = request.get("idempotency_key")
        if not isinstance(key, str) or not key:
            return False
        try:
            return any(event.get("idempotency_key") == key for event in self.store.read())
        except Exception:
            return False

    def _holder_would_refuse(self, operation, request, current):
        """Would a `running` row of `current` REFUSE this holding operation (the only case in which `apply` may close a dead one)?
        `revise_plan`, `semantic_reopen` and `invalidate`: any running row. `dispatch` and `resume`: a running row that the S5 window
        clause (`_window_beside_running`) or its S6 twin (`_lane_beside_running`) - the same two calls `validate` and
        `_resume_problems` make - does not admit beside the request;
        a resume of an unknown id has no holder to blame (its own refusal stands). Error direction: when in doubt it says True (the
        repair is guarded by the revision and by the row's status, so a needless attempt costs a read, never a wrong write)."""
        dispatches = [d for d in (current.get("dispatches") or {}).values() if isinstance(d, dict)]
        running = [d for d in dispatches if d.get("status") == "running"]
        if not running:
            return False
        if operation == "dispatch":
            recorded = {_dispatch_ident(row, key) for key, row in (current.get("dispatches") or {}).items() if isinstance(row, dict)}
            if isinstance(request.get("id"), str) and request.get("id") in recorded and self._is_replay(request):
                # a TRUE replay - the id is recorded AND the store already holds an event under this request's idempotency key -
                # is answered by the store before `validate` (FR-45; or refused as a reuse of the key): no holder refuses it, and
                # the repair must not close the very row the replay names. A recorded id under a FRESH key is no replay: the
                # prelude runs as for any dispatch and `validate` refuses it ("resume existing dispatch")
                return False
            return not (self._window_beside_running(request, current, running)
                        or self._lane_beside_running(request, current, running))
        if operation == "resume":
            target = (current.get("dispatches") or {}).get(request.get("id")) if isinstance(request.get("id"), str) else None
            if not isinstance(target, dict):
                return False
            beside = [d for d in running if d is not target]
            return bool(beside) and not (self._window_beside_running(target, current, beside, flagged=False)
                                         or self._lane_beside_running(target, current, beside, flagged=False))
        return True

    def apply(self, operation, request):
        # A gate `decision` reads the gate A open items BEFORE the store lock is taken (M5, AR-12): the rehearsal starts subprocesses, so
        # it must not run inside `store.commit`'s callback; `validate` then reuses that read (`items_scope`). The call below re-enters
        # with the scope open, so the body runs once.
        if operation == "decision" and self._items_memo is None:
            with self.items_scope():
                self.open_gate_items(dict(request).get("gate"))
                return self.apply(operation, request)
        request = dict(request)
        respelled = False       # the dispatch scope was written in other keys than the request used (M-3)
        if operation != "initialize":
            current = self.state()
            lease = current.get("leases", {}).get("orchestrator")
            if lease and request.get("owner_session_id") != lease.get("owner_session_id"):
                raise StateConflict("controller mutation rejected: stale or missing orchestrator lease")
            if operation in HOLDING_OPS and self._holder_would_refuse(operation, request, current):
                # TR4-7 (AR-25, FR-59): a `running` row whose session is provably over is not work: it is RECORDED as a stop (the one
                # writer, `close_settled`: a `state_repair` event that says what proved it, the finding) BEFORE the refusals below read
                # the state, so it neither blocks nor stays `running`. Alive and unknown change nothing. B1: it runs only when a
                # running row would REFUSE this request (an admitted S5 window never touches its siblings), the repair is committed
                # only against the revision it read (another writer acted: nothing is written) and the state is read AGAIN either
                # way. The caller's `expected_revision` is never carried past a repair: a repair moves the revision, so the caller is
                # judged against the fresh one by the ordinary rule ("stale expected revision": it reads the state and sends again).
                self.close_settled(current, by=operation)
                current = self.state()
            if operation == "revise_plan":
                # the lease is checked HERE (CX2-17 C-2): the owner is not a fact of the plan - the projection does
                # `state.update(payload)` and a replay compares the payload (FR-45) - and `validate` refuses a field it does not
                # know, so the hand-written request that carries it is read once and the field goes (own copy)
                request.pop("owner_session_id", None)
            if operation == "dispatch":
                # t-329 (B-249): tokens resolve against THIS process's roots, a packet of another package
                # generation is refused, and the INPUT is never written back (FR-45): `request` is this call's own
                # copy and gets a new dict
                if "known_paths" in request:
                    request["known_paths"] = self._current_known_paths(request["known_paths"], current)
                # CX1-11 (M-3): the scope is RECORDED in the keys the approved scope holds, whatever the spelling
                # the request used, so every reader of a dispatch's scope (S6 coverage, invalidate, the window and
                # budget keys) sees one spelling. The same helper `validate` refuses by; own copy, a new list.
                # It runs BEFORE the stamp: `_stamp_dispatch` keys the windows by this scope (F-3).
                if isinstance(request.get("scope"), list) and request["scope"]:
                    canonical, refused = self._outside_approved(request["scope"], current.get("scope") or [])
                    if canonical + [member for member, _ in refused] != request["scope"]:
                        request["scope"] = canonical + [member for member, _ in refused]
                        respelled = True
                # the manual block's cases are read by the SAME map right behind it (CX2-17 C2): a bare `TC-3` two areas hold is
                # every one of its keys, and the block must stay inside the scope it now sits in. The block's limit is then
                # counted over the KEYS (a bare id of two areas is two cases for the person who runs them). A non-list or an
                # empty list is left for `validate`; a member the map cannot resolve stays as written for `validate` to refuse.
                if isinstance(request.get("manual_case_ids"), list) and request["manual_case_ids"]:
                    request["manual_case_ids"] = self._manual_keys(request["manual_case_ids"], current)
                self._stamp_dispatch(request, current)
            if (operation == "code_only" and isinstance(request.get("reason"), str) and request["reason"]
                    and isinstance(request.get("stage"), str) and request["stage"][1:].isdigit()):
                # TR1-9 (AR-27): a close that passes over a dispatch which is not work any more says so BY NAME in the stage's close
                # note, and TYPED in the event (`passed_over: [{id, label}]`, B3/B4): the projection sets those rows aside and the stage
                # entry keeps the names, which `report_facts` and the driver's finding read. Own copy; `validate` recomputes it.
                passed = code_close_facts(current, request["stage"], self._close_verdicts(current, request["stage"])).get("passed_over")
                request["passed_over"] = [{"id": ident, "label": label} for ident, label in passed or []]
                if passed and code_close_note(passed) not in request["reason"]:
                    request["reason"] = request["reason"] + code_close_note(passed)
            if operation == "await":
                # t-2181 PC-6: the sides of the record are what the ONE reader says now (`contract.story_sides`, AR-13), written
                # into the event so a replay of the journal gives the same record; a caller's own `sides` is never kept (for
                # `first_look_stop` too: "sides from the reader"). Own copy of the request, as the dispatch scope above.
                import contract
                request["sides"] = contract.story_sides(self._pipeline())
            if operation == "accept" and "stage_complete" not in request:
                # The last role of a stage closes it. Saying nothing used to mean "not
                # complete", so S4 stayed open after its critic was accepted and gate A
                # refused with a message nobody could act on (TP2-2553). An explicit
                # `false` is still honoured by the caller — and refused in `validate`, where
                # the flag is named.
                # an `id` that is not a string names nothing (a list is unhashable): `validate` refuses it by name (E4)
                dispatch = ((current.get("dispatches") or {}).get(request.get("id"))
                            if isinstance(request.get("id"), str) else None) or {}
                if self._closes_stage(dispatch, current):
                    request["stage_complete"] = True
        if "idempotency_key" not in request:
            # A bare KeyError reached the CLI as «the request is missing a required field» (R2, run 12586: the
            # scout and the conductor both hand-built an accept from the phase text). This one names the field,
            # the revision it goes with (an `initialize` has none yet) and the command that writes it whole.
            present = {} if operation == "initialize" else current
            revision_note = ("" if operation == "initialize" else
                             f" and `expected_revision` (now {present.get('revision')})")
            raise ValueError(f"the {operation} request requires an `idempotency_key` and has none. "
                             + apply_door(operation, self.store.root, str(request.get("id") or ""), present.get("dispatches"))
                             + f" A hand-written request carries `idempotency_key` (a key of your own for THIS content; "
                             f"repeat it only to repeat the same request){revision_note}.")
        key = request.pop("idempotency_key")
        revision = request.pop("expected_revision", None)
        if operation == "accept":
            revision = self._revision_past_own_return(request.get("id"), revision, current)
        if operation == "reconcile_dispatch" and revision is None:
            raise StateConflict("dispatch reconciliation requires current expected_revision")
        if operation == "handoff":
            request["_expected_revision"] = revision
        if operation == "initialize":
            request = self._import_legacy_pipeline(request)
            # A caller cannot self-attest a host capability.  Bundled runtime has no verified
            # fresh-context adapter, so all fresh tasks start with truthful manual fallback.
            request.pop("host_capabilities", None)
            request["host_capabilities"] = []
            # A story is `legacy` when it carries work the controller never saw — a stage
            # after S0, a running role, a gate. S0 alone is not that: `phases/s0.md` §9 closes
            # S0 with `stage_done.py` BEFORE `initialize`, so pipeline.json always holds a
            # closed S0 by now, and reading it as a legacy pipeline gave every fresh story
            # `plan_contract_mode: legacy` and coverage v1 (TP1-13797, 2026-09-24).
            legacy = self._imports_prior_work(request.get("legacy_import"))
            request.setdefault("coverage_contract_version", 1 if legacy else 2)
            request.setdefault("plan_contract_mode", "legacy" if legacy else "new")
        if operation == "coverage_migration":
            request.setdefault("to_version", 2)
        expansions = self._normalise_revise_scope(request) if operation == "revise_plan" else {}
        if operation == "dispatch":
            policy = request.pop("model_policy", None)
            if policy:
                # `policy["supported"]` used to raise a bare KeyError and the CLI printed
                # `{"error": "'supported'"}` — a message naming neither the field nor the
                # request it belongs to (TP1-15045, three rejected rework attempts).
                if not isinstance(policy, dict) or any(k not in policy for k in ("parent", "supported")):
                    raise ValueError("model_policy requires 'parent' (the orchestrator's own "
                                     "model/effort) and 'supported' (the host's verified map); "
                                     "'project' and 'task' overrides are optional. Omit "
                                     "model_policy entirely to inherit.")
                request["resolved_model"] = resolve_model(request["role"], policy["parent"],
                                                         policy.get("project", {}), policy.get("task", {}),
                                                         policy["supported"])
            else:
                request["resolved_model"] = {"model": "inherit", "effort": "inherit"}
        # Deferred, so the order is: commit, then `_after_commit` (the gate-A override marks and
        # the plan baseline, which the dashboard should already see), then the derived-view
        # refresh when the block ends. A refresh failure therefore never skips `_after_commit`
        # and never undoes the commit.
        try:
            with self.store.deferred_after_commit():
                receipt = self.store.commit(EVENT_KIND.get(operation, operation), request, key, revision,
                                            lambda events, p: self.validate(operation, p, projection(events)),
                                            self.project)
                self._after_commit(operation, request, key=key, revision=revision)
        except StateConflict as exc:
            committed = self._replayed_with_other_scope(exc, operation, request, current) if operation == "dispatch" else None
            if committed is None:
                fields = self._revise_key_fields(exc, operation)
                if fields is None:
                    raise
                # a hand-written key reused for another `revise_plan` (CX2-17, A6): built HERE, inside the raise, so the blocks
                # census sees it (F-1); the scope the key was COMMITTED with is read from that event, not from the state
                stored = next((event for event in reversed(self.store.read()) if event.get("type") == "revise_plan"
                               and event.get("idempotency_key") == exc.key), None)
                held = (stored or {}).get("payload", {}).get("scope")
                sent = request.get("scope") if isinstance(request.get("scope"), list) else [request.get("scope")]
                if "scope" in fields and isinstance(held, list):
                    raise IdempotencyKeyReused("idempotency key reused with a different scope: the key " + str(exc.key)
                                               + " was committed with scope [" + self._listed(str(m) for m in held)
                                               + "]; this request names [" + self._listed(str(m) for m in sent)
                                               + "]. A new request takes a key of its own and expected_revision "
                                               + str(self.state().get("revision")), key=exc.key, fields=exc.fields) from exc
                raise IdempotencyKeyReused("idempotency key reused with different " + ", ".join(fields) + ": the key "
                                           + str(exc.key) + " holds another request. A new request takes a key of its own "
                                           "and expected_revision " + str(self.state().get("revision")),
                                           key=exc.key, fields=exc.fields) from exc
            # N-2: built HERE, inside the raise, so the blocks census sees it (F-1)
            raise IdempotencyKeyReused("idempotency key reused with different inputs: dispatch " + str(request.get("id"))
                                       + self._other_scope_text(committed, request, respelled),
                                       key=exc.key, fields=exc.fields) from exc
        if expansions and isinstance(receipt, dict):
            # m-13: the receipt (the CLI's output, never the payload) lists the members written otherwise than spelt
            receipt = dict(receipt, scope_expansions=expansions)
        return receipt

    def _revision_past_own_return(self, dispatch_id, revision, current):
        """The `expected_revision` an `accept` is committed with.

        A role stops between the orchestrator's prepare and its accept, and the hook (or `next`,
        through `close_settled`) journals that stop: the revision moves although nothing about
        the dispatch, its evidence or the story's decisions has. The accept of that very
        dispatch then went "stale expected revision" and the orchestrator had to prepare it
        again (B-311, TP2-2406).

        The gap is forgiven only when it is exactly that: the dispatch is `returned_unaccepted`
        and EVERY event in (revision, now] is a return receipt of THIS dispatch. Anything else
        in the gap - another dispatch, a decision, a manifest patch, a release, a repair of
        another dispatch - is something the orchestrator has not seen, and the accept stays
        stale. Only the number changes here: `validate` still judges the accept on the events
        inside the lock, an event that lands after this read fails the commit's own check, and
        a repeated idempotency key is answered with the stored event before the number is
        looked at. No expected revision, a revision ahead of the journal, any other status and
        any other operation are not touched."""
        if (isinstance(revision, bool) or not isinstance(revision, int)
                or not isinstance(dispatch_id, str)):
            return revision
        if revision >= current.get("revision", 0):
            return revision
        events = self.store.read()
        now = len(events)
        if revision < 0 or revision >= now:
            return revision
        dispatch = (projection(events).get("dispatches") or {}).get(dispatch_id) or {}
        if dispatch.get("status") != RETURNED:
            return revision
        if all(self._is_return_receipt(event, dispatch_id) for event in events[revision:now]):
            return now
        return revision

    @staticmethod
    def _is_return_receipt(event, dispatch_id):
        """Is this journal event the record of the stop of exactly this dispatch?

        `returned` is the hook's own fact; `state_repair` is what `next`/`recover` write when
        liveness proves the stop. A repair with no fixes, or one with a fix for another
        dispatch or of another kind, is not this dispatch's receipt."""
        payload = event.get("payload") or {}
        if event.get("type") == "returned":
            return payload.get("dispatch_id") == dispatch_id
        if event.get("type") == "state_repair":
            fixes = payload.get("fixes")
            return bool(fixes) and all(
                isinstance(fix, dict) and fix.get("dispatch_id") == dispatch_id
                and fix.get("kind") == RETURNED for fix in fixes)
        return False

    def _current_known_paths(self, paths, state=None):
        """`paths` as a dispatch records them: resolved against this process's project and plugin, or refused when
        the packet was made for another package or names paths this machine does not have (`contract.
        known_paths_for_dispatch`). Not a dict, or absent: left to `validate`, which names it.

        The project is `_project_root()` (the marker above the story). When none is found and the packet depends
        on a project (`{project_root}` or an absolute `project_root`), the project is asked of the finder `prepare`
        uses, `project_for_task(story, hint=<state's recorded project_root>)` - a story kept outside its project's
        folder (E4) was given its `{project_root}` by `prepare` from that very project, and must resolve against it
        (t-622). When THAT finds none, its own refusal stands, with its `--project` door: this gate never says "the
        token has no root in this process" about a packet whose fault is a missing project, and never hands a
        project-dependent packet to a dispatch with no project. A packet that does not depend on a project passes
        as before."""
        if not isinstance(paths, dict):
            return paths
        import contract
        from runtime_paths import names_project, project_for_task
        project, plugin = self._project_root(), Path(__file__).resolve().parent.parent
        if project is None and names_project(paths):
            stored = (state or {}).get("known_paths")
            stored = stored if isinstance(stored, dict) else {}
            project = project_for_task(self.store.root, hint=stored.get("project_root") or stored.get("root"))

        def current():
            try:
                from runtime_paths import resolve_runtime
                runtime = resolve_runtime(self.store.root.resolve(), project)
                # the stamp, and what a tokenised packet's leftover absolute paths are recomputed from (t-304 Q6)
                return {"package_fingerprint": runtime["package_fingerprint"], "package_version": runtime["package_version"],
                        "repository_roots": runtime.get("repository_roots"), "entrypoints": runtime.get("entrypoints"),
                        "scripts_root": runtime.get("scripts_root")}
            except (OSError, ValueError, KeyError):
                return None          # unknown, not a mismatch (FR-41): a package that cannot be read refuses nothing here

        door = (f"Make the packet again for this package: `controller.py --task-root {self.store.root} --operation "
                "prepare --input <a file holding the stage and role, as {\"stage\": ..., \"role\": ...}>` prints the "
                "request with this package's paths (`dispatch_request`); dispatch that with `--operation dispatch --input <file>`.")
        return contract.known_paths_for_dispatch(paths, project_root=project, plugin_root=plugin, python=sys.executable,
                                                 current=current, door=door, task_root=self.store.root)

    @staticmethod
    def _imports_prior_work(imported):
        """Does a legacy import carry anything beyond the story's own closed S0?"""
        imported = imported if isinstance(imported, dict) else {}
        stages = {str(stage) for stage in (imported.get("stages") or {}) if str(stage) != "S0"}
        return bool(stages or imported.get("dispatches") or imported.get("decisions"))

    def _import_legacy_pipeline(self, request):
        """Turn a pre-controller pipeline projection into explicit, conservative state.

        This migration is deliberately evidence-poor: completed receipts need a legacy
        digest, gates stay stale until their exact revision/scope is reconciled, and an
        inherited running role is a checkpoint to reconcile rather than a job to repeat.
        """
        pipeline_path = self.store.root / "pipeline.json"
        if not pipeline_path.exists() or request.get("legacy_import"):
            return request
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        if not isinstance(pipeline, dict):
            raise ValueError("legacy pipeline must be an object")
        stages, dispatches, decisions = {}, {}, {}
        for stage, receipt in (pipeline.get("stages") or {}).items():
            if not isinstance(receipt, dict) or not str(stage).startswith("S"):
                continue
            status = str(receipt.get("status") or "")
            if status in {"done", "completed"} and receipt.get("digest"):
                stages[stage] = {"status": "completed", "imported": True,
                                 "reason": str(receipt.get("digest"))}
            elif status in {"running", "started"} or (
                    # The S0 template (`phases/s0.md`) writes every later stage as
                    # `{"status": "pending", "role": ..., "digest": ""}`: a placeholder, not a
                    # role somebody started. Importing it made a phantom `legacy:S1` that
                    # blocked the first real dispatch until a person released it by word
                    # (TP1-13797, 2026-09-24 02:19-02:27 UTC). A `pending` receipt is an
                    # inherited job only when it names the dispatch or the agent it came from.
                    status == "pending" and (receipt.get("dispatch_id") or receipt.get("agent_id"))):
                did = "legacy:" + stage
                dispatches[did] = {"id": did, "stage": stage, "role": str(receipt.get("role") or "legacy"),
                                   "status": "incomplete", "checkpoint": {"remaining": [stage]},
                                   "reason": "legacy running receipt requires ownership reconciliation", "imported": True}
                stages[stage] = {"status": "incomplete", "dispatch_id": did, "imported": True}
        for gate, receipt in (pipeline.get("gates") or {}).items():
            if isinstance(receipt, dict) and receipt.get("decision") in {"approved", "approve"}:
                did = "legacy-gate:" + str(gate)
                decisions[did] = {"id": did, "gate": gate, "status": "stale", "imported": True,
                                  "authorization_source": receipt.get("authorization_source", "legacy pipeline"),
                                  "recoverable": bool(receipt.get("scope") and receipt.get("input_revision"))}
        if stages or dispatches or decisions:
            request["legacy_import"] = {"stages": stages, "dispatches": dispatches, "decisions": decisions}
        return request

    def validate(self, op, p, state):
        # K1 (C3-11): the shape checks of the request are independent of one another and all
        # `ValueError` (the call's fault), so they are one refusal: the known paths, then the
        # host's agent id.
        shape = known_paths_problems(p.get("known_paths")) if op in {"initialize", "dispatch"} else []
        # The host's own id of the launched agent. It is optional everywhere and known only
        # after the Agent call returns, which is why `checkpoint` and `accept` may carry it
        # too: on TP2-2553 nothing ever recorded it, the hook refused the resume of a
        # role that was still there, and the story paid for a fresh dispatch instead.
        if op in {"dispatch", "checkpoint", "accept", "resume"} and "agent_id" in p:
            if not isinstance(p["agent_id"], str) or not p["agent_id"].strip():
                shape.append((ValueError, "agent_id is the host's own id of the launched agent, as a "
                                          "nonempty string; omit it when the host reported none"))
        self._raise_all(shape)
        if op == "initialize":
            if state.get("source_revision") or not isinstance(p.get("scope"), list):
                raise StateConflict("initialize once with explicit scope")
            # K1: the three request fields are independent (the call's fault, one class).
            problems = []
            # TP2-2406: the scope holds case ids; the story's own key is none. Only a NEW write is checked.
            own = self._own_key_problem(p["scope"])
            if own:
                problems.append(own)
            if not p.get("source_revision") or not p.get("known_paths"):
                problems.append((ValueError, "source_revision and known_paths required"))
            if not self._among(p.get("coverage_contract_version"), {1, 2}):
                problems.append((ValueError, "unsupported coverage contract version"))
            if not self._among(p.get("plan_contract_mode"), {"new", "legacy"}):
                problems.append((ValueError, "initialize requires new or legacy plan contract mode"))
            self._raise_all(problems)
            return
        if not state.get("source_revision"):
            raise StateConflict("initialize task before work")
        if op == "revise_plan":
            held = self._holders_tail(state)       # TR4-7: a dispatch whose session is over does not hold the plan (`apply` recorded it)
            if held:
                raise StateConflict("checkpoint active work before revising scope" + held)
            problems = []
            if not isinstance(p.get("scope"), list) or not p.get("plan_revision") or not p.get("reason"):
                problems.append((ValueError, "plan revision requires scope, content revision and reason"))
            if any(k not in {"scope", "plan_revision", "reason", "required_quality_checks"} for k in p):
                problems.append((ValueError, "plan revision contains unsupported state fields"))
            if isinstance(p.get("scope"), list):
                problems.extend(self._revise_scope_problems(p["scope"]))
            self._raise_all(problems)
        elif op == "reconcile_dispatch":
            old = state["dispatches"].get(p.get("id"), {})
            successor = state["dispatches"].get(p.get("accepted_dispatch_id"), {})
            if old.get("status") not in STOPPED:
                raise StateConflict("only a stopped dispatch can be reconciled")
            if successor.get("status") != "accepted" or successor.get("unresolved"):
                raise StateConflict("reconciliation requires an accepted successor without unresolved scope")
            if (not old.get("scope") or not set(old["scope"]).issubset(successor.get("scope", []))
                    or any(old.get(k) != successor.get(k) for k in ("stage", "role", "input_hash"))):
                raise StateConflict("successor must cover the same stopped work and inputs")
            if not p.get("reason") or not successor.get("evidence_refs"):
                raise ValueError("reconciliation requires reason and accepted evidence")
            # K1 (C4-4): the references are independent of one another - every one that does not resolve is listed
            # (the checks above are of another class, or read the two records this one reads: they stop first).
            self._raise_all([(StateConflict, issue)
                             for issue in self._ref_issues(successor["evidence_refs"], "successor evidence")])
        elif op == "technical_normalize":
            allowed = {"json_format", "key_order", "crlf", "markdown_projection"}
            if p.get("kind") not in allowed or not p.get("semantic_hash") or not p.get("previous_semantic_hash"):
                raise ValueError("technical normalization requires allowlisted kind and both semantic hashes")
            gate = self._current_gate_a(state)
            if not gate:
                raise StateConflict("technical normalization preserves an existing current Gate A only")
            actual = self._plan_semantic_hash(self._plan_document())
            if (p["semantic_hash"] != p["previous_semantic_hash"]
                    or p["previous_semantic_hash"] != gate.get("plan_semantic_hash", gate.get("plan_content_hash"))
                    or p["semantic_hash"] != actual):
                raise StateConflict("semantic content changed; use semantic_reopen")
        elif op == "semantic_reopen":
            affected = p.get("affected_scope")
            if not p.get("reason") or not isinstance(affected, list) or not affected or not self._within(affected, state["scope"]):
                raise ValueError("semantic reopen needs reason and nonempty affected current scope")
            problems = []
            held = self._holders_tail(state)       # TR4-7: the same reading as every "checkpoint active work" refusal
            if held:
                problems.append((StateConflict, "checkpoint active work before reopening Gate A" + held))
            if not self._current_gate_a(state):
                problems.append((StateConflict, "semantic reopen requires current approved Gate A"))
            self._raise_all(problems)
        elif op == "handoff":
            from session_handoff import validate_takeover
            validate_takeover(state.get("leases", {}).get("orchestrator"), p, state, self.store.root)
            if (p.get("host_capability") == "fresh_orchestrator_context"
                    and "fresh_orchestrator_context" not in (state.get("host_capabilities") or [])):
                raise StateConflict("fresh orchestrator context is not verified for this host; use manual_continuation")
            if not isinstance(p.get("lease"), dict) or not p["lease"].get("owner_session_id"):
                raise ValueError("handoff needs a new owner lease")
        elif op == "orchestrator_telemetry":
            lease = state.get("leases", {}).get("orchestrator")
            problems = []
            if not lease or p.get("owner_session_id") != lease.get("owner_session_id"):
                problems.append((StateConflict, "orchestrator telemetry requires current lease"))
            if "orchestrator_telemetry" not in (state.get("host_capabilities") or []):
                problems.append((StateConflict, "host cannot provide verified orchestrator telemetry"))
            self._raise_all(problems)
            if not isinstance(p.get("model_requests"), int) or p["model_requests"] < 0:
                problems.append((ValueError, "orchestrator telemetry requires a nonnegative model request count"))
            if p.get("context_percent") is not None and (not isinstance(p["context_percent"], (int, float)) or not 0 <= p["context_percent"] <= 100):
                problems.append((ValueError, "context_percent must be 0..100 or unknown"))
            self._raise_all(problems)
        elif op == "coverage_migration":
            if state.get("coverage_contract_version") != 1 or p.get("from_version") != 1 or p.get("to_version") != 2:
                raise StateConflict("coverage migration requires an active version 1 task and known target version 2")
            if not p.get("plan_content_hash") or not p.get("backup_ref") or not p.get("migration_id"):
                raise ValueError("coverage migration requires exact plan hash, backup and migration ID")
            if content_hash(self._plan_document()) != p["plan_content_hash"]:
                raise StateConflict("coverage migration plan hash is stale")
            # Dry-run the target contract before appending an irreversible migration receipt.
            preview = p.get("dry_run")
            if not isinstance(preview, dict) or preview.get("plan_content_hash") != p["plan_content_hash"]:
                raise ValueError("coverage migration requires a current dry_run receipt")
            from planning_contract import validate_plan
            document = self._plan_document()
            rows = document.get("rows") if isinstance(document, dict) else document
            errors = validate_plan(rows, require_v2=True)
            if errors or preview.get("valid") is not True:
                raise StateConflict("coverage migration dry_run failed: " + "; ".join(errors or ["receipt invalid"]))
        elif op in HOLD_OPERATIONS:
            self._hold_op_refusal(op, p, state)
        elif op in ("reopen_story", "leave_unlaunched", "settle_order"):
            if op == "settle_order":
                self._settle_order_refusal(p, state)
            else:
                self._held_work_refusal(op, p, state)
        elif op == "dispatch":
            validate_record("Dispatch", p)
            # t-1937 TR3-4 (S-1, B1). POSITION: the FIRST check of this branch, before `required` (so it reads `p` with `.get`: the
            # fields may be absent), and it only decides whether the running dispatches below REFUSE this one. INVARIANT: every
            # check after it still runs on an admitted dispatch (the closure test, the id, the scope, the gates), and anything the
            # clause does not hold keeps the old refusal, byte for byte - the stage, the role, the plan, the flag, the scopes, the cap.
            # t-2147 TR3-9d: the S6 lane clause stands in the SAME condition. INVARIANT: each clause demands ALL running dispatches
            # be of its own kind, so a mixed set (an S5 window beside an S6 lane, a lane beside a suite) keeps the old refusal.
            _running_now = [d for d in state["dispatches"].values() if d["status"] == "running"]
            if _running_now and not (self._window_beside_running(p, state, _running_now)
                                     or self._lane_beside_running(p, state, _running_now)):
                # HF8-15 (2): text only - the rule (one running dispatch) is unchanged. The prefix stays the one every reader
                # matches (`story_run.KNOWN_REFUSALS`, the door table); the ids and, while an S5 code critic runs, the move that
                # sends its author back (`story_step.py finish --needs-author`) are what the run of 12586 lacked.
                running = sorted(str(d.get("id")) for d in state["dispatches"].values() if d["status"] == "running")
                critics = [str(d.get("id")) for d in state["dispatches"].values() if d["status"] == "running"
                           and d.get("stage") == "S5" and d.get("role") == "qa-code-critic"]
                raise StateConflict(
                    f"sequential task already has an active dispatch: {', '.join(running)}. Finish it first (`story_step.py finish`)"
                    + (f"; a critic that found its author's defect in its own way: `story_step.py finish --task "
                       f"{self._ticket()} --dispatch-id {sorted(critics)[0]} --needs-author <cases> --reason \"<words>\"`"
                       if critics else ""))
            required = ("id", "stage", "role", "input_hash", "scope", "budget", "known_paths")
            if any(k not in p for k in required) or not p["input_hash"]:
                raise ValueError("dispatch contract incomplete")
            # THE closure test (B-331, C1-6a; M1 (d) as code on every road): the skill path can dispatch a packet by hand,
            # so the driver's question is not the only guard. After the fields are known to be there, before any other
            # check reads them.
            closed_refusal = self._closed_dispatch_refusal(state, p)
            if closed_refusal:
                raise StateConflict(closed_refusal)
            problems = []   # K1 (C3-11): the id and the role's review are independent facts of the story
            if p["id"] in state["dispatches"]:
                problems.append((StateConflict, "resume existing dispatch; do not replace its checkpoint"))
            if p.get("role") == "qa-case-critic" and self._current_gate_a(state):
                problems.append((StateConflict, "CASE_REVIEW_AFTER_GATE_A: use technical_normalize or semantic_reopen before a new review"))
            self._raise_all(problems)
            if runner_kind_required(state, p.get("role"), p.get("purpose")):
                kind = p.get("execution_kind")
                if kind not in {"manual", "automation"}:
                    raise ValueError("new-task qa-runner dispatch requires execution_kind manual or automation")
                if kind == "manual":
                    manual = p.get("manual_case_ids")
                    validate_manual_runner_block(p["scope"], manual,
                                                 extra=self._half_membership_problems(p.get("stage"), state, manual, "manual"))
                else:     # RH1-10 (DC1-15): the same check for the automated half, on the dispatch road
                    refused = self._half_membership_problems(p.get("stage"), state, p["scope"], "automation")
                    if refused:
                        raise StateConflict(self.automation_half_refusal(refused))
            due = checkpoint_due(p["role"], p.get("counters", {}), p.get("limits"))
            if due["blocking"]:
                raise StateConflict("packet checkpoint threshold reached" + limit_reasons(due)
                                    + ". Close the running work with `controller.py --operation checkpoint` "
                                    "and dispatch the fresh packet it prints.")
            prior_counters = state.get("cumulative_counters", {}).get(budget_scope(p))
            total = (cumulative_budget(p["role"], prior_counters,
                                       {"active_seconds": 0, "requests": 0, "output_tokens": 0,
                                        "repair_cycles": 0}, p.get("limits")) if prior_counters else {})
            if total.get("blocking"):
                raise StateConflict("cumulative packet budget reached; resume cannot reset counters"
                                    + limit_reasons(total) + ". The way on is the person's word on the "
                                    "story budget, which reaches them through the driver's own table; "
                                    "do not retry the dispatch.")
            try:
                n = int(p["stage"][1:])
            except (TypeError, ValueError):
                raise ValueError(f"stage {p.get('stage')!r} must be one of: "
                                 + ", ".join(f"S{i}" for i in range(10)))
            if p["stage"] != f"S{n}" or not 0 <= n <= 9:
                raise ValueError(f"stage {p['stage']!r} must be one of: "
                                 + ", ".join(f"S{i}" for i in range(10)))
            # X7-6 (AR-13, AR-25): a prior stage that awaits its CONSUMER's acceptance does not block the consumer's own dispatch.
            # INVARIANT: only the role `acceptance_by` of that one stage, and only while `awaits_acceptance` (the one reader) holds;
            # every other role still meets the refusal below, and a stage with no `acceptance_by` is refused as before.
            from acceptance import awaits_acceptance, consumer_of
            if any(state["stages"].get(f"S{i}", {}).get("status") not in ("completed", "skipped")
                   and not (consumer_of(f"S{i}") == p.get("role") and awaits_acceptance(state, f"S{i}", self._pipeline()))
                   for i in range(n)):
                raise StateConflict("required prior logical stage incomplete")
            if "rerun_after" in p:
                self._validate_rerun_after(p, state, n)
            gate = "B" if n == 9 else "A" if n >= 5 else None
            if gate and not any(d.get("gate") == gate and d.get("status") == "approved"
                                and d.get("source_revision") == state["source_revision"]
                                for d in state["decisions"].values()):
                raise StateConflict(f"current Gate {gate} decision required")
            if n >= 5:
                self._validate_gate_a_content_current(state)
            # I1-I3, one reading (`_outside_approved`): a member equal to an approved one, or resolving to keys that
            # are ALL approved, passes; the rest is refused, an unhashable one without a `TypeError`
            _, outside = self._outside_approved(p["scope"], state["scope"])      # `validate_record` above: a list
            if outside and self._scope_not_recorded(p, state):
                # HF8-6 (F5 b): S4 before any gate A decision is not an expansion of anything approved; the head said "a new gate A
                # decision" to a story that never had one (run 12586) and named a door that does not lead to a pinned case
                raise StateConflict("the review scope does not hold yet: " + self._listed(m for m, _ in outside)
                                    + "; gate A has not been asked, so nothing approved is at stake. The scope holds pinned case ids: "
                                      "a case file that exists is pinned and recorded by `case_versions.py --task-root "
                                    + str(self.store.root) + " --all` (read `scope` and `scope_note` in its answer); a plan row id "
                                      "is not a case id, name the cases of that row; an id with no case file is written by the "
                                      "designer first")
            if outside:
                raise StateConflict("scope expansion requires plan/gate revision"
                                    + self._unapproved_text(outside, state["scope"]))
            # `issubset` lets [] through by definition, S5 acceptance compares {} to [] and
            # matches, and Gate A guards read `if state["scope"]` — so on TP2-2530 an
            # empty window completed S5 and nothing said a word until S8.
            if p["stage"] in DERIVED_SCOPE_STAGES and not p["scope"]:
                expected = self.stage_scope(p["stage"], state, p.get("execution_kind"))
                if not expected.get("derived"):
                    # q3 (AR-28), both derived stages: `stage_scope` turns an unreadable plan into `scope: []`; that is an
                    # unknown, not "nothing expected" (S5: the word `S5 scope: unreadable`, S6: `S6 half membership: unreadable`)
                    unreadable = self._unreadable_plan_problems(
                        state, "whether an empty scope is what the approved plan expects", p["stage"])
                    if unreadable:
                        raise StateConflict(unreadable[0])
                if expected.get("scope"):
                    kind = f" ({p['execution_kind']})" if p.get("execution_kind") else ""
                    errors = [f"{p['stage']}{kind} dispatch has an empty scope while the approved "
                              f"plan expects {len(expected['scope'])}: " + ", ".join(expected["scope"])]
                    blocking, _ = self._passed_by_person(p["stage"], errors)
                    if blocking:
                        raise StateConflict(
                            blocking[0] + ". Take the scope from the controller — "
                            "`--operation stage-scope` (also `stage_scope` in the prepare "
                            "packet) — never type it. If a person decided this stage runs "
                            "empty, record their words: `"
                            + person_words.door(f"waiver.py --task <TICKET> --stage {p['stage']} "
                                                "--block \"empty scope\"") + "`.")
            if p.get("repair_cause") is not None and p["repair_cause"] not in REPAIR_CAUSES:
                raise ValueError(f"repair_cause {p['repair_cause']!r} must be one of: "
                                 + ", ".join(REPAIR_CAUSES) + " (absent means test_defect)")
            cause = repair_cause(p)
            if cause != "test_defect" and not p.get("repair_cause_source") \
                    and not str(p.get("reason") or "").strip():
                raise ValueError(f"a {cause} round needs `reason`: one sentence of what happened. "
                                 "It spends none of the repair cap, so the receipt is the only "
                                 "place the retro can learn why the round existed.")
            # The repair cap must not depend on whether the host recorded a counter.
            if p.get("role") in REPAIR_LOOP_ROLES and not p.get("parent_retry"):
                policy = dict(DEFAULT_LIMITS, **(p.get("limits") or {}))
                cap = policy.get("design_repair_cycles" if "case" in p["role"] else "repair_cycles")
                ledger = repair_ledger(state["dispatches"], p)
                spent = ledger["counted"]
                free = ("A round that is not about a defect of the test spends none of the "
                        "cap: dispatch it with `repair_cause` mechanical | environment | "
                        "tooling | reviewer_error | question_answer | source_arrived | ticket_changed and a `reason`. ")
                if cause == "mechanical" and p["role"] not in AUTHOR_ROLES:
                    # After a mechanical fix the critic is not dispatched again: the author's
                    # green run on the new bytes closes the round (`acceptance.mechanical_round`).
                    key = mechanical_pass_key(state["dispatches"], p)
                    errors = [f"{key}: {p['role']} is not dispatched for a mechanical repair round "
                              f"on this {p['stage']} window"]
                    blocking, _ = self._passed_by_person(p["stage"], errors)
                    if blocking:
                        raise StateConflict(
                            blocking[0] + ". A mechanical fix is closed by the author's own "
                            "green run on the new bytes, never by another review; a review "
                            "that has something new to say about the test is a `test_defect` "
                            "round. If a person wants the review anyway: "
                            + repair_doors(p["stage"], [key]) + ".")
                elif cause == "mechanical":
                    allowed = self._dispatch_setting("mechanical_rounds")
                    had = mechanical_rounds(state["dispatches"], p)
                    if had >= allowed:
                        key = mechanical_pass_key(state["dispatches"], p)
                        errors = [f"{key}: this {p['stage']} window has already had {had} mechanical "
                                  f"repair round(s); the cap is {allowed}"]
                        blocking, _ = self._passed_by_person(p["stage"], errors)
                        if blocking:
                            raise StateConflict(
                                blocking[0] + ". A second list of mechanical fixes means the "
                                "first was not applied as worded: send it as a `test_defect` "
                                "round, or carry it as a named debt to the gate. If a person "
                                "wants one more: " + repair_doors(p["stage"], [key]) + ".")
                elif (cause == "test_defect" and ledger["opened"]
                      and cap is not None and spent >= cap):
                    counted = [r["id"] for r in ledger["rounds"] if r["cause"] == "test_defect"]
                    others = [f"{r['id']} ({r['cause']})" for r in ledger["rounds"]
                              if r["cause"] != "test_defect"]
                    # This role's pass opens the line, and only its own: a word matches by
                    # substring, so the other role's key stays out of the matched line.
                    passes = repair_passes(state["dispatches"], p)
                    errors = [f"{passes[p['role']]}: {p['role']} has already had {spent} repair "
                              f"round(s) about the test on this {p['stage']} window; the cap is {cap}. Counted as "
                              f"test_defect: {', '.join(counted) or 'none'}; not counted: "
                              f"{', '.join(others) or 'none'}"]
                    blocking, _ = self._passed_by_person(p["stage"], errors)
                    if blocking:
                        raise StateConflict(
                            blocking[0] + ". " + free + "Otherwise carry what is left as a "
                            "named debt to the gate instead of another round; a mechanical "
                            "fix the last review worded goes to the author as "
                            "`repair_cause: mechanical` and is closed by the author's own "
                            "green run on the new bytes, not by another review. If a person "
                            "wants one more round, one pass for each of the two roles, the "
                            "author's and the critic's, from the same words: "
                            # The block words must be IN the refused line: `--block "repair
                            # cap"` was advertised here through 0.7.7 and matched nothing.
                            + repair_doors(p["stage"], list(passes.values())) + ".")
            if p.get("purpose") and p["purpose"] not in PURPOSES:
                # "unsupported purpose; regression is user-owned" answered a question nobody
                # had asked: a free-text purpose was rejected without naming one that works.
                raise ValueError(f"purpose {p['purpose']!r} must be one of: "
                                 + ", ".join(sorted(PURPOSES))
                                 + " (a regression run is user-owned and is not a dispatch purpose)")
            if p.get("purpose") == S3_LABELLING and (p["stage"] != "S3" or p["role"] != "qa-test-strategist"
                                                     or p.get("rework_of")):
                # G1-11 (window 1 of S3). POSITION: after the closed-set check above, so an unknown word is still refused by
                # the old text first. INVARIANT: no labelling dispatch is ever registered on another stage or role, or as a
                # rework (a rework of accepted S3 work is ONE dispatch, which labels and plans together).
                raise ValueError(
                    f"purpose {S3_LABELLING} requires a fresh qa-test-strategist dispatch of S3: it is window 1 of S3 and nothing else "
                    f"(here: stage {p['stage']}, role {p['role']}"
                    + (f", rework of {p['rework_of']}" if p.get("rework_of") else "") + "). Dispatch it without --purpose, or as "
                    f"`story_step.py start --task <T> --stage S3 --role qa-test-strategist --purpose {S3_LABELLING}`; a "
                    "rework of accepted S3 work is one dispatch without this word.")
            # SC1-14 B1b. POSITION: after the closed-set check and the S3 word rule above, so an unknown word is refused by the old
            # text first. INVARIANT: a request without `s5_plan` on S5 outside the `planned` form passes exactly as before.
            self._raise_all(self._s5_plan_problems(p, state))
            if p.get("parent_retry"):
                # A name that is not a string (a list, an object) cannot be a dispatch id, and a
                # dict lookup with it is a bare `TypeError: unhashable`: the same refusal.
                old = (state["dispatches"].get(p["parent_retry"])
                       if isinstance(p["parent_retry"], str) else None)
                if old is None:
                    # A bare KeyError printed as `{"error": "'S4-qa-case-designer-99'"}` told a
                    # reader nothing: which field, which dispatch, what to dispatch instead.
                    raise StateConflict(
                        f"parent_retry {p['parent_retry']!r} names no dispatch of this story. A "
                        "retry resumes a dispatch that stopped with a checkpoint: dispatch the "
                        "`packet` that `controller.py --operation next` (or `--operation recover`) "
                        "prints for it, as it stands")
                if old["status"] not in STOPPED:
                    raise StateConflict("only a checkpointed dispatch can be resumed")
                if any(p.get(k) != old.get(k) for k in ("stage", "role", "scope", "input_hash")):
                    raise StateConflict("changed retry inputs require explicit invalidation")
                if old.get("reason") == BUDGET_EXHAUSTED:
                    raise StateConflict("hard quota exhaustion is not automatically retried")
                if p.get("checkpoint") != old.get("checkpoint"):
                    raise StateConflict("retry must inherit checkpoint")
            if p.get("relaunch_of"):
                # `relaunch_of` only ever named the dispatch it repeats; nothing checked that it
                # exists or that it ever needed repeating. A made-up name is a new dispatch in
                # disguise, so it gets the continuation's lineage and skips no check above.
                old = (state["dispatches"].get(p["relaunch_of"])
                       if isinstance(p["relaunch_of"], str) else None)
                if old is None:
                    raise StateConflict(
                        f"relaunch_of {p['relaunch_of']!r} names no dispatch of this story. A "
                        "relaunch repeats a dispatch that never reached an agent: dispatch the "
                        "`dispatch_request` that `controller.py --operation next` prints for it, "
                        "as it stands")
                if old.get("status") not in (NEVER_STARTED, RELEASED):
                    raise StateConflict(
                        f"relaunch_of {p['relaunch_of']!r} is {old.get('status')}: only a "
                        f"dispatch that never reached an agent ({NEVER_STARTED}) or that a "
                        f"person released ({RELEASED}) is relaunched. To go back over accepted "
                        "work use `controller.py --operation rework`; to resume a stopped role "
                        "use its retry packet (`--operation recover` prints it)")
                # The packet `next` prints copies these four fields from the record unchanged
                # (`_relaunch_packet`), so they are compared as they are - the same four a
                # `parent_retry` must repeat. A relaunch that changes any of them is different
                # work under the name of the old one; that is a dispatch of its own.
                differs = {}
                for key in ("stage", "role", "scope", "input_hash"):
                    mine, theirs = p.get(key), old.get(key)
                    if key == "scope":  # an absent scope is an empty one
                        mine, theirs = list(mine or []), list(theirs or [])
                    if mine != theirs:
                        differs[key] = f"{key} is {mine!r} here and {theirs!r} there"
                if differs:
                    raise StateConflict(
                        f"relaunch_of {p['relaunch_of']!r} repeats that dispatch's work, and this "
                        f"packet differs in {', '.join(differs)} ({'; '.join(differs.values())}). "
                        "Dispatch the `dispatch_request` that `controller.py --operation next` "
                        "prints for it, as it stands; different work is a new dispatch, sent "
                        "without `relaunch_of`")
            # F5: the stopped story and `await_reopened` are checked where the dispatch commits, not only where the rework is built
            self._hold_dispatch_refusal(p, state)
            guard = self.stage_guard_errors(p["stage"], role=p.get("role"))
            if guard:
                raise StateConflict("; ".join(guard))
        elif op == "request_cancel":
            from worker_lifecycle import cancellation
            if state["dispatches"].get(p.get("id"), {}).get("status") != "running":
                raise StateConflict("cancellation requires the active dispatch")
            cancellation(p)
            # K1 (C4-4): the two references are independent (`cancellation` above is another class)
            # the references are fields of the request: the call's fault (FR-46), the class of the five other reference loops
            self._raise_all([(ValueError, issue) for issue in self._found(
                self._path_issue(p[key], "cancellation " + key[:-len("_ref")])
                for key in ("evidence_ref", "authorization_ref") if p.get(key))])
        elif op == "resume":
            # FB-4. The checks are independent facts of the request and the record: one refusal for all of them (K1).
            self._raise_all(self._resume_problems(p, state))
        elif op in ("checkpoint", "accept"):
            d = state["dispatches"].get(p["id"]) if isinstance(p.get("id"), str) else None
            if not d and "id" not in p:
                # R3 (run 12586): a `dispatch_id` for `id` was refused as «unknown dispatch», twice, naming neither.
                # The class stays StateConflict: the driver routes on it (E10).
                raise StateConflict("unknown dispatch: the request names no dispatch - \"id\" is absent (keys given: "
                                    + _keys_given(p) + "). " + apply_door(op, self.store.root, "", state["dispatches"]))
            if not d:
                # AR-13: the ONE text of this refusal is `_unknown_dispatch`'s; only the class differs here
                raise StateConflict("unknown dispatch" + self._dispatch_gap(p.get("id"), state["dispatches"]))
            # A returned or abandoned dispatch still finishes here. Its role is gone, but the
            # evidence it wrote is on disk and hash-checked below, and deciding what that work
            # is worth was always the orchestrator's job, never the hook's (TP2-2523).
            if d["status"] not in {"running"} | SETTLED:
                # TP2-2553: the original dispatch was `checkpoint --status blocked`,
                # `accept` answered "only the active dispatch can finish; ... is blocked",
                # and nothing said which id to accept instead or how to get one. A stopped
                # dispatch has exactly two ways on, and the refusal names them both.
                retry = self._retry_children(state["dispatches"], d.get("id"))
                if d.get("passed_over_by") and not retry:
                    # TR1-9 B3 (AR-25): a row a code close passed over has a way out: its stage is closed without it
                    raise StateConflict(f"{d.get('id')} was passed over when its stage was closed by code (receipt {d['passed_over_by']}): "
                                        f"its work is not taken; going back over the stage is `controller.py --task-root {self.store.root} "
                                        "--operation rework`")
                if op == "accept" and retry:
                    # The retry marks its parent `superseded` the moment it is dispatched, so
                    # the status alone never pointed at the id that carries the work now.
                    raise StateConflict(self._retry_holds(d, retry) + f"accept {retry[-1]}")
                resume_first = self._resume_clause(d)    # FB-4: "" unless the same agent can continue it
                if op == "accept" and d["status"] in STOPPED:
                    raise StateConflict(
                        resume_first + f"{d.get('id')} is {d['status']}: a stopped dispatch is not accepted "
                        "where it stands. Retry it and accept the retry — `controller.py "
                        f"--task-root {self.store.root} --operation recover` prints the ready "
                        "packet, which inherits this checkpoint and supersedes this dispatch "
                        "— or, if this is as far as the work goes, record what is left with "
                        f"`--operation checkpoint --dispatch {d.get('id')} --status "
                        "incomplete --reason \"<what is left>\" --brief`.")
                raise StateConflict(resume_first + "only the active dispatch can finish; " + str(d.get("id"))
                                    + " is " + str(d.get("status")))
            if op == "checkpoint":
                from worker_lifecycle import active_binding
                project = self._project_root()      # None (no project found): no receipt to read, the veto is skipped
                # Dispatch ids repeat across stories: only a receipt naming THIS story is this worker. A receipt carries the
                # `--task` of its writer, so the veto asks for every spelling of this folder (`_story_names`): a receipt under
                # another case or through a link still holds it (a live worker is never lost to a spelling, CX2-17 E21).
                if project and any(active_binding(project, d["id"], name) for name in self._story_names(project)):
                    raise StateConflict("host worker is still active or cancellation unacknowledged; preserve progress and wait")
            if not self._among(p.get("status"), TERMINAL):
                raise ValueError("invalid completion status:" + self._status_gap(op, p))
            if op == "accept":
                # K1 (C4-4): the evidence, or each of its references, and the reason of an unresolved handoff are
                # independent facts of the request - one refusal. The references are read only from evidence that holds.
                problems = []
                if p["status"] != "accepted" or not p.get("evidence_refs"):
                    problems.append((ValueError, "accept requires evidence, never an empty digest"))
                    if p.get("evidence_refs"):   # only the status is wrong: the references are there and were not read
                        problems = self._noted(problems, "(the evidence references were not checked: the status is not accepted)")
                else:
                    problems += [(ValueError, issue) for issue in self._ref_issues(p["evidence_refs"])]
                if p.get("unresolved") and not p.get("reason"):
                    # R8 (run 12586, Lead decision 27.10): the field, what "reason" carries, and the door - the old bare
                    # sentence named none of them. No code or driver matches the old phrase (grep, the t-1263 report).
                    problems.append((ValueError, "\"unresolved\" is given without \"reason\": \"reason\" carries why the work is "
                                     "accepted unresolved (S1: the person's words of the accepted gap, as ticket_adapter.py "
                                     "accept-gap recorded them). "
                                     + apply_door("accept", self.store.root, d.get("id"), state["dispatches"])))
                self._raise_all(problems)
                # SC1-14 B1b. POSITION: before the window's receipts. INVARIANT: a window record is accepted exactly as before; a
                # plan has no window record, so the receipts (FR-5) are not asked of it.
                self._raise_all(self._s5_plan_accept_problems(d, p, state))
                # SC1-14 FJ-C (13). POSITION: beside the B1b call, before the window's receipts. INVARIANT: a window that did not
                # grow, a plan record and a story on the earlier form are accepted exactly as before; S5 does not close while a
                # grown window's author or critic has not covered it.
                self._raise_all(self._grown_close_problems(d, p, state))
                review = [] if s5_part_of(d) == "plan" else self._code_review_refusal(d, p)
                s5_window = d.get("stage") == "S5" and bool(p.get("stage_complete"))
                if review and not s5_window:
                    # Outside the S5 completion branch the receipts are the only check that runs,
                    # so they refuse at once, as they always did; inside it they join the list.
                    self._raise_all(review)
                # A completion that names unresolved work with a reason says why the stage is
                # not done, and a rework of the same role can still close it. The refusal is
                # for the silent `false` — the one that claims nothing is left and still
                # leaves the stage with no role to close it. TP2-2553 accepted both S4
                # roles that way; gate A then refused with "stage not completed" and the only
                # road out was a duplicate `S4-qa-case-critic-2` over unchanged evidence.
                # t-1937 TR3-4 (B3). POSITION: before the refusal below, which it may lift. INVARIANT: only `open_windows` that names
                # real OTHER windows of the stage lifts it, never with `unresolved`; the silent `false` on a truly last window (no
                # `open_windows`) is refused exactly as before. A bad name is its own refusal, naming the windows.
                self._raise_all(self._open_windows_problems(d, p, state))
                if (p.get("stage_complete") is False and not p.get("unresolved") and "open_windows" not in p
                        and self._closes_stage(d, state)):
                    raise StateConflict(
                        f"accepting {d.get('id')} with stage_complete: false leaves "
                        f"{d.get('stage')} with no role to close it — pass stage_complete: "
                        "true, name the unresolved work with its reason, or checkpoint the "
                        "dispatch if the work is not done (`controller.py --task-root "
                        f"{self.store.root} --operation checkpoint --dispatch {d.get('id')} "
                        "--status incomplete --reason \"<what is left>\" --brief`)")
                if d["stage"] == "S1" and p.get("stage_complete"):
                    inventory_path = self.store.root / "work/source-inventory.json"
                    if inventory_path.exists() or state.get("source_inventory_required"):
                        if not inventory_path.is_file():
                            raise StateConflict("S1 requires canonical source inventory")
                        # ONE summary (t-721 F-7): `source_inputs` judges the inventory - it refuses a pending or
                        # invalid one, and an S1 that is already `completed` keeps the old meaning of an acceptance
                        # it recorded (`s1_closed`, t-114 G3). A second `completeness(inventory)` here read the same
                        # inventory with `s1_closed=False` and could disagree with it (a re-acceptance of a closed
                        # S1 over a legacy whole-source acceptance); the branch that read a person's word for that
                        # disagreement is gone with it. The person's word about a source gap is `accept-gap`.
                        summary = self.source_inputs(state)["source_completeness"]
                        if not summary["complete"] and not (p.get("unresolved") and p.get("reason")):
                            # R7 (run 12586): the sentence now names the sources it counts and the two fields that pass it
                            # `pending` is counted by `completeness` as blocking, so it is named too (S7-5)
                            ids = sorted({str(i) for name in ("pending", "unavailable", "unavailable_materials",
                                                              "incomplete_materials", "accepted_gaps")
                                          for i in (summary.get(name) or [])})
                            # The pair is the PERSON's word about the gap, never a caller's (P13, FR-57): the door is the
                            # person's `accept-gap` first, then a plain `finish`, which derives "unresolved" and "reason"
                            # from the inventory itself (`story_step._s1_accepted_gaps`) - no flag passes them by hand.
                            raise StateConflict("S1 unavailable sources require explicit unresolved gap handoff: the inventory "
                                                + (f"lists {', '.join(ids)} and " if ids else "") + "the completion names no "
                                                "unresolved gap. The gap is the person's to accept: record their words with "
                                                f"`ticket_adapter.py accept-gap --output {self.store.root / 'work' / 'source-inventory.json'} "
                                                "--source-id <the source id> --words-file <the file holding the person's own words>` "
                                                "(a source the factory's own probe found unreachable is a default gap and needs "
                                                "no question), then finish: the completion's \"unresolved\" and \"reason\" are "
                                                "derived from the inventory, not typed. "
                                                + apply_door("accept", self.store.root, d.get("id"), state["dispatches"]))
                if d["stage"] == "S3":
                    self._s3_completion_gate(d, p, state)
                if p.get("stage_complete"):
                    # X2-5 (E-B11). POSITION: after every check of this branch that exists today, before the S5/S6 branches. INVARIANT: a stage
                    # without `acceptance_by` (S0, S1, S5, S8, S9) is refused nothing new; S2, S3, S4, S6 and S7 do not close without an `accept`
                    # record for the author's last dispatch, or a person's recorded word (P13).
                    from acceptance import stage_acceptance_refusal
                    refusal, passed = stage_acceptance_refusal(self._pipeline(), d, state, self._passed_by_person)
                    if refusal:
                        raise StateConflict(refusal)
                    self._record_person_pass(d["stage"], d.get("id"), passed)
                if d["stage"] == "S5" and p.get("stage_complete"):
                    # ONE list (K1): every independent gap of the window at once, in tiers; the
                    # tiers and what each one stops are in `_s5_completion_problems`.
                    # t-1937 TR3-4 (item 5): the backstop first in the list, the rest of the tiers as they were.
                    self._raise_all(self._s5_running_beside_problems(d, state)
                                    + self._s5_completion_problems(d, p, state, review))
                if d["stage"] == "S6" and p.get("stage_complete"):
                    # t-2147 TR3-9d (the S6 twin of the S5 backstop above): the code gate UNDER the driver's close predicate.
                    # INVARIANT: S6 never closes over a manual lane still at work; a story with no running manual sibling is
                    # refused nothing new.
                    # ONE list (K1, as the S5 branch above): the backstop first, then the derived-scope gap.
                    s6_gaps = self._s6_running_beside_problems(d, state)
                    blocking = []
                    if state.get("plan_contract_mode") == "new":
                        blocking, _ = self._passed_by_person("S6", self._s6_completion_problems(d, state))
                    if blocking:
                        s6_gaps.append((StateConflict,
                            "; ".join(blocking) + ". Accept this dispatch with `stage_complete: "
                            "false`, dispatch that half (`controller.py --operation stage-scope` "
                            "with `execution_kind` names its cases; the qa-runner packet carries "
                            "`execution_kind` and, for the manual half, `manual_case_ids`; `story_step.py start --stage S6 "
                            "--role qa-runner --execution-kind automation`, or `--execution-kind manual --scope <1..5 ids>` "
                            "for one manual block), and let "
                            "the last S6 dispatch complete the stage. If a person closes S6 "
                            "without it: `"
                            + person_words.door(f"waiver.py --task {self._ticket()} --stage S6 "
                                                "--block \"derived scope\"") + "`."))
                    self._raise_all(s6_gaps)
            elif p["status"] == "accepted":
                raise ValueError("checkpoint is not acceptance; use accept with validated evidence")
            elif not p.get("checkpoint") or not p.get("reason"):
                raise ValueError("checkpoint requires remaining work and reason")
        elif op == "decision":
            # ONE body of rules, shared with `check_decision` so a rehearsal cannot drift
            # from the real thing. Every problem is raised in one refusal (K1: a request refused
            # one defect at a time cost a round per defect); its class is the first problem's
            # (FR-46), so a caller that catches StateConflict or ValueError still sees what it did.
            self._raise_all(self._decision_problems(p, state))
            # RH1-6 (F-2): a SEPARATE call after the shared rules - `_decision_problems` is what the rehearsal runs, so an item
            # check inside it would make the rehearsal read its own result. No road records gate A over an open item (A-E10).
            self._raise_all([(StateConflict, item_sentence) for item_sentence in self.open_gate_items(p.get("gate"))[0]])
        elif op == "policy":
            problems = []   # K1 (C3-11): the request's two fields, then the story's two facts - each run one class
            if not self._among(p.get("mode"), {"preparatory", "no_implementation"}):
                problems.append((ValueError, "policy mode must be preparatory or no_implementation"))
            if not all(p.get(k) for k in ("id", "reason", "source_revision")):
                problems.append((ValueError, "policy requires id, reason and source revision"))
            self._raise_all(problems)
            if p.get("source_revision") != state["source_revision"]:
                problems.append((StateConflict, "policy references stale source revision"))
            if not isinstance(p.get("scope"), list) or not self._same_set(p["scope"], state["scope"]):
                problems.append((StateConflict, "policy must bind the exact approved scope"))
            self._raise_all(problems)
            # K1 (C4-4): the evidence list, or each of its references - a list that is none has no reference to read,
            # so the two never both have an item and nothing is skipped
            if not isinstance(p.get("evidence_refs"), list) or not p["evidence_refs"]:
                problems.append((ValueError, "policy requires evidence for the no-implementation decision"))
            else:
                problems += [(ValueError, issue) for issue in self._ref_issues(p["evidence_refs"], "policy evidence")]
            self._raise_all(problems)
            if state["stages"].get("S4", {}).get("status") != "completed":
                raise StateConflict("preparatory policy requires completed S4")
            if any(d.get("gate") == "A" and d.get("status") == "approved"
                   and d.get("source_revision") == state["source_revision"]
                   and set(d.get("scope") or []) == set(state["scope"])
                   for d in state["decisions"].values()) is False:
                raise StateConflict("preparatory policy requires current Gate A approval")
            if any(state["stages"].get(stage, {}).get("status") == "completed" for stage in ("S5", "S6")):
                raise StateConflict("preparatory policy cannot replace completed execution")
            if p["id"] in state["policies"]:
                raise StateConflict("policy already recorded")
        elif op == "code_only":
            stage = p.get("stage")
            # S0 joins S6-S8 because no role runs it: preflight is the orchestrator's own
            # work, so there is no dispatch to `accept` and `stage_done --status done` on an
            # already-initialized task had no way through at all (TP1-15045 review).
            # Its evidence is the pipeline.json S0 just wrote.
            problems = []   # K1 (C3-11): the request's three fields, then the story's three facts
            if not self._among(stage, {"S0", "S6", "S7", "S8"}):
                problems.append((ValueError, "code-only receipts are allowed only for S0, S6, S7 or S8"))
            if not all(p.get(k) for k in ("id", "reason")):
                problems.append((ValueError, "code-only receipt requires id and reason"))
            if not isinstance(p.get("evidence_refs"), list) or not p["evidence_refs"]:
                problems.append((ValueError, "code-only receipt requires evidence"))
            self._raise_all(problems)
            # AR-13: the one predicate of "closable by code now"; the liveness verdicts are read HERE and passed in (the predicate
            # stays pure), and a verdict that cannot be read keeps the row running (FR-59, AR-28)
            verdicts = self._close_verdicts(state, stage)
            problems += code_close_conflicts(state, stage, verdicts)
            self._raise_all(problems)
            # B4: the close names exactly what it passes over. A verdict that flipped between `apply` (which wrote the names into the
            # request) and now would close over work no one named, so the request is sent again (the state moved).
            named = [{"id": ident, "label": label} for ident, label in code_close_facts(state, stage, verdicts).get("passed_over") or []]
            if (p.get("passed_over") or []) != named:
                raise StateConflict("the state moved while the close was prepared: the dispatches it passes over changed, send it again")
            # K1 (C4-4): the list holds (the fields run above refused it otherwise); every reference that does not resolve
            problems += [(ValueError, issue) for issue in self._ref_issues(p["evidence_refs"], "code-only evidence")]
            self._raise_all(problems)
        elif op == "invalidate":
            problems = []   # K1 (C3-11): the cause and the scope are independent fields of the request
            if not p.get("reason"):
                problems.append((ValueError, "invalidation requires a cause"))
            affected = p.get("affected_scope")
            if not isinstance(affected, list) or not affected or not self._within(affected, state["scope"]):
                problems.append((ValueError, "invalidation must name a nonempty affected current scope"))
            self._raise_all(problems)
            if any(x not in state["dispatches"] for x in p.get("dispatch_ids", [])) or any(
                    x not in state["decisions"] for x in p.get("decision_ids", [])):
                raise StateConflict("invalidation names unknown records")
            # the two checks below read `state["dispatches"][x]`: they run only once the ids are known
            held = self._holders_tail(state, set(p.get("dispatch_ids", [])))
            if held:       # TR4-7: only the named dispatches count (liveness is read for them alone), and only the live ones
                problems.append((StateConflict, "checkpoint active work before invalidation" + held))
            if any(not set(state["dispatches"][x].get("scope") or []).intersection(affected)
                   for x in p.get("dispatch_ids", [])):
                problems.append((StateConflict, "invalidation may name only dispatches in its affected scope"))
            self._raise_all(problems)
            applicability = p.get("gate_a_applicability")
            if applicability is not None:
                if not p.get("source_revision") or p["source_revision"] == state.get("source_revision"):
                    raise ValueError("Gate A applicability carry requires a new source revision")
                prior = state["decisions"].get(str(applicability.get("decision_id")), {})
                # The carry's facts are NOT all independent: the decision it names (1) is the record the exact-scope
                # check (4) reads `prior` from, so (4) runs only once (1) holds; (2) and (3) wait for it as well
                # (the carry is read decision first). Items 2 to 4 are independent of one another (one door:
                # fix the carry) and are refused together. A stop at (1) says which checks did not run (FR-59).
                if (prior.get("gate") != "A" or prior.get("status") != "approved"
                        or prior.get("source_revision") != state.get("source_revision")):
                    self._raise_all(self._noted(
                        [(StateConflict, "Gate A applicability must name the current approved Gate A decision")],
                        "(the checks of the unchanged requirements, the plan revision and the exact scope did not "
                        "run: they read the decision named here)"))
                if applicability.get("requirements_unchanged") is not True:
                    problems.append((StateConflict, "Gate A applicability requires explicit unchanged requirements and oracle"))
                expected_plan = state.get("plan_revision") or state.get("source_revision")
                if applicability.get("plan_revision") != expected_plan:
                    problems.append((StateConflict, "Gate A applicability must bind the unchanged current plan revision"))
                if (not isinstance(applicability.get("scope"), list)
                        or not self._same_set(applicability["scope"], state["scope"])
                        or not self._same_set(prior.get("scope") or [], state["scope"])):
                    problems.append((StateConflict, "Gate A applicability must preserve the exact approved scope"))
                self._raise_all(problems)
                refs = applicability.get("evidence_refs")
                # K1 (C4-4): the evidence list, or each of its references (a list that is none has no reference to read)
                if not isinstance(refs, list) or not refs:
                    problems.append((ValueError, "Gate A applicability requires evidence of unchanged requirements"))
                else:
                    problems += [(ValueError, issue) for issue in self._ref_issues(refs, "Gate A applicability evidence")]
                self._raise_all(problems)
        elif op == "mutation":
            if not all(p.get(k) for k in ("id", "dispatch_id", "paths", "before_hashes")):
                raise ValueError("mutation requires intent, owned paths and before hashes")
            dispatch = state["dispatches"].get(p["dispatch_id"], {})
            problems = []   # K1 (C3-11): the author dispatch and the recorded intent are independent facts
            if not dispatch:
                problems.append((StateConflict, "mutation names an unknown author dispatch"))
            old = state["mutations"].get(p["id"])
            if old and any(p.get(k) != old.get(k) for k in ("dispatch_id", "paths", "before_hashes")):
                problems.append((StateConflict, "mutation ownership and original content are immutable"))
            self._raise_all(problems)
            order = ("planned", "writing", "written", "executed", "reviewed")
            status = p.get("status")
            if status not in order:
                raise ValueError("unknown mutation progress")
            # the author dispatch exists by now, so what is left of the story's facts is independent
            problems += self._mutation_dispatch_problems(status, dispatch, p, state)
            if not old and status != "planned":
                problems.append((StateConflict, "persist intent before changing files"))
            if old and order.index(status) != order.index(old["status"]) + 1:
                problems.append((StateConflict, "mutation progress cannot skip evidence steps"))
            self._raise_all(problems)
            if status in ("written", "executed", "reviewed") and not p.get("after_hashes"):
                problems.append((ValueError, "written progress requires content hashes"))
            if status in ("executed", "reviewed") and not p.get("evidence_refs"):
                problems.append((ValueError, "execution/review requires receipts"))
            self._raise_all(problems)
        else:
            raise ValueError(f"operation {op!r} must be one of: " + ", ".join(sorted(APPLY_OPERATIONS)))

    @staticmethod
    def _mutation_dispatch_problems(status, dispatch, p, state):
        """The author/reviewer dispatch facts of a `mutation` progress step, as `[(class, message)]` (a helper of `validate`)."""
        problems = []
        if status == "reviewed":
            reviewer = state["dispatches"].get(p.get("reviewer_dispatch_id"), {})
            if reviewer.get("status") != "running" or reviewer.get("role") != "qa-code-critic":
                problems.append((StateConflict, "reviewed mutation needs an active independent qa-code-critic dispatch"))
            if dispatch.get("status") not in {"accepted", "paused", "blocked", "incomplete"}:
                problems.append((StateConflict, "author mutation must be checkpointed before independent review"))
        elif dispatch.get("status") != "running":
            problems.append((StateConflict, "mutation writes must belong to an active author dispatch"))
        return problems

    # --- one refusal for every independent defect (K1, cmp3) ---------------------------------
    # The refusals of `decision` and of the S5 completion used to raise the FIRST defect, so a
    # request with three defects cost three rounds, each with a role or a conductor behind it.
    # The checks that do not depend on one another now collect `[(class, message)]` - the form
    # `_decision_problems` already had - and `_raise_all` refuses them whole.
    COMPOUND_HEAD = "{n} problems - the request is refused whole, every one is listed:"

    @staticmethod
    def _merged(problems):
        """`problems` with identical messages folded into the first one's place as `<message>
        (×K)`: the per-instance checks write one template per instance, and K lines of the same
        sentence would only hide the line that differs."""
        counts = {}
        for _, message in problems:
            counts[str(message)] = counts.get(str(message), 0) + 1
        merged, seen = [], set()
        for cls, message in problems:
            message = str(message)
            if message not in seen:
                seen.add(message)
                merged.append((cls, message if counts[message] == 1 else f"{message} (×{counts[message]})"))
        return merged

    @classmethod
    def _raise_all(cls, problems):
        """Refuse with every problem of `[(class, message)]`, or do nothing when there is none.

        One problem is its own sentence, unchanged. Several are one numbered text under a head
        that states their number (`COMPOUND_HEAD`); the head and the `N) ` lines are the contract
        `detector_verdict.split_items` reads, so the number in the head is the number of lines
        and a line of a multi-line message that could pass for a numbered one is indented.
        The class is the FIRST problem's: no caller branches on it, and the order of the checks
        puts the most basic one first. Nothing is cut and nothing is written here (FR-45)."""
        merged = cls._merged(problems)
        if not merged:
            return
        if len(merged) == 1:
            raise merged[0][0](merged[0][1])
        lines = [cls.COMPOUND_HEAD.format(n=len(merged))]
        lines += [f"{number}) " + message.replace("\n", "\n   ")
                  for number, (_, message) in enumerate(merged, 1)]
        raise merged[0][0]("\n".join(lines))

    @staticmethod
    def _same_set(left, right):
        """`set(left) == set(right)`, and False when an element cannot be hashed (see `_among`)."""
        try:
            return set(left) == set(right)
        except TypeError:
            return False

    @staticmethod
    def _within(items, allowed):
        """`set(items).issubset(allowed)`, and False when an element cannot be hashed (see `_among`)."""
        return _subset_of(items, allowed)

    @staticmethod
    def _among(value, allowed):
        """`value in allowed` (a set), and False for a value that cannot be hashed: a chain evaluates every
        check, so an object a later check would have choked on must be a refusal of its own, not a TypeError
        that hides the problems found before it."""
        try:
            return value in allowed
        except TypeError:
            return False

    @staticmethod
    def _noted(problems, note):
        """`problems` with `note` appended to the LAST message: the sentence that says which
        checks did NOT run (FR-59 - a skipped check names itself, it never reads as a pass)."""
        cls, message = problems[-1]
        return problems[:-1] + [(cls, f"{message} {note}")]

    @staticmethod
    def _dispatch_gap(identifier, dispatches):
        """What follows `unknown dispatch` in the ONE text of that refusal: the id as given (repr - a list or a number is
        a refusal, never a TypeError) and the ids the story has."""
        return f" {identifier!r}; this story has " + (", ".join(sorted(map(str, dispatches))) or "none")

    @staticmethod
    def _unknown_dispatch(identifier, dispatches):
        """The problem `[(class, message)]` entry for a dispatch id the story does not have, naming the ones it has: the ONE text
        of that refusal (`checkpoint`, `release`, the two held-work ops, and `validate`'s accept/checkpoint at the state class)."""
        return (ValueError, "unknown dispatch" + Controller._dispatch_gap(identifier, dispatches))

    @staticmethod
    def _status_gap(op, p):
        """The part after `invalid completion status:` - the field, what the request holds in it, the closed set, and (an
        accept) the one value it carries. A key of the request that names a status in its own spelling is said to be
        unread - by the key's exact name, from the request, never from a table of synonyms (FR-12; R6, run 12586)."""
        held = repr(p["status"]) if "status" in p else "absent"
        text = f" \"status\" is {held}; a completion status is one of: {', '.join(sorted(TERMINAL))}."
        if op == "accept":
            text += " An accept carries \"status\": \"accepted\"."
        unread = sorted(str(k) for k in p if isinstance(k, str) and k != "status" and "status" in k)
        return text + "".join(f" \"{k}\" is not read." for k in unread)

    # --- FB-4: a dispatch stopped for a person and continued by its own agent --------------------------------------------------
    RESUMABLE = ("blocked", "paused")   # `incomplete` is work left, not a person's answer: its agent is gone, its road is the retry

    def _resume_command(self, d):
        """`story_step.py resume --task <key> --dispatch-id <id>` for a dispatch that can go on in place, else ''. Named only
        when the road exists: the record carries the agent that held the context and the status is resumable (FR-2 - a door
        the refused party can use). The ONE spelling of the command in the controller (AR-15)."""
        agent = d.get("agent_id") if isinstance(d, dict) else None
        if not isinstance(d, dict) or d.get("status") not in self.RESUMABLE or not (isinstance(agent, str) and agent.strip()):
            return ""
        return self._resume_door(d.get("id"))

    def _resume_door(self, dispatch_id):
        """The command that resumes `dispatch_id`, ungated: the door a refusal of the resume itself names."""
        return f"story_step.py resume --task {self._ticket()} --dispatch-id {dispatch_id}"

    @staticmethod
    def _retry_children(dispatches, dispatch_id):
        """The ids of the retries that continue `dispatch_id` (their `parent_retry` names it); [] when none."""
        return [o.get("id") for o in dispatches.values() if o.get("parent_retry") == dispatch_id]

    @staticmethod
    def _retry_holds(d, retry):
        """The head every refusal of a superseded dispatch starts with: its retry carries the work now (each caller adds its door)."""
        return f"{d.get('id')} is {d.get('status')}: {retry[-1]} is its retry and holds this work now; "

    def _resume_clause(self, d):
        """The clause a refusal of `accept` / `checkpoint` on a STOPPED dispatch starts with, or '' (R6): the resume first.
        The old text follows it unchanged."""
        command = self._resume_command(d)
        return f"if the same agent continued it: `{command}`, then run this again; else " if command else ""

    @staticmethod
    def _last_stop_sequence(events, dispatch_id):
        """The journal sequence of the LAST `checkpoint` event of this dispatch, or None: the stop a resume retires."""
        found = [event.get("sequence") for event in events
                 if event.get("type") == "checkpoint" and (event.get("payload") or {}).get("id") == dispatch_id]
        return max(found) if found else None

    def _resume_status_problems(self, d, dispatches):
        """Why a dispatch in THIS status is not resumed, each with the door of its status (R2 b); [] for blocked / paused."""
        did, status, root = d.get("id"), d.get("status"), self.store.root
        if status in self.RESUMABLE:
            return []
        door = f"`controller.py --task-root {root} --operation "
        if status == "superseded":
            retry = self._retry_children(dispatches, did)
            if retry:
                return [(StateConflict, self._retry_holds(d, retry) + f"finish or pause {retry[-1]}")]
            return [(StateConflict, f"{did} is superseded: this work was set aside; {door}next` prints what holds the "
                                    "stage now")]
        if status == "running" or status in SETTLED:
            return [(StateConflict, f"{did} is {status}: it is not stopped; `story_step.py finish --task {self._ticket()} "
                                    f"--dispatch-id {did} --digest \"<digest>\"` or `story_step.py pause` takes it as it is")]
        if status == "incomplete":
            return [(StateConflict, f"{did} is incomplete: it stopped with work left, not for a person's answer, so no "
                                    f"agent holds its context; continue it with the retry packet {door}recover` prints")]
        if status in (NEVER_STARTED, RELEASED):
            return [(StateConflict, f"{did} is {status}: it never reached an agent, or a person set it free, so no agent "
                                    f"holds its work; {door}next` prints the relaunch packet")]
        if status in ("accepted", "stale"):
            return [(StateConflict, f"{did} is {status}: its work is closed; going back over it is {door}rework`")]
        return [(StateConflict, f"{did} is {status}: only a dispatch stopped for a person (blocked or paused) is resumed; "
                                f"{door}next` prints what the story does now")]

    def _resume_stop_problems(self, d, p):
        """The checks that read the stop itself: the budget, the agent, the stale request (R2 c, e, f, g)."""
        did, root, problems = d.get("id"), self.store.root, []
        if d.get("reason") == BUDGET_EXHAUSTED:
            problems.append((StateConflict, f"{did} stopped on the story budget ({BUDGET_EXHAUSTED}): hard quota exhaustion "
                                            "is not automatically resumed. Raise the quota (the person's word on the story "
                                            "budget) or dispatch fresh work with a new input hash"))
        mine, theirs = d.get("agent_id"), p.get("agent_id")
        mine, theirs = (mine.strip() if isinstance(mine, str) else ""), (theirs.strip() if isinstance(theirs, str) else "")
        retry = f"the retry packet `controller.py --task-root {root} --operation recover` prints"
        if not mine and not theirs:
            problems.append((StateConflict, f"{did} has no recorded agent and the request names none: a resume names the "
                                            "agent that holds the context. Pass `--agent-id <the id the Agent call "
                                            f"returned>`, or, when that agent is gone, continue with {retry}"))
        elif mine and theirs and mine != theirs:
            problems.append((StateConflict, f"{did} is held by agent {mine}, the request names {theirs}: a different agent "
                                            f"is a new dispatch, not a resume. Continue with {retry}"))
        latest = self._last_stop_sequence(self.store.read(), did)
        if p.get("stop_sequence") is None or p.get("stop_sequence") != latest:
            problems.append((StateConflict, f"stale stop: the request retires the stop at sequence {p.get('stop_sequence')}, "
                                            f"the latest stop of {did} is at {latest}. `{self._resume_door(did)}` builds the "
                                            "request again"))
        return problems

    def _config_cap(self, reader_name):
        """The cap a `config_contract` reader (THE reader of its key, AR-13) gives over the project's own config. No project, an absent
        or unreadable file, a config that is not an object: the reader's default (3), never a refusal. One body for both caps (AR-15)."""
        import config_contract
        project, config = self._project_root(), None
        if project is not None:
            try:
                config = config_contract.read_config_file(project)       # the one reader of the file (AR-13, axis 16)
            except (config_contract.ConfigUnreadable, OSError):
                config = None
        return getattr(config_contract, reader_name)(config)[0]

    def _parallel_cap(self):
        """How many S5 windows may run at once: `config_contract.parallel_windows` over the project's own config."""
        return self._config_cap("parallel_windows")

    def _window_beside_running(self, p, state, running, flagged=True):
        """May dispatch (or resumed dispatch) `p` run BESIDE the `running` dispatches (t-1937 TR3-4: S-1, S-3, B1)? True only when ALL hold:
        `p` carries `parallel_window` literally True (`flagged`; a resume is the driver's restart road and carries no flag, so its
        caller passes `flagged=False`); `p` and every running one are S5 WINDOW dispatches (stage S5, a role of `S5_WINDOW_ROLES`, not
        the plan); every scope is a non-empty list of case ids and is disjoint from `p`'s - the scope of a `returned_unaccepted`
        sibling too, though it is not counted; `len(running) + 1` is within the cap (`_parallel_cap`).

        Error direction: it may answer False needlessly (the old refusal then stands, which only costs a wait); it must never answer
        True for two dispatches that share a case, for a flag that is not the boolean True, for a scope it cannot read, or for any
        stage or role outside the clause - an unreadable thing is not disjoint (AR-28). Reads `p` with `.get`: it runs before
        `required`. Pure; never raises."""
        try:
            if flagged and p.get("parallel_window") is not True:
                return False

            def window_like(item):
                return (isinstance(item, dict) and item.get("stage") == "S5" and item.get("role") in S5_WINDOW_ROLES
                        and s5_part_of(item) != "plan")

            cases_of = _scope_cases
            if not window_like(p) or not running or not all(window_like(r) for r in running):
                return False
            mine = cases_of(p)
            if mine is None:
                return False
            # a returned-but-unaccepted S5 dispatch is not running (not counted), yet its cases are still the work of its window
            held = [r for r in (state.get("dispatches") or {}).values()
                    if isinstance(r, dict) and r.get("status") == RETURNED and r.get("stage") == "S5"
                    and s5_part_of(r) != "plan" and r.get("id") != p.get("id")]
            for other in list(running) + held:
                theirs = cases_of(other)
                if theirs is None or theirs & mine:
                    return False
            return len(running) + 1 <= self._parallel_cap()
        except Exception:
            return False

    def _walkers_cap(self):
        """How many S6 manual lanes may run at once: `config_contract.walkers` over the project's own config."""
        return self._config_cap("walkers")

    def _lane_beside_running(self, p, state, running, flagged=True):
        """May S6 manual lane `p` (or a resumed one) run BESIDE the `running` dispatches (t-2147 TR3-9d, the twin of
        `_window_beside_running`)? True only when ALL hold: `flagged` -> `p.get("walk_lane") is True` (a resume carries no flag, its
        caller passes `flagged=False`); `p` and every running one are stage S6, role `qa-runner`, `execution_kind` "manual"; every scope
        is a non-empty list of case ids and is disjoint from `p`'s (the scope of a `returned_unaccepted` S6 sibling too); `p` AND every
        running one carry `walk_lane` True and a `walk_actor` that is a string ("" = guest) - a record lacking either is an UNKNOWN
        account and admits nothing (critic B9); the `walk_actor` values are pairwise distinct; `len(running) + 1` is within the cap
        (`_walkers_cap`).

        Error direction: it may answer False needlessly (the old refusal stands: a wait); it must never answer True for two lanes that
        share a case or an account, for an account it cannot read, for a flag that is not the boolean True or for any stage, role or
        kind outside the clause - an unreadable thing is not distinct (AR-28). Reads `p` with `.get`: it runs before `required`.
        Pure; never raises."""
        try:
            if flagged and p.get("walk_lane") is not True:
                return False

            def lane_like(item):
                return (_manual_lane_like(item) and item.get("walk_lane") is True
                        and isinstance(item.get("walk_actor"), str))

            cases_of = _scope_cases
            if not running or not lane_like(p) or not all(lane_like(r) for r in running):
                return False
            mine = cases_of(p)
            if mine is None:
                return False
            held = [r for r in (state.get("dispatches") or {}).values()
                    if isinstance(r, dict) and r.get("status") == RETURNED and _manual_lane_like(r)
                    and r.get("id") != p.get("id")]
            for other in list(running) + held:
                theirs = cases_of(other)
                if theirs is None or theirs & mine:
                    return False
            actors = [p["walk_actor"]] + [r["walk_actor"] for r in running]
            if len(set(actors)) != len(actors):
                return False
            return len(running) + 1 <= self._walkers_cap()
        except Exception:
            return False

    def _resume_problems(self, p, state):
        """Every reason this `resume` request is refused, at once (R2); [] when the stopped dispatch goes on."""
        dispatches = state.get("dispatches") or {}
        d = dispatches.get(p.get("id")) if isinstance(p.get("id"), str) else None
        if not isinstance(d, dict):
            return [self._unknown_dispatch(p.get("id"), dispatches)]
        problems = self._resume_status_problems(d, dispatches)
        if problems:       # FR-59: the checks that read a stop did not run - say so, never read as a pass
            problems = self._noted(problems, "(the agent, budget and stop checks did not run: it is not a stopped dispatch)")
        else:
            problems = self._resume_stop_problems(d, p)
        beside = [o for o in dispatches.values() if o.get("status") == "running" and o is not d]
        running = sorted(str(o.get("id")) for o in beside)
        # t-1937 TR3-4 (S-3): a stopped S5 window resumes beside its running siblings (the driver's restart road: no flag, the
        # stage + role + scope + cap clause carries it). INVARIANT: a resume of anything else keeps the refusal, and two
        # dispatches never share a case.
        if running and not (self._window_beside_running(d, state, beside, flagged=False)
                            or self._lane_beside_running(d, state, beside, flagged=False)):
            problems.append((StateConflict, f"sequential task already has an active dispatch: {', '.join(running)}. Finish "
                                            f"or checkpoint it first (`story_step.py finish` / `story_step.py pause`), then "
                                            f"`{self._resume_door(d.get('id'))}`"))
        # AR-13: the ONE closure test of a dispatch (the retro S9 exempt, the unreadable file read by the state alone)
        closed = self._closed_dispatch_refusal(state, {"stage": d.get("stage")})
        if closed:
            problems.append((StateConflict, closed))
        return problems

    def build_resume_request(self, dispatch_id, agent_id=None):
        """The whole `resume` request for a stopped dispatch, built by code from the journal (R1) - never from a file.

        `stop_sequence` is the sequence of the dispatch's last `checkpoint` event and the idempotency key is built from it:
        a resume request is never reused across stops, and a rerun after success is a replay. A dispatch with no
        `checkpoint` event of its own (an imported record, a status `state_repair` set) has no stop to retire: refused, with
        the retry packet as the door - the key is never `resume:<id>:None`. The agent is the given one (stripped), else
        the record's, else absent; a given but blank one goes on unchanged so `validate` refuses its shape."""
        state = self.state()
        dispatches = state.get("dispatches") or {}
        identifier = str(dispatch_id or "").strip()
        problems = []   # K1: the id and the stop are independent facts of the call
        if not identifier:
            problems.append((ValueError, "--dispatch-id names the dispatch to resume; this story has: "
                                         + (", ".join(sorted(map(str, dispatches))) or "none")))
        dispatch = dispatches.get(identifier) if identifier else None
        if identifier and not dispatch:
            problems.append(self._unknown_dispatch(identifier, dispatches))
        stop = self._last_stop_sequence(self.store.read(), identifier) if dispatch else None
        if dispatch and stop is None:
            # a status with its own door says it (running, superseded, ...); a stopped record with no stop of its own, this
            problems += [(ValueError, status_problem) for _, status_problem in self._resume_status_problems(dispatch, dispatches)] or [
                (ValueError, f"no recorded stop to resume ({identifier} is {dispatch.get('status')} without a checkpoint of "
                             f"its own); continue it with the retry packet `controller.py --task-root {self.store.root} "
                             "--operation recover` prints")]
        self._raise_all(problems)
        request = {"id": identifier, "stop_sequence": stop, "stage": dispatch.get("stage"), "role": dispatch.get("role"),
                   "expected_revision": state.get("revision"), "idempotency_key": f"resume:{identifier}:{stop}"}
        recorded = dispatch.get("agent_id")
        if agent_id is not None:
            request["agent_id"] = str(agent_id).strip() or agent_id     # a blank one stays blank: `validate` refuses its shape
        elif isinstance(recorded, str) and recorded.strip():
            request["agent_id"] = recorded.strip()
        lease = (state.get("leases") or {}).get("orchestrator") or {}
        if lease.get("owner_session_id"):
            request["owner_session_id"] = lease["owner_session_id"]
        return request

    def _code_review_refusal(self, d, p):
        """The code critic's unreceipted window as a one-item problem list, or [] (not a critic,
        or nothing blocks). A person's recorded word passes a receipt, as at every other check."""
        if d.get("role") != "qa-code-critic":
            return []
        blocking, _ = self._passed_by_person(d.get("stage") or "S5", self._code_review_problems(p))
        if not blocking:
            return []
        # The marker is what a driver routes on: TP1-13797, 26.09 — this
        # refusal says in words that it is not the person's, and still reached
        # the conductor and then the person, because the table knew no such
        # wording. The waiver line stays: the repair is the role's, accepting the
        # window without it is the person's, and those are two different things.
        from role_cli import REPAIR_MARKER
        return [(StateConflict,
                 "; ".join(blocking) + ". These are the review's own receipts, not the "
                 f"person's to produce. {REPAIR_MARKER}. If a person accepts the window "
                 "without them: `"
                 + person_words.door(f"waiver.py --task {self._ticket()} --stage "
                                     f"{d.get('stage') or 'S5'} --block \"not receipted\"")
                 + "`.")]

    # --- SC1-14 B1b: the plan before the windows ---------------------------------------------------------------------------
    # The refusals below are collected (`_raise_all`) so a request meets every gap at once. A refusal a person's word can pass
    # (`plan before windows`, `plan form switch`, `plan review round`) is built by `_plan_refusal`; the others are the story's
    # state or the call's shape and name their door.

    def _plan_refusal(self, word, what, then):
        """`[(StateConflict, text)]` for one refusal of the plan order, `[]` when a person's recorded `word` for S5 passes it
        (FR-4: a check stops a silent pass, never an informed one). The line the word is matched against is `S5 <word>: <what>`
        and nothing else; `then` (the door, and the other words a conductor may put to the person) follows the match."""
        blocking, _ = self._passed_by_person("S5", [f"S5 {word}: {what}"])
        if not blocking:
            return []
        return [(StateConflict, blocking[0] + ". " + then + " If a person decides, the conductor records their words: `"
                 + person_words.door(f"waiver.py --task {self._ticket()} --stage S5 --block \"{word}\"") + "`.")]

    @staticmethod
    def _plan_rework_door(role, reason):
        """The command that sends `role` back over the plan (the door of the plan order's refusals): one form for the author's
        rework and the critic's look, which differ in the role and in what `--reason` says."""
        return (f"`controller.py --operation rework --stage S5 --role {role} --purpose {S5_PLAN} --cases <the cases> "
                f"--reason <{reason}> --brief`")

    def _before_windows(self, what, door):
        return self._plan_refusal(WORD_PLAN_BEFORE_WINDOWS, what, "Door: " + door + ".")

    @staticmethod
    def _run_mode():
        """The process asking: `driver` when the story driver set its variable, else what the host says or `desktop` (the form
        of an S5 with no record yet is decided by it, `s5_plan.mode`; the stamp `pipeline.run_mode` is never read, E37)."""
        import os
        import launch_card
        return os.environ.get(launch_card.RUN_MODE_ENV, "").strip() or "desktop"

    def _s5_plan_problems(self, p, state):
        """`[(class, message)]` of the plan order for a DISPATCH request (spec t-1246 B1b step 1), `[]` for every request this
        part does not concern. Two families: a request WITH `purpose: s5_plan` (a plan dispatch: its stage, role, kind of parent,
        whether the story may have a plan, whether its predecessor exists, the review cap), and a window request of an S5 whose
        form is `planned` (a window is written only against a plan that is there, read, clean, reviewed, not blocked and still
        the one reviewed). A story that began on the earlier form (`legacy`) is never asked for a plan by a window."""
        if p.get("purpose") == S5_PLAN:
            return self._s5_plan_request_problems(p, state)
        if p.get("stage") != "S5":
            return []
        return self._s5_window_problems(p, state)

    def _s5_plan_request_problems(self, p, state):
        import s5_plan as SP
        role, ticket = p.get("role"), self._ticket()
        if p.get("stage") != "S5" or role not in S5_PLAN_ROLES:
            return [(ValueError, f"purpose {S5_PLAN} requires a dispatch of S5 by qa-automator or qa-code-critic: it is the plan "
                                 f"and nothing else (here: stage {p.get('stage')}, role {role}). Dispatch without --purpose, or as "
                                 f"`story_step.py start --task {ticket} --stage S5 --role qa-automator --purpose {S5_PLAN}`")]
        problems, dispatches, root = [], state["dispatches"], self.store.root
        if p.get("rework_of"):
            parent = dispatches.get(p["rework_of"]) if isinstance(p["rework_of"], str) else None
            if s5_part_of(parent) != "plan":
                problems.append((ValueError, f"purpose {S5_PLAN} requires a rework of a plan dispatch (here: rework of "
                                             f"{p['rework_of']}, which is not one). A window is reworked without this word; the "
                                             f"plan is reworked from the plan dispatch of {role}"))
        try:
            form, why = SP.mode(root, state, self._run_mode())
            chain = SP.reviews(root, state)
        except SP.PlanUnreadable as exc:
            return problems + [(StateConflict, str(exc))]
        if form == SP.LEGACY:
            problems += self._plan_refusal(
                WORD_PLAN_FORM_SWITCH, f"S5 of this story began on the earlier form ({why})",
                "The windows of the earlier form stand and need no plan. A plan is begun only by the word that switches the form: "
                f"after it, `story_step.py start --task {ticket} --stage S5 --role qa-automator --purpose {S5_PLAN}`.")
        plans = [d for d in dispatches.values() if isinstance(d, dict) and d.get("stage") == "S5" and s5_part_of(d) == "plan"]
        live = [d for d in plans if d.get("status") == "accepted" and d.get("role") == role]
        rework = self._plan_rework_door(role, "what to mend")
        if role == "qa-code-critic" and not any(d.get("role") == "qa-automator" and d.get("status") == "accepted" for d in plans):
            problems.append((StateConflict, "the plan critic judges the author's plan, and no plan dispatch of qa-automator is accepted "
                                            f"yet; dispatch the author first: `story_step.py start --task {ticket} --stage S5 --role "
                                            f"qa-automator --purpose {S5_PLAN}`"))
        if live and not p.get("rework_of"):
            problems.append((StateConflict, f"the plan of {role} is accepted ({live[-1].get('id')}); the plan is reworked, not "
                                            f"dispatched again: {rework}"))
        if role == "qa-code-critic" and p.get("rework_of") and chain:
            kind = SP.next_look(chain)
            if SP.looks(chain)[kind] >= 1:
                said = ("the critic has already looked again at the blocker rows once"
                        if kind == "after_blocker" else "the critic has already looked once at cases added after the review")
                problems += self._plan_refusal(
                    WORD_PLAN_REVIEW_ROUND, f"{said}; one such look is the limit",
                    "The plan stands as the last review left it. The conductor puts the choice to the person: one more look "
                    f"(the word {WORD_PLAN_REVIEW_ROUND}, about one critic call) or the person changes the plan themselves.")
        return problems

    def _s5_window_problems(self, p, state):
        import s5_plan as SP
        root, ticket, run_mode = self.store.root, self._ticket(), self._run_mode()
        try:
            form, _why = SP.mode(root, state, run_mode)
        except SP.PlanUnreadable as exc:
            return [(StateConflict, str(exc))]
        if form != SP.PLANNED:
            return []
        problems = []
        start = f"`story_step.py start --task {ticket} --stage S5 --role qa-automator --purpose {S5_PLAN}`"
        rework = self._plan_rework_door("qa-automator", "what to mend")
        look = self._plan_rework_door("qa-code-critic", "what changed")
        critic = f"`story_step.py start --task {ticket} --stage S5 --role qa-code-critic --purpose {S5_PLAN}`"
        if run_mode == "driver":
            problems += self._plan_refusal(
                WORD_PLAN_FORM_SWITCH, "S5 of this story runs on the plan form, which the driver does not run (F-E)",
                "Door: the conductor runs this S5 (the plan, its review, then the windows); the driver keeps the stories that began "
                "on the earlier form.")
        try:
            plan = SP.load(root)
        except SP.PlanUnreadable as exc:
            problems += self._before_windows(f"the plan cannot be read: {exc}", "repair the file, then ask again")
            plan = False
        if plan is None:
            problems += self._before_windows(f"there is no {SP.PLAN_REL}: the plan comes before any window", start)
        elif plan:
            problems += self._plan_window_problems(p, plan, rework, ticket)
            planned = self._planned_cut_or_empty(state)     # the cut and the chains, read ONCE for (11) and (12)
            problems += self._window_split_problems(p, plan, state, planned)
            problems += self._grown_window_problems(p, state, planned)
        try:
            chain = SP.reviews(root, state)
        except SP.PlanUnreadable as exc:
            return problems + [(StateConflict, str(exc))]
        if not chain:
            return problems + self._before_windows("no accepted review of the plan: the code critic judges the plan before any window", critic)
        broken = [f"{e['dispatch']} ({e['unreadable']})" for e in chain if e["unreadable"]]
        if broken:
            return problems + self._before_windows("a review of the plan cannot be read: " + "; ".join(broken),
                                                   f"the critic completes the form and `finish` stamps the receipt ({critic})")
        last = chain[-1]
        if last["outcome"] == "blocked":
            ids = ", ".join(r["id"] for r in last["remarks"] if r["kind"] == "blocker")
            if len(chain) >= 2 and SP.has_blocker(chain[-2]):     # the LAST review is the re-look of a blocker, and it stands
                then = ("The plan was reviewed again after the rework and the blocker stands. The conductor puts three moves to the "
                        f"person, with the cost of each: the word {WORD_PLAN_BEFORE_WINDOWS} (the blocker goes into the windows as a "
                        f"remark; no more plan calls), the word {WORD_PLAN_REVIEW_ROUND} (one more round: about one call of the "
                        "author and one of the critic), or the person decides what to change.")
            else:
                then = f"Door: the author mends the blocker rows ({rework}), then the critic looks once at them ({look})."
            problems += self._plan_refusal(WORD_PLAN_BEFORE_WINDOWS, f"the plan review {last['dispatch']} blocks the plan ({ids})", then)
        if plan and last["plan_sha256"] != SP.plan_sha256(root):
            problems += self._before_windows(f"the plan changed after its last accepted review ({last['dispatch']})",
                                             f"the critic looks again ({look})")
        return problems

    def _plan_window_problems(self, p, plan, rework, ticket):
        """The window checks that read the plan itself: its gaps, whether it was written for the cases and the approved plan
        now in force, and whether it has the window's cases."""
        import s5_plan as SP
        root, problems = self.store.root, []
        # Step (d) of the check (an `extend` row's test is where the plan says) is NOT looked for in the project's files here: the
        # author's plan was accepted clean, the bytes are held by (7), and a window may legitimately rewrite the very test a later
        # row extends - window 2 must not be refused for it (t-1320 F-1). The accept of the plan and `--check` still look.
        findings = SP.check(root, self, files=False)
        if findings:
            problems += self._before_windows(
                f"the plan has {len(findings)} gap(s): " + "; ".join(findings[:5]) + ("; ..." if len(findings) > 5 else ""),
                f"the author mends them ({rework}); `python scripts/s5_plan.py --task {ticket} --check` lists them")
        try:
            scope_hash, gate_hash = SP.current_hashes(root, self)
        except SP.PlanUnreadable as exc:
            problems += self._before_windows(f"the plan cannot be compared with the cases and the approved plan now in force: {exc}",
                                             "fix the plan, then ask again")
        else:
            if (not gate_hash or not plan.get("gate_a_plan_hash")
                    or (plan.get("scope_hash"), plan.get("gate_a_plan_hash")) != (scope_hash, gate_hash)):
                problems += self._before_windows(
                    "the plan was written for other cases or another approved test plan (or the comparison could not be made): the "
                    "review does not cover the cases now in scope",
                    f"the author reworks the plan on the new cases ({rework}); the critic then looks at them once")
        known = {str(row.get("case")) for row in plan.get("cases") or [] if isinstance(row, dict)}
        missing = [str(case) for case in p.get("scope") or [] if str(case) not in known]
        if missing:
            problems += self._before_windows(f"the window's case(s) {', '.join(missing)} are not in the plan",
                                             f"the author adds them ({rework})")
        return problems

    def _window_split_problems(self, p, plan, state, planned=None):
        """(11) `[(class, message)]`: a FRESH window request whose scope cuts through the cases of a test of the plan (spec t-1314
        section 2 item 7, F-J5 (a)). The cases one test covers are written in one window, and the cut the controller hands out
        (`stage-scope`, `windows[]`) never splits them; a scope taken by hand can. Only a request that is not a continuation is
        asked - `rework_of`, `parent_retry` and `relaunch_of` carry the scope of the window they continue, which may be a part of
        a group (a narrow rework of a written window) - and only a plan with at least one test. The groups are the plan's tests
        over the STAGE SCOPE (`_planned_cut`) and the request's own cases - the domain the cut itself groups over (AR-13): the row
        a plan keeps for a case that left the scope ties nothing here, and a scope EQUAL to a window of the cut always passes (the
        gate is tied to the one producer, so its door cannot loop). A cut that cannot be read asks nothing: the plan gates beside
        it name that. The refusal is the plan order's - the word `plan before windows` passes it - and names the scope to take
        from `stage-scope`."""
        import s5_plan as SP
        tests = plan.get("tests") if isinstance(plan, dict) else None
        if p.get("rework_of") or p.get("parent_retry") or p.get("relaunch_of") or not (
                isinstance(tests, list) and any(isinstance(test, dict) for test in tests)):
            return []
        if planned is None:
            planned = self._planned_cut_or_empty(state)
        if not planned:
            return []
        scope = [str(case) for case in p.get("scope") or []]
        if any(set(scope) == set(window["scope"]) for window in planned["windows"]):
            return []
        problems = []
        for group in SP.case_groups(plan, list(dict.fromkeys(planned["scope"] + scope)), lambda case: False):
            inside = [case for case in group["cases"] if case in scope]
            if inside and len(inside) < len(group["cases"]):
                problems += self._before_windows(
                    f"the window's scope {', '.join(scope)} splits the cases of test(s) {', '.join(group['tests'])} "
                    f"({', '.join(group['cases'])}): a test is written in one window",
                    "take the window's scope from `controller.py --operation stage-scope` (`windows[]`)")
        return problems

    def _planned_cut(self, state):
        """`None` for an S5 that is not on the plan form, else `{"plan", "scope", "windows", "written"}`: THE one computation of the
        cut and of the chains that (11), (12) and (13) read (AR-13; SC1-14 FJ fix Q-a). `scope` is the stage's S5 scope
        (`_cases_by_disposition`), `windows` the cut `s5_windows_for` hands out - with `accepted_by` set the way `stage_scope` sets it
        - and `written` the chains (`_written_windows`) its first windows are. A caller that holds the result reads the cut once
        per validate call; nothing is kept between calls. A plan or a state that cannot be read RAISES (`PlanUnreadable`,
        `StateConflict`, `ValueError`, `OSError`), and so does a cut that fails: this never falls back to the cut by cases, whose
        window numbers belong to no chain (AR-28)."""
        import s5_plan as SP
        if SP.mode(self.store.root, state, self._run_mode())[0] != SP.PLANNED:
            return None
        plan = SP.load(self.store.root)
        mapping, dispositions, _basis = self._case_rows(state)
        scope = self._cases_by_disposition(mapping, dispositions)["automate"]
        written = self._written_windows(state, scope)
        windows, _cut = self.s5_windows_for(plan, state, scope, mapping, written)
        self._mark_accepted_by(state, "S5", windows)
        return {"plan": plan, "scope": scope, "windows": windows, "written": written}

    def _planned_cut_or_empty(self, state):
        """`_planned_cut` for the gates that ask nothing of a cut they cannot read: `{}` for an S5 that is not on the plan form and
        for a cut that cannot be made (the plan gates beside them name that); never `None`."""
        import s5_plan as SP
        try:
            return self._planned_cut(state) or {}
        except (SP.PlanUnreadable, StateConflict, ValueError, OSError, TypeError, KeyError, AttributeError):
            return {}

    def _grown_cut(self, state, planned=None):
        """`[{"index", "scope", "grown", "added", "grew", "tests", "accepted_by", "written"}]`: the windows of the S5 cut on the plan form
        as the gates of a grown window read them (spec t-1314 section 2 items 6 and 12, FJ-C). `scope` is W' (the author's chain and the
        cases that joined it), `grown` the cases of W' the chain has not been sent back over, `grew` is True when the chain holds
        cases its root did not (the author reworked the window with a new case), `added` the cases of either kind, `tests` the ids of
        the plan's tests that list one of them, `accepted_by` the cut's own (role -> accepted dispatch over all of W'), `written` whether
        the window is an author's chain. `[]` for an S5 that is not on the plan form. THE one reading of the cut for (12) and (13): the
        cut and the chains are `_planned_cut`'s - one producer, so a window and its chain are the same number by construction. A plan or a
        state that cannot be read RAISES (`PlanUnreadable`, `StateConflict`, `ValueError`, `OSError`): the caller decides what an
        unknown is, the cut never answers "nothing grew" for a plan it could not read. `planned` is a `_planned_cut` the caller holds."""
        import s5_plan as SP
        if planned is None:
            planned = self._planned_cut(state)
        if not planned:
            return []
        windows, written, plan = planned["windows"], planned["written"], planned["plan"]
        records = {_dispatch_ident(d, name): d for name, d in (state.get("dispatches") or {}).items() if isinstance(d, dict)}
        out = []
        for window in windows:
            index = window.get("index")
            chain = written[index - 1] if isinstance(index, int) and 0 < index <= len(written) else None
            grown = [str(case) for case in window.get("grown") or []]
            extra = []
            if chain is not None:
                root_scope = records.get(chain["root"], {}).get("scope")
                own = {str(case) for case in root_scope} if isinstance(root_scope, list) else set()
                extra = [case for case in chain["scope"] if case not in own]
            added = list(dict.fromkeys(extra + grown))
            out.append({"index": index, "scope": [str(case) for case in window.get("scope") or []], "grown": grown, "added": added,
                        "grew": bool(extra), "tests": sorted(set(SP.tests_tying(plan, added, 1))),
                        "accepted_by": dict(window.get("accepted_by") or {}), "written": chain is not None})
        return out

    @staticmethod
    def _grown_door(window):
        """The author's rework of a window: the exact command (spec t-1314 section 2 item 12.5). For a window with added cases its cause is
        `ticket_changed`, a round that is not about a defect of the test, so it spends none of the window cap; a written window with
        nothing added is reworked for the reason the author is given."""
        cases = ", ".join(window["added"])
        tests = ", ".join(window["tests"]) or "of the plan"
        if not cases:
            return (f"`controller.py --operation rework --stage S5 --role qa-automator --cases {','.join(window['scope'])} "
                    "--reason <what to change in this window> --brief`")
        return (f"`controller.py --operation rework --stage S5 --role qa-automator --cases {','.join(window['scope'])} "
                f"--cause ticket_changed --reason \"case(s) {cases} added to S5 after the plan review; test(s) {tests} extend "
                "this window\" --brief`")

    def _grown_window_problems(self, p, state, planned=None):
        """(12) `[(class, message)]`: a window request of an S5 on the plan form that goes round the author of a grown window (spec
        t-1314 section 2 items 6 and 12.7, FJ-C). A window is grown while the cases its plan tests added to it have not been sent
        back to its author (`grown`, cleared the moment a live member of the author's chain covers them). Two requests are held,
        both only when their scope meets the grown window W': an AUTHOR dispatch whose scope lacks any of the grown cases (the
        window would be rewritten without the new case), and a CRITIC dispatch of any scope (it would review W' before its author
        has covered the new cases). A request from a person's words (`person_words`) is not held: the words are not silence (F5);
        the close of S5 still is (13). The refusal is the plan order's - the word `plan before windows` passes it - and names the
        author's rework, command and cause. A cut that cannot be read asks nothing here: the plan gates beside it name that.

        A window is its author's chain (L1, Lead decision 27.10.2026): a FRESH author dispatch - none of `rework_of`, `parent_retry`,
        `relaunch_of` - whose scope meets a WRITTEN window is held too, grown or not, with the rework of that window as the door; a
        fresh dispatch over cases no written window holds is not. Both pass the same person's word. `planned` is a `_planned_cut` the
        caller holds (one validate call reads the cut once)."""
        if p.get("person_words") or p.get("role") not in ("qa-automator", "qa-code-critic") or p.get("purpose") == S5_PLAN:
            return []
        if planned is None:
            planned = self._planned_cut_or_empty(state)
        if not planned:
            return []
        windows = self._grown_cut(state, planned)
        asked = {str(case) for case in p.get("scope")} if isinstance(p.get("scope"), list) else set()
        fresh = p.get("role") == "qa-automator" and not (p.get("rework_of") or p.get("parent_retry") or p.get("relaunch_of"))
        problems = []
        for window in windows:
            if fresh and window["written"] and asked & set(window["scope"]):
                problems += self._before_windows(
                    f"window {window['index']} is written ({', '.join(window['scope'])}) and a window is its author's chain: a fresh "
                    f"dispatch over {', '.join(sorted(asked & set(window['scope'])))} would write its tests outside that chain",
                    "the author's rework of the window: " + self._grown_door(window))
                continue
            if not window["grown"] or not asked & set(window["scope"]):
                continue
            door = self._grown_door(window)
            new, tests = ", ".join(window["grown"]), ", ".join(window["tests"]) or "the plan"
            if p.get("role") == "qa-automator":
                if set(window["grown"]) <= asked:
                    continue
                what = f"window {window['index']} grew after the plan review by {new} (test(s) {tests}): its author reworks it with them first"
            else:
                what = f"the critic of window {window['index']} waits for its author to cover {new} (test(s) {tests})"
            problems += self._before_windows(what, door)
        return problems

    def _grown_close_problems(self, d, p, state):
        """(13) `[(class, message)]`: S5 does not close while a window that grew after the plan review has not been covered by BOTH its
        author and its critic over all of W' (spec t-1314 section 2 item 12.7, FJ-C). Asked of the accept of an S5 window record with
        `stage_complete: true`, on the plan form only; a window that did not grow, a plan record and a story on the earlier form
        are accepted as before. A window needs the pair when it is `grown` or its chain grew (`grew`): the author's rework that
        covers the new case clears `grown`, and the critic of the OLD window never covers W'. The accepted dispatch itself counts
        for its role when its scope holds W'. Held for a person's words too (they are not silence); the word `plan before windows`
        passes it. An unreadable cut is not a pass at this boundary: it is refused with the reason and a door."""
        if d.get("stage") != "S5" or s5_part_of(d) == "plan" or not p.get("stage_complete"):
            return []
        import s5_plan as SP
        try:
            windows = self._grown_cut(state)
        except (SP.PlanUnreadable, StateConflict, ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
            return self._before_windows(f"whether a window of S5 grew after the plan review cannot be established ({exc})",
                                        "repair what the error names (the plan file, the approved scope), then accept again")
        mine = {str(case) for case in d.get("scope") or []}
        ticket, problems = self._ticket(), []
        for window in windows:
            if not (window["grown"] or window["grew"]):
                continue
            have = dict(window["accepted_by"])
            if set(window["scope"]) <= mine:
                have.setdefault(str(d.get("role")), str(d.get("id")))
            missing = [role for role in ("qa-automator", "qa-code-critic") if role not in have]
            if not missing:
                continue
            names = " and ".join({"qa-automator": "its author", "qa-code-critic": "its critic"}[role] for role in missing)
            cases = ", ".join(window["scope"])
            doors = []
            if "qa-automator" in missing:
                doors.append("the author reworks the window with the new case(s) and that rework is accepted: " + self._grown_door(window))
            if "qa-code-critic" in missing:
                wanted = ",".join(window["scope"])
                ran = any(isinstance(r, dict) and r.get("stage") == "S5" and r.get("role") == "qa-code-critic"
                          and r.get("status") == "accepted" and s5_part_of(r) != "plan"
                          and {str(case) for case in r.get("scope") or []} & set(window["scope"])
                          for r in (state.get("dispatches") or {}).values())
                doors.append(
                    f"the critic reviews the window over {cases}: " + (
                        f"its critic is reworked over all of it, `controller.py --operation rework --stage S5 --role qa-code-critic "
                        f"--cases {wanted} --reason <review the cases added to the window> --brief`" if ran else
                        f"no critic has reviewed it, `story_step.py start --task {ticket} --stage S5 --role qa-code-critic --scope {wanted}`"))
            problems += self._before_windows(
                f"S5 cannot close: window {window['index']} grew after the plan review by {', '.join(window['added'])} (test(s) "
                f"{', '.join(window['tests']) or 'of the plan'}) and {names} {'have' if len(missing) > 1 else 'has'} not covered all of {cases}",
                "; then ".join(doors))
        return problems

    def _s5_plan_accept_problems(self, d, p, state):
        """`[(class, message)]` of the accept of a PLAN dispatch (B1b step 2), `[]` for a window record and for a plan that holds.
        A plan never closes S5; the author's plan has no gap (`s5_plan.check`) and a rework changes only the rows the last review
        named (unless a person's words ask otherwise); the critic's review reads, agrees with itself, was stamped on the bytes
        now on disk and reuses no remark id of the chain. Every refusal is the role's to mend: the conductor returns it whole."""
        if s5_part_of(d) != "plan":
            return []
        import s5_plan as SP
        from role_cli import REPAIR_MARKER
        root, problems = self.store.root, []
        end = f". {REPAIR_MARKER}: return it to {d.get('role')} in one message"
        if p.get("stage_complete"):
            problems.append((StateConflict, f"a plan never closes S5 (accepting {d.get('id')} with stage_complete: true): accept it with "
                                            "`story_step.py finish` and no `--complete`, the windows follow" + end))
        if d.get("role") == "qa-automator":
            findings = SP.check(root, self)
            if findings:
                problems.append((StateConflict, f"the plan has {len(findings)} gap(s): " + "; ".join(findings[:6])
                                 + ("; ..." if len(findings) > 6 else "") + end))
            elif d.get("rework_of") and not d.get("person_words"):
                # A person's word on THIS dispatch lifts the bound (P13). The word is read by `contract.stage_override_values` (the
                # ONE reader of a prefixed word, AR-13): the id is compared for EQUALITY, so the word given for `S5-qa-automator-5`
                # is not a match inside `S5-qa-automator-50`, and no `*` reaches it; a record that cannot be read leaves the
                # refusal (FR-59).
                prefix, word = "plan rows by person:", f"plan rows by person: {d.get('id')}"
                try:
                    import contract
                    pipeline = json.loads((self.store.root / "pipeline.json").read_text(encoding="utf-8"))
                    said = [e for v, e in contract.stage_override_values(pipeline, prefix) if v == str(d.get("id"))]
                except (OSError, ValueError):
                    said = []
                if said:
                    self._record_person_pass("S5", d.get("id"), [{"error": f"S5 {word}", "decision": said[0].get("decision"),
                                                                  "by": said[0].get("by")}])
                else:
                    problems += self._plan_rework_rows_problems(
                        state, end, person_door=person_words.door(f"waiver.py --task {self._ticket()} --stage S5 --block \"{word}\""))
        elif d.get("role") == "qa-code-critic":
            problems += self._plan_review_problems(d, state, end)
        return problems

    def _plan_rework_rows_problems(self, state, end, person_door=""):
        """E1 and the one rule of the rows (spec t-1314 FJ-C step 3): a rework of the author's plan (not a person's words) changes only
        the rows of (a) the cases the last accepted review's blockers bind, (b) the cases added after that review, which it has not
        seen, and (c) their TEST NEIGHBOURS - the cases that share a test with a new case (the plan as it stands now) or with a
        case the rework dropped (the receipt's `tests -> cases` map and the plan as it stands): adding or dropping a case moves
        the row of every case its tests touch, and that is not a change the author chose. The rest of the plan stays as the critic
        saw it. A blocker that binds no case (about the whole plan) holds no row back. A receipt with no `tests` map (a review
        before t-1340) reads the neighbours of a dropped case by the new plan alone, and a refusal says so."""
        import s5_plan as SP
        try:
            chain, plan = SP.reviews(self.store.root, state), SP.load(self.store.root)
        except SP.PlanUnreadable as exc:
            return [(StateConflict, str(exc))]
        if not chain or plan is None:
            return []
        last = chain[-1]
        if last["unreadable"]:
            return [(StateConflict, f"the rows the rework may change cannot be told: the review {last['dispatch']} cannot be read "
                                    f"({last['unreadable']})" + end)]
        changed, new = SP.moved_cases(plan, last["rows_sha"])
        bound = SP.blocker_cases(plan, last["remarks"], last.get("tests"))   # a test the blocker names is read by the receipt's map
        if bound is None:
            return []
        dropped = set(last["rows_sha"]) - set(SP.rows_sha(plan))
        near = SP.test_neighbours(plan, sorted(new | dropped))
        stamp_tests = last.get("tests")
        if isinstance(stamp_tests, dict):       # the receipt's tests -> cases map is the plan the dropped case was in
            near |= SP.test_neighbours({"tests": [{"cases": listed} for listed in stamp_tests.values()]}, sorted(dropped))
        extra = sorted(changed - bound - new - near)
        if extra:
            note = "" if isinstance(stamp_tests, dict) else (
                f" (the receipt of {last['dispatch']} keeps no tests map, so the neighbours of a dropped case are read by the new plan alone)")
            return [(StateConflict, f"the rework changed the rows of {', '.join(extra)}, which no blocker of {last['dispatch']} names and "
                                    "which share no test with a new or a dropped case; only the blocker rows, the new cases and the cases "
                                    "that share a test with a new or dropped case change, the rest of the plan stays as the critic saw it"
                                    + note + (f". If a person asked for these rows to change, record their words: `{person_door}` and "
                                              "finish again; a rework built with `--words-file` is not bound either" if person_door else "")
                                    + end)]
        return []

    def _plan_review_problems(self, d, state, end):
        import s5_plan as SP
        root = self.store.root
        try:
            element, chain, now = SP.review_of(root, d["id"]), SP.reviews(root, state), SP.plan_sha256(root)
        except SP.PlanUnreadable as exc:
            return [(StateConflict, str(exc))]
        if element["unreadable"]:
            return [(StateConflict, f"the review {d['id']} cannot be read: {element['unreadable']}" + end)]
        problems = []
        disagree = SP.verdict_problem(element)
        if disagree:
            problems.append((StateConflict, f"the review contradicts itself: {disagree}" + end))
        if now is None or element["plan_sha256"] != now:
            problems.append((StateConflict, f"the plan changed after this review was stamped ({d['id']} saw other bytes than "
                                            f"{SP.PLAN_REL} holds now): the critic looks again at the current plan" + end))
        used = {r["id"] for e in chain for r in e["remarks"]}
        repeated = sorted(r["id"] for r in element["remarks"] if r["id"] in used)
        if repeated:
            problems.append((StateConflict, f"remark id(s) {', '.join(repeated)} repeat the ids of an earlier review of the plan: "
                                            "a look after a review continues the numbering (PR-n)" + end))
        missed = self._plan_look_missed(d, chain, root)
        if missed:
            previous, missing, moved, unread = missed
            scoped = ", ".join(str(case) for case in d.get("scope") or []) or "no case"
            what = (f"the look scoped {scoped} but the previous review {previous} cannot be read ({unread}), so which rows moved "
                    "since is not known: the stamp would cover rows nobody looked at, and a look then covers the whole plan"
                    if unread else
                    f"the look scoped {scoped} but rows of {', '.join(missing)} changed since {previous}: the stamp would cover "
                    "rows nobody looked at")
            then = ("Door: the critic looks again over all the rows it must cover, "
                    f"`controller.py --operation rework --stage S5 --role qa-code-critic --purpose {S5_PLAN} "
                    f"--cases {','.join(moved)} --reason <what changed> --brief`")
            line = f"S5 {WORD_PLAN_BEFORE_WINDOWS}: {what}"
            if d.get("person_words"):       # P13: the look was ordered in the person's own words; the pass is kept, not silent
                self._record_person_pass("S5", d.get("id"), [{"error": line, "by": "human",
                                                              "decision": "the look is a rework ordered in the person's own words"}])
            else:
                blocking, passed = self._passed_by_person("S5", [line])
                if blocking:
                    problems.append((StateConflict, blocking[0] + ". " + then + end + " If a person decides, the conductor records "
                                     "their words: `" + person_words.door(f"waiver.py --task {self._ticket()} --stage S5 --block "
                                                                          f"\"{WORD_PLAN_BEFORE_WINDOWS}\"") + "`."))
                else:
                    self._record_person_pass("S5", d.get("id"), passed)
        return problems

    def _plan_look_missed(self, d, chain, root):
        """`(previous review id, [cases missed], [cases the look must cover], reason the previous review is unread or "")` or None. F3
        (spec t-1314 FJ-C step 4): a NARROW look - the critic's rework of its own review (`rework_of`) - scopes the cases whose
        rows moved since the previous accepted review (`moved_cases`: changed and new); otherwise its stamp would cover rows nobody
        looked at (the accept stamps the whole plan). The first review is a full look and is not asked. The third item is the whole set
        the look must cover (moved rows, or the whole plan when the previous review cannot be read - an unknown is never a pass, M5),
        so the door names it and following the door once passes (B2). A plan that cannot be read asks nothing here: the plan's own
        refusals name it. The door is the critic's rework."""
        import s5_plan as SP
        previous = [e for e in chain if e["dispatch"] != d.get("id")]
        if not d.get("rework_of") or not previous:
            return None
        try:
            plan = SP.load(root)
        except SP.PlanUnreadable:
            return None
        if plan is None:
            return None
        unread = previous[-1]["unreadable"]
        changed, new = SP.moved_cases(plan, {} if unread else previous[-1]["rows_sha"])    # no stamp: every case is one nobody looked at
        moved = sorted(changed | new)
        missing = sorted((changed | new) - {str(case) for case in d.get("scope") or []})
        return (previous[-1]["dispatch"], missing, moved, str(unread or "")) if missing else None

    def _s5_completion_problems(self, d, p, state, review):
        """Why this S5 completion, which claims the stage is done, cannot be recorded:
        `[(class, message)]`, [] when it can. `review` is the code critic's receipts item (tier 3a).

        TIERS - a check whose input a failing check makes meaningless does not run, and the
        refusal says so; every other check is collected, so one refusal carries the lot.
          0  `unresolved` without a `reason` is refused before this runs (a malformed call).
          1  no `window` object: stops. Every other check reads the record. The receipts (a)
             do not read it, so they stand in front of this item.
          2  `window_shape_errors`: stops with the whole shape list. The field checks read these
             fields. The receipts (a) stand in front of this item too.
          3  collected: receipts (a, first in every tier), scope map keys (b), empty instances (c), coverage (d),
             schema (e), author/critic (f), mechanical round (g), per-instance refs (h), hash,
             revision and quality checks (i). Within ONE instance (h) stops at its first failure
             (broken refs make the hashes meaningless); between instances it collects. A helper
             that refuses ends the tier with its own text as the last item.
          4  `validate_window` (the gap checks), only when 0-3 collected nothing: it sees exactly the
             windows it saw when every earlier check was a raise, so it cannot fall over a field
             an earlier check was refusing (an entry of `quality_receipts` without an `id`)."""
        window = p.get("window")
        if not isinstance(window, dict):
            missing = ("S5 completion needs a window acceptance record; "
                       "`window_record.py --task <TICKET> --dispatch "
                       + str(d.get("id")) + "` builds it from the manifest, "
                       "the run blocks and the receipts, and "
                       "`--window <path>` passes it here")
            # The factory's standing rule, which this one gate did not follow: a check
            # stops a silent pass, never an informed one. Live TP1-13797 run 5 —
            # the critic's probe writes a receipt `window_record.py` cannot read, so no
            # record could be built for the last window at all, and there was no key: the
            # person's word lifted the dispatch block and the stage still would not
            # close. `stage_overrides[]` already holds the words; this reads them like
            # every other check does.
            blocking, passed = self._passed_by_person("S5", [missing])
            if blocking:
                # StateConflict, not ValueError: the request is well formed and the
                # story's state is what says no. `StateConflict` IS a `ValueError`,
                # so nothing that catches the wider class notices - but the walk of
                # every block (design/controller-blocks.md) reads the class as the
                # difference between "you called this wrong" and "the story is not
                # ready", and this block is the second kind.
                return review + self._noted(
                    [(StateConflict, blocking[0])],
                    "(the other window checks did not run: they read the record)")
            if review:
                return review  # the word passed the missing record, not the unreceipted review
            self._record_person_pass("S5", d.get("id"), passed)
            print("S5 window acceptance record: passed by a person's recorded word — "
                  + str((passed[0] or {}).get("decision") or "")[:300])
            return []
        from contract import PROBE_MISSING_ERROR, window_shape_errors
        # EVERY structural gap at once, before any field-by-field check. On
        # TP2-2553 the shape was learned one refusal at a time, and the
        # critic's last interval ran close to two hours for it.
        shape = window_shape_errors(window)
        if shape:
            door = ""
            # The door follows the OUTCOME of the instance the shape line names (HF2-4b, FR-2): the person's word for
            # a probe that cannot run is for a test that ran GREEN (FR-18); the door of a RED one is its manifest row.
            suffix = ": " + PROBE_MISSING_ERROR
            outcomes = {str(i.get("instance_id") or ""): i.get("outcome")
                        for i in window.get("instances") or [] if isinstance(i, dict)}
            owed = [line[:-len(suffix)] for line in shape if line.endswith(suffix)]
            if any(outcomes.get(label) == "passed" for label in owed):
                # HF1-14: a probe that cannot run here is passed only by the person's word for THAT instance, recorded
                # by the orchestrator (the critic returns the item); this refusal stays a stop and reads no word.
                # F4 (t-2007): the door follows what each owed test's probe record says - the critic's `--judge`, the person's
                # `probe not proved:` word, or this `probe gap:` word - never the word for a test it cannot close
                from window_record import PROBE_GAP_RECORD, probe_gap_keys_line, probe_word_door  # the ONE text of these doors (AR-13)
                door = probe_word_door(
                    window, self.store.root, self._ticket(),
                    " A probe that cannot run here is passed only by the person's word for the case key of that test, "
                    "recorded by the orchestrator: `"
                    + PROBE_GAP_RECORD.replace("<T>", self._ticket())
                    + "`; then `window_record.py` builds the record again."
                    + probe_gap_keys_line(window, self.store.root))
            red = [label for label in owed if outcomes.get(label) == "failed"]
            if red:
                from window_record import RED_ROW_DOOR  # the ONE text of this door (AR-13)
                door += f" For {', '.join(red)} (ran red): {RED_ROW_DOOR}."
            return review + self._noted(
                [(ValueError, "S5 window record is incomplete: " + "; ".join(shape)
                  + ". `window_record.py --task " + self._ticket()
                  + " --dispatch " + str(d.get("id")) + "` writes every "
                  "one of these from what is already on disk." + door)],
                "(the field checks below did not run: they read these fields)")
        problems = list(review)
        try:
            self._s5_collect(d, p, state, window, problems)
        except _TierEnds as end:
            cls, message = end.args
            problems = self._noted(problems + [(cls, message)], "(the checks after it did not run)")
        problems = self._merged(problems)
        if problems:
            return self._noted(
                problems, "(the window's gap checks - quality receipts, instance outcomes, reviews - "
                          "did not run: they read fields the items above refuse)")
        return self._s5_gap_problems(d, p, window)

    def _open_windows_problems(self, d, p, state):
        """`[(class, message)]` for the accept field `open_windows` (t-1937 TR3-4, B3), `[]` when it is absent or names real windows.

        The field is the scheduler's word that OTHER windows of the stage are still open, which is why accepting this one with
        `stage_complete: false` does not leave the stage with no role to close it. It is a list of case ids, each a case of a window
        of `stage_scope` that is NOT this dispatch's own (a window meeting this dispatch's cases is its own), and it does not travel
        with `unresolved` (that pair already says why the stage stays open). Every refusal names the windows the story has and the
        door (FR-1, FR-2). With `stage_complete: true` the field lifts nothing - the refusal it lifts is for `false` only. A stage
        whose windows cannot be read has none to name: every name is then refused with that said (AR-28, FR-59)."""
        if "open_windows" not in p:
            return []
        from detector_verdict import named
        given, stage = p.get("open_windows"), str(d.get("stage") or "")
        own = {str(case) for case in d.get("scope") or []}
        try:
            windows = self.stage_scope(stage, state).get("windows") or []
        except (StateConflict, ValueError, OSError):
            windows = []
        others = [sorted({str(case) for case in w.get("scope") or []}) for w in windows
                  if isinstance(w, dict) and not own & {str(case) for case in w.get("scope") or []}]
        others = [w for w in others if w]
        real = {case for w in others for case in w}
        have = ("the other windows of " + stage + " are: " + "; ".join(", ".join(w) for w in others)
                if others else f"no other window of {stage} could be read from the approved plan")
        door = (f"Door: `story_step.py finish --task {self._ticket()} --dispatch-id {d.get('id')} --digest \"<digest>\" "
                "--not-complete --open-windows <cases of the windows still open>`")
        if p.get("unresolved"):
            return [(ValueError, "open_windows requires a plain --not-complete, not unresolved: unresolved already says why "
                                 f"{stage} stays open. Drop one of the two. {door}")]
        if (not isinstance(given, list) or not given
                or not all(isinstance(case, str) and case.strip() for case in given)):
            return [(ValueError, f"open_windows must be a non-empty list of case ids, one or more of each other window still open "
                                 f"(got {given!r}); {have}. {door}")]
        bad = [case for case in given if case not in real]
        if bad:
            why = "this dispatch's own cases do not count" if set(bad) & own else "no such window"
            return [(ValueError, f"open_windows requires cases of another window of {stage}; {named(bad, SCOPE_SHOWN)} "
                                 f"{'is' if len(bad) == 1 else 'are'} not one ({why}); {have}. {door}")]
        return []

    def _s5_running_beside_problems(self, d, state):
        """`[(class, message)]` when this S5 completion would close the stage while another S5 dispatch is `running` (t-1937 TR3-4,
        item 5), else `[]`. The code gate UNDER the driver's own close predicate (`s5_open_windows`): never reached when the
        predicate is right, and the one thing between a wrong predicate and a stage closed over a window at work. The refusal names
        the running dispatches and their cases and the door (`--not-complete --open-windows <their cases>`); a person's recorded
        word (`close beside a running window`) passes it like any S5 close refusal (P13), and the pass is recorded (FR-4)."""
        refused = self._beside_running_refusal(d, state, "S5", lambda o: isinstance(o, dict) and o.get("stage") == "S5",
                                               WORD_CLOSE_BESIDE_RUNNING)
        if refused is None:
            return []
        blocking, cases = refused
        return [(StateConflict, blocking[0] + ". The stage closes with the last window to finish: finish this one with "
                 f"`--not-complete --open-windows {','.join(cases) or '<the cases of the running windows>'}` "
                 f"(`story_step.py finish --task {self._ticket()} --dispatch-id {d.get('id')} --digest \"<digest>\" "
                 "--not-complete --open-windows ...`). If a person decides the stage closes now, the conductor records their words: `"
                 + person_words.door(f"waiver.py --task {self._ticket()} --stage S5 --block \"{WORD_CLOSE_BESIDE_RUNNING}\"") + "`.")]

    def _beside_running_refusal(self, d, state, stage, like, word):
        """The shared body of the S5 and S6 close backstops (AR-15): `(blocking lines, cases of the running ones)` when `d`
        would complete `stage` while another dispatch `like` selects is `running` and no person's recorded `word` passes it, else
        None; a pass by the word is recorded (FR-4). Each stage keeps only its door sentence, raised on `blocking[0]` - the list
        `_passed_by_person` has filtered, the shape `tools/controller-blocks-gen.py` routes to the person."""
        running = sorted((o for o in state["dispatches"].values()
                          if like(o) and o.get("status") == "running" and o.get("id") != d.get("id")),
                         key=lambda o: str(o.get("id")))
        if not running:
            return None
        cases = sorted({str(case) for o in running for case in o.get("scope") or []})
        what = (f"{d.get('id')} would complete {stage} while {', '.join(str(o.get('id')) for o in running)} "
                f"{'is' if len(running) == 1 else 'are'} still running"
                + (f" (cases {', '.join(cases)})" if cases else ""))
        blocking, passed = self._passed_by_person(stage, [f"{stage} {word}: {what}"])
        if not blocking:
            self._record_person_pass(stage, d.get("id"), passed)
            return None
        return blocking, cases

    def _s6_running_beside_problems(self, d, state):
        """`[(class, message)]` when this S6 completion would close the stage while another S6 manual lane is `running` (t-2147
        TR3-9d), else `[]`. The twin of `_s5_running_beside_problems` (one shared body, `_beside_running_refusal`): the refusal names
        the running lanes and their cases and the door (wait, or finish this lane with `--not-complete`, the S5 twin's road - a
        paused lane is not a finished one); a person's recorded word (`close beside a running lane`) passes it as any close
        refusal (P13), and the pass is recorded (FR-4)."""
        refused = self._beside_running_refusal(d, state, "S6", _manual_lane_like, WORD_CLOSE_BESIDE_RUNNING_LANE)
        if refused is None:
            return []
        blocking, _ = refused
        return [(StateConflict, blocking[0] + ". The stage closes with the last lane to finish: wait for the running lane, or finish "
                 f"this one without closing the stage (`story_step.py finish --task {self._ticket()} --dispatch-id {d.get('id')} "
                 "--digest \"<digest>\" --not-complete`). If a person decides the stage closes now, the conductor records their words: `"
                 + person_words.door(f"waiver.py --task {self._ticket()} --stage S6 --block \"{WORD_CLOSE_BESIDE_RUNNING_LANE}\"") + "`.")]

    def _tier3_call(self, helper, *args):
        """Run a helper of the collecting tier; its refusal ends the tier as the last item."""
        try:
            return helper(*args)
        except (StateConflict, ValueError) as exc:
            raise _TierEnds(StateConflict if isinstance(exc, StateConflict) else ValueError,
                            str(exc)) from exc

    def _s5_collect(self, d, p, state, window, problems):
        """Tier 3 of `_s5_completion_problems`: append every independent defect to `problems`."""
        scope_instances = window["scope_instances"]  # tier 2: a nonempty map of lists
        if set(scope_instances) != set(d.get("scope") or []):
            problems.append((ValueError, "S5 window needs a nonempty exact scope_instances map"))
        # A case with no instance at all. On TP1-13797 (FB-10) TC-014's every
        # Then was `impossible` — no observable outside the caller's own memory —
        # and the closing window, scoped to that one case, had no representable
        # shape: an instance list may not be empty, and every listed instance
        # needs a fingerprint or a handoff. The manifest already says what the
        # case is (`unresolved[]`, reason `impossible` or `handed_to_person`);
        # the completion repeats it out loud (`unresolved` + `reason`), and only
        # then is an empty list a fact rather than a hole. Every other case keeps
        # the rule above.
        empty = sorted(case for case, ids in scope_instances.items() if not ids)
        if empty:
            without = self._tier3_call(self._cases_without_instances)
            stray = [case for case in empty if case not in without]
            if stray or not (p.get("unresolved") and p.get("reason")):
                problems.append((
                    ValueError,
                    "S5 window needs a nonempty exact scope_instances map: "
                    + ", ".join(empty) + " lists no instance. A case may list none "
                    "only when automation-manifest.json `unresolved[]` carries it "
                    "with reason `impossible` or `handed_to_person`"
                    + (" (it does not carry " + ", ".join(stray) + ")" if stray else "")
                    + " and the completion names it in `unresolved` with a `reason`"))
        expected_instances = [str(i) for ids in scope_instances.values() for i in ids]
        actual_instances = [str(item.get("instance_id") or "")
                            for item in window.get("instances") or [] if isinstance(item, dict)]
        if (len(actual_instances) != len(set(actual_instances))
                or set(expected_instances) != set(actual_instances)):
            problems.append((ValueError, "S5 window instances do not exactly cover the dispatched scope map"))
        if state.get("coverage_contract_version") == 2:
            if window.get("schema_version") != 2:
                problems.append((ValueError, "coverage v2 task requires an S5 window schema_version 2"))
                problems[:] = self._noted(
                    problems, "(the coverage v2 checks did not run: the window is not schema_version 2)")
            else:
                self._s5_v2_collect(d, state, window, problems)
        if window.get("input_hash") != d.get("input_hash"):
            problems.append((ValueError, "S5 window input hash does not match its dispatch"))
        if window.get("source_revision") and window.get("source_revision") != state.get("source_revision"):
            problems.append((ValueError, "S5 window source revision is stale"))
        # HF4-10 (N10-2): both sides through the ONE reader, so a window built by 0.10.3 (the readiness ids) closed on a
        # newer build compares equal to the state it was built against
        from window_record import demanded_quality_checks
        required = demanded_quality_checks(state.get("required_quality_checks", []))[0]
        if set(demanded_quality_checks(window.get("required_quality_checks", []))[0]) != set(required):
            problems.append((ValueError, "window cannot omit project quality checks"))

    def _s5_v2_collect(self, d, state, window, problems):
        """The coverage v2 part of tier 3: author and critic, the mechanical round, the refs."""
        author_id = str(window.get("author_dispatch_id") or "")
        reviewer_id = str(window.get("reviewer_dispatch_id") or "")
        author = state["dispatches"].get(author_id, {})
        reviewer = state["dispatches"].get(reviewer_id, {})
        critic = d.get("role") == "qa-code-critic"

        def same_window(other):
            # a plan dispatch (its scope is every case) is never "the same window", whatever the scope says (SC1-14 B1a, E22)
            return (other.get("stage") == "S5" and s5_part_of(other) != "plan"
                    and set(other.get("scope") or []) == set(d.get("scope") or [])
                    and other.get("input_hash") == d.get("input_hash"))

        # `author_dispatch_id` is the accepted author of the window, or the
        # completing mechanical author dispatch itself (accepted right here).
        if (author_id == reviewer_id or author.get("role") != "qa-automator"
                or not same_window(author)
                or (author.get("status") != "accepted" and author_id != d.get("id"))
                or window.get("input_hash") != d.get("input_hash")
                or (critic and reviewer_id != d.get("id"))):
            problems.append((StateConflict, "coverage v2 S5 completion requires distinct accepted author and active critic for the same window"))
        if not critic:
            # The author's mechanical dispatch completes the window: the
            # critic already reviewed and probed it, the fix was made on the
            # critic's word, and the author's green run on the new bytes is
            # the proof (`acceptance.green_on_current_bytes`). No second critic.
            round_problems = self._tier3_call(self._mechanical_completion_problems,
                                              d, window, reviewer, reviewer_id)
            blocking, _ = self._passed_by_person("S5", round_problems)
            if blocking:
                problems.append((
                    StateConflict,
                    "; ".join(blocking) + ". Only the active qa-code-critic, or "
                    "the qa-automator dispatch with `repair_cause: mechanical` "
                    "whose window record carries `mechanical_round` "
                    "{author_dispatch_id, reviewer_dispatch_id, "
                    "reviewed_input_hash}, completes an S5 window. If a person "
                    "accepts it as it is: `"
                    + person_words.door(f"waiver.py --task {self._ticket()} "
                                        "--stage S5 --block \"mechanical round\"")
                    + "`."))
        approved_plan = self._tier3_call(self._plan_document)
        approved_rows = approved_plan.get("rows") if isinstance(approved_plan, dict) else approved_plan
        approved_obligations = {str(ob.get("obligation_id")): content_hash(ob)
                                for row in approved_rows for ob in row.get("coverage_obligations") or []
                                if ob.get("obligation_id")}
        for item in window.get("instances") or []:
            refs = item.get("obligation_refs")
            # Within ONE instance the first failure stops: broken refs make every hash below
            # them meaningless. Between instances the failures are collected (and merged).
            if (item.get("schema_version", 2) != 2 or not isinstance(refs, list) or not refs
                    or any(not isinstance(ref, dict) or not ref.get("obligation_id")
                           or not ref.get("obligation_hash") for ref in refs)
                    or len({ref["obligation_id"] for ref in refs}) != len(refs)):
                problems.append((ValueError, "coverage v2 instance requires unique obligation_refs with exact hashes"))
                continue
            # An instance the person took over never ran here, so it has no
            # execution fingerprint to give. Demanding one would leave the
            # window with exactly two ways out: invent a receipt, or claim
            # there is no implementation (TP2-2536, FB-1). The same holds for
            # an instance the stand blocked (t-219): no run reached a verdict, and
            # `validate_window` re-derives the claim from the manifest, so a
            # hand-typed outcome buys nothing here.
            if (not item.get("execution_fingerprint")
                    and item.get("outcome") not in (HANDED_OUTCOME, BLOCKED_OUTCOME)):
                problems.append((ValueError, "coverage v2 instance requires execution_fingerprint"))
                continue
            if any(approved_obligations.get(str(ref["obligation_id"])) != ref["obligation_hash"]
                   for ref in refs):
                problems.append((StateConflict, "instance obligation_refs do not match the current approved plan"))
                continue
            if set(item.get("obligation_ids") or []) != {ref["obligation_id"] for ref in refs}:
                problems.append((ValueError, "instance obligation IDs must match obligation_refs"))
                continue
            if item.get("obligation_hash") != content_hash(refs):
                problems.append((ValueError, "instance obligation_hash must bind exact obligation_refs"))

    def _s5_gap_problems(self, d, p, window):
        """Tier 4: what `validate_window` finds, as items - the four gap checks collected."""
        from acceptance import (CONTRADICTS_REQUIREMENT, PROBE_GAP_KIND, PROBE_GAP_UNRECORDED_KIND,
                                probe_gap_named, validate_window)
        from window_record import PROBE_GAP_RECORD, probe_gap_keys_line, probe_word_door  # the ONE text of these doors (AR-13)
        gaps =validate_window(window, self.store.root)
        problems = []
        # A probe gap no recorded word of the person names (HF1-14, E12): refused WHETHER OR NOT the completion carries
        # a typed `unresolved` pair, because a caller's pair is not the person's word (M3). The door is the
        # orchestrator's; the critic returns the item.
        unrecorded = [g for g in gaps if g.startswith(PROBE_GAP_UNRECORDED_KIND + ":")]
        if unrecorded:
            problems.append((
                StateConflict,
                "this window claims a probe gap no recorded word of the person names (" + ", ".join(unrecorded)
                + "): a typed `unresolved` pair does not pass it."
                + probe_word_door(
                    window, self.store.root, self._ticket(),
                    " If the person accepts that this test is not probed here, the orchestrator records `"
                    + PROBE_GAP_RECORD.replace("<T>", self._ticket())
                    + "` for the case key of that test, then `window_record.py --task " + self._ticket() + " --dispatch "
                    + str(d.get("id"))
                    + "` builds the record again; otherwise a probe of the test (`probe_by_code.py`) writes the receipt"
                    + probe_gap_keys_line(window, self.store.root))))
        # A gap that says "the person runs this one" is not the same kind of gap
        # as "nothing proves this behaviour". It closes the window by code, with
        # no receipt and no waiting — but only when the handoff is named in the
        # completion itself, so the manifest, the ledger and gate B all carry the
        # same word instead of a silent hole (TP2-2536).
        handed_gaps = [g for g in gaps if g.startswith(HANDED_OUTCOME + ":")]
        other_gaps = [g for g in gaps if not g.startswith(HANDED_OUTCOME + ":")]
        if handed_gaps and not names_handed(p):
            problems.append((
                StateConflict,
                "this window hands " + ", ".join(handed_gaps)
                + " to the person, and the completion does not say so: accept it "
                "with `unresolved` naming `" + HANDED_OUTCOME + "` and a reason "
                "carrying the profile and what the person runs"))
        # The same for the stand (t-219): a gap that says "the stand blocked this one" closes
        # the window only as an unresolved acceptance that NAMES `blocked_by_env`, so the
        # manifest's row, the ledger and gate B read the word the completion carries. It stays
        # among `other_gaps` below: the pair itself is still required, and a person's word
        # for a gap of any other kind is not read from here.
        blocked_gaps = [g for g in gaps if g.startswith(BLOCKED_OUTCOME + ":")]
        if blocked_gaps and not names_blocked(p):
            problems.append((
                StateConflict,
                "this window holds instances the stand blocked (" + ", ".join(blocked_gaps)
                + "), and the completion does not say so: accept it as unresolved with "
                "`unresolved` naming `" + BLOCKED_OUTCOME + "` and a `reason` carrying the "
                "instances and what the stand lacks - `story_step.py finish --task "
                + self._ticket() + " --dispatch-id " + str(d.get("id"))
                + " --digest \"<digest>\"` derives that pair from the window record"))
        # The same for a named probe gap (HF1-14; a person's word or the factory's own naming, RN1-9): it closes the window only as an unresolved acceptance
        # that NAMES `probe_gap`, which `story_step.py finish` derives from the window record.
        probe_gaps = [g for g in gaps if g.startswith(PROBE_GAP_KIND + ":")]
        if probe_gaps and not names_probe_gap(p):
            problems.append((
                StateConflict,
                "this window holds named probe gaps (" + ", ".join(probe_gaps)
                + "), and the completion does not say so: accept it as unresolved with `unresolved` naming `"
                + PROBE_GAP_KIND + "` and a `reason` carrying the instances - `story_step.py finish --task "
                + self._ticket() + " --dispatch-id " + str(d.get("id"))
                + " --digest \"<digest>\"` derives that pair from the window record"))
        # The same for a red the requirement contradicts (HF2-4b): the window closes only as an unresolved acceptance that
        # NAMES `contradicts_requirement`; the pair is derived by `story_step.py finish`, so no role types it and no word
        # of a person is read. A pair typed by hand without the word is refused (FR-10): it must name what it closes.
        contradicts_gaps = [g for g in gaps if g.startswith(CONTRADICTS_REQUIREMENT + ":")]
        if contradicts_gaps and not names_contradicts(p):
            problems.append((
                StateConflict,
                "this window holds red tests the requirement contradicts (" + ", ".join(contradicts_gaps)
                + "): accept it as unresolved with `unresolved` naming `" + CONTRADICTS_WORD + "` - `story_step.py finish "
                "--task " + self._ticket() + " --dispatch-id " + str(d.get("id"))
                + " --digest \"<digest>\"` derives that pair from the window record"))
        if other_gaps and (not p.get("unresolved") or not p.get("reason")):
            problems.append((StateConflict, "unresolved window: " + ", ".join(other_gaps)))
        if gaps and p.get("passed_green"):
            problems.append((StateConflict, "a completed process with gaps cannot be passed_green"))
        if probe_gaps and not problems:
            # An informed pass is recorded (FR-4): the block, the person's words (read from the story's own pipeline,
            # not from the window) and who. Only when nothing else refuses the window.
            # The factory names no gap of its own (t-1968 N2): every named gap is a person's word.
            named = probe_gap_named(window, self.store.root)
            self._record_person_pass("S5", d.get("id"), [
                {"error": g, "decision": (named.get(g.partition(":")[2]) or {}).get("words", ""),
                 "by": "human"} for g in probe_gaps])
        return problems

    @staticmethod
    def _mechanical_completion_problems(d, window, reviewer, reviewer_id):
        """Why the author's mechanical dispatch may NOT complete this S5 window — [] when it may.

        Every line carries "mechanical round", so one recorded word passes them all
        (`waiver.py --block "mechanical round"`). The bytes themselves are judged by
        `acceptance.validate_window` right after: a review bound to `reviewed_input_hash` is
        current only with the author's green run block on the instance's current bytes.
        """
        from acceptance import mechanical_round
        said = "S5 completion by a mechanical round: "
        problems = []
        if d.get("role") != "qa-automator" or repair_cause(d) != "mechanical":
            problems.append(said + f"{d.get('id')} is a {d.get('role')} dispatch with "
                            f"repair_cause {repair_cause(d)}, not the author's mechanical repair")
        record = mechanical_round(window)
        if record is None:
            problems.append(said + "the window record carries no well-formed `mechanical_round` "
                            "(author_dispatch_id, reviewer_dispatch_id, reviewed_input_hash)")
            return problems
        if record["author_dispatch_id"] != str(d.get("id")):
            problems.append(said + f"mechanical_round.author_dispatch_id is "
                            f"{record['author_dispatch_id']}, the completing dispatch is {d.get('id')}")
        if record["reviewer_dispatch_id"] != reviewer_id:
            problems.append(said + f"mechanical_round.reviewer_dispatch_id is "
                            f"{record['reviewer_dispatch_id']}, the window names {reviewer_id or 'none'}")
        if (reviewer.get("role") != "qa-code-critic" or reviewer.get("status") != "accepted"
                or reviewer.get("stage") != "S5"
                or set(reviewer.get("scope") or []) != set(d.get("scope") or [])
                or reviewer.get("input_hash") != d.get("input_hash")):
            problems.append(said + f"{reviewer_id or 'no reviewer'} is not an accepted qa-code-critic "
                            "of this same window (scope and input hash)")
        return problems

    def _s3_grounding_lines(self, d, rows, window):
        """`(lines, crash)`: the grounding findings of an S3 acceptance as refusal lines (`GT.exit_line`), for window 1 (`GT.check`, the
        role's own findings only: the driver's and the conductor's do not stop a window the role cannot repair them in) or for the exit
        (`GT.exit_findings`, every finding, a plan in hand). `crash` is the one line of a check that raised: an error goes to a refusal,
        never to a pass (FR-59)."""
        import grounding_table as GT
        root = self.store.root
        try:
            if window == "labelling":
                found = [f for f in GT.check(root) if f.who == "role"]
            else:
                found = GT.exit_findings(root, rows, GT.not_planned_of(root, str(d.get("id") or "")))
            return [GT.exit_line(f) for f in found], []
        except Exception as exc:   # a check that cannot run is a refusal with a name, not an unhandled error and not a pass
            return [], [f"the check could not run ({type(exc).__name__}: {str(exc)[:200]}). This is the factory's own defect, not the plan's. "
                        "Way on: the conductor repairs the check; a check that did not run is not a pass"]

    def _s3_completion_gate(self, d, p, state):
        """The S3 acceptance gate (G1-5), one call from `validate`. POSITION: after the receipts and the 'no role to close it' refusal, and
        inside the branch of every S3 acceptance, not only the closing one. ORDER (INVARIANT: the plan's refusal never comes before the
        refusal by the marker):
          a. a window-1 (labelling) dispatch that claims the stage complete is refused, and no word of a person passes it (its door is the
             driver's: `finish --not-complete`); `stage_complete: "true"` is complete here, and so is the default a last role gets;
          b. window 1 without `stage_complete`: the role's findings of `GT.check`, through the person's word;
          c. an exit (`stage_complete`): the plan's errors and the grounding findings are ONE list in ONE `_passed_by_person`; the plan's
             head `S3 structured test plan invalid: ` stays when the plan has errors, else `S3 grounding: `; with no grounding finding the
             text and its order are the plan's alone, byte for byte;
          d. a check that raised is a refusal on the same road (a person may pass it too)."""
        window = s3_window_of(d)
        complete = bool(p.get("stage_complete"))
        if window == "labelling" and complete:
            raise StateConflict("a window-1 (labelling) dispatch of S3 cannot close the stage; it is accepted with "
                                "--not-complete --unresolved plan_pending")
        if window != "labelling" and not complete:
            # X2-5 (E-X2-5f): the author of a stage that has an acceptor no longer closes it, but his exit window is still the one the plan
            # is judged on - the refusal reaches him, as before; the critic's closing accept repeats the same check on the same bytes
            from acceptance import author_exit_owes_plan
            if not author_exit_owes_plan(d):
                return
        errors, rows = [], None
        if window != "labelling":
            from planning_contract import validate_plan
            document = self._plan_document()
            rows = document.get("rows") if isinstance(document, dict) else document
            if not isinstance(rows, list):
                raise ValueError("structured test plan rows must be a list")
            errors = validate_plan(rows, require_v2=state.get("coverage_contract_version") == 2)
        lines, crash = self._s3_grounding_lines(d, rows, window)
        grounding = lines + crash
        if not errors and not grounding:
            return
        # `planning_contract.py`'s own refusal ends with "A person's word passes
        # any of these: `waiver.py --task <T> --stage S3 --block ...`" - and until
        # now this line did not read that word, so the door the refusal named
        # opened the exit gate and not the stage. Five conductor sessions of run 5
        # ($1.94) stood on this one message.
        blocking, passed = self._passed_by_person("S3", list(errors) + grounding)
        if blocking:
            left = [b for b in blocking if b not in grounding]
            held = [b for b in blocking if b in grounding]
            door = (" A person's word passes any of these: `"
                    + person_words.door(f"waiver.py --task {self._ticket()} --stage S3 --block \"<part of the line>\"") + "` " + person_words.WHOLE_PART + ".") if held else ""
            if left:
                # the plan's head and its text stay as they were; the grounding lines follow under their own head
                blocking = left + (["S3 grounding: " + held[0]] + held[1:] if held else [])
                raise StateConflict("S3 structured test plan invalid: " + "; ".join(blocking) + door)
            blocking = held
            raise StateConflict("S3 grounding: " + "; ".join(blocking) + door)
        self._record_person_pass("S3", d.get("id"), passed)
        print("S3 structured test plan: passed by a person's recorded word — "
              + str((passed[0] or {}).get("decision") or "")[:300])

    def _closes_stage(self, d, state=None):
        """Does accepting THIS dispatch leave its stage no role that could close it?

        TP2-2553: S4's designer and critic were both accepted with
        `stage_complete: false`, gate A refused with "stage not completed", and the only way
        out was a duplicate `S4-qa-case-critic-2` over unchanged evidence. The stage model
        already knows which role is last (`contract.stage_closes_with`); for S5 and S6 the
        stage is also cut into windows, so the last role of ONE window closes the stage only
        when no other window is still waiting for it. Anything this cannot read answers False:
        a rule that cannot see the state must not invent a closure or a refusal.
        """
        from contract import stage_closes_with
        stage, role = str((d or {}).get("stage") or ""), str((d or {}).get("role") or "")
        if not stage_closes_with(stage, role):
            return False
        # SC1-14 B1a, INVARIANT: the S5 plan dispatch (its critic is the stage's last role) never closes S5 and never "leaves
        # S5 with no role": the windows are written after it. So `apply` sets no `stage_complete` on it and `validate` does
        # not refuse its `stage_complete: false` (E29). `s5_part_of` answers `window` for any record it cannot read.
        if s5_part_of(d) == "plan":
            return False
        # P2 w5 B-1, INVARIANT: the S7 investigation dispatch (the analyst, `complete=False`) is a read-only pass BESIDE the
        # stage's close: the code closes S7 after it (`close_by_code`), so accepting it never leaves S7 "with no role to close it"
        # and `story_step finish --not-complete` is accepted as the S5 plan's is. `s7_part_of` answers "" for a record it cannot read.
        if s7_part_of(d) == "investigation":
            return False
        state = self.state() if state is None else state
        if ((state.get("stages") or {}).get(stage) or {}).get("status") == "completed":
            return False  # already closed; this acceptance strands nothing
        if stage not in DERIVED_SCOPE_STAGES:
            return True
        try:
            windows = self.stage_scope(stage, state).get("windows") or []
            mine = {str(case) for case in d.get("scope") or []}
            for window in windows:
                scope = {str(case) for case in window.get("scope") or []}
                if not scope or scope.issubset(mine):
                    continue  # this dispatch's own window, or a window with nothing in it
                if role not in (window.get("accepted_by") or {}):
                    return False
            return True
        except Exception:
            return False

    def _code_review_problems(self, p):
        """What a code review must leave behind before its dispatch can be accepted.

        TP1-15045: `qa-code-critic` returned eight findings as chat text, wrote no
        findings file, and left `review_receipt_ref` and `sensitivity_proof` `null` in the
        manifest. The orchestrator then retyped the findings for the person, and nothing the
        author could be pointed at existed. `critic_rollcall.py` already counts this for the
        case critic; this is the same rule for the code critic, counted by code.

        Only asked when there IS a manifest: a review with no `work/automation-manifest.json`
        is not an automation review, and a story written by an older version must not be
        refused for a field its manifest never had.
        """
        from contract import artifact, load_json, manifest_tests, test_instance_id
        try:
            manifest_path = Path(artifact(self.store.root, "automation-manifest.json"))
        except (OSError, ValueError):
            # A manifest this reader cannot even locate is `validate_artifacts.py`'s finding,
            # with its own owner and command. It is not a reason to refuse a review.
            return []
        if not manifest_path.is_file():
            return []
        manifest = load_json(manifest_path)
        problems = []
        # One phrase every line carries, so a person's word passes all three at once:
        # `waiver.py --block "not receipted"`.
        said = "the qa-code-critic window is not receipted: "
        names = [str(ref.get("path") or "") for ref in (p.get("evidence_refs") or [])
                 if isinstance(ref, dict)]
        if not any("findings" in Path(name).name.lower() for name in names):
            problems.append(said + "no findings file in the accepted evidence (a name containing "
                            "`findings`, e.g. `work/test-code/critic-findings-<your dispatch>.md`); the repair "
                            "prompt points the author at that file, and a digest in the chat is "
                            "not one")
        bindings = manifest.get("obligation_bindings")
        if isinstance(bindings, list) and bindings:
            missing = sorted({str(b.get("obligation_id") or "?") for b in bindings
                              if isinstance(b, dict) and not str(b.get("review_receipt_ref") or "").strip()})
            if missing and not str(manifest.get("review_receipt_ref") or "").strip():
                problems.append(said + "the manifest carries no `review_receipt_ref` for "
                                + ", ".join(missing[:6])
                                + "; write the immutable S5 review window and put its "
                                  "task-relative path there through `manifest_put.py`")
        import proof_level
        from contract import binding_receipt_ref
        # A red test its `contradicts_requirement` row explains takes no probe (HF2-4b, F2, F-20): ONE call of the one
        # reader of red-ness (AR-13), over the whole story and its latest terminal runs. The exemption holds only the
        # CURRENT red: a past red that went green, or whose row was retracted, is not in `red` and owes its proof as
        # before. A reader that raised or answered `{}` exempts nothing (FR-59: the refusal stands).
        try:
            import acceptance
            red = acceptance.red_by_requirement(
                manifest, [{"instance_id": test_instance_id(e)} for e in manifest_tests(manifest)],
                acceptance.story_scope(manifest), self.store.root, strict=True)
        except Exception:
            red = {}
        unproven = []
        for entry in manifest_tests(manifest):
            # THE predicate (proof_level.proof_required): new or changed, and not handed to the
            # person. A proof reached only through an obligation binding is a proof.
            required = proof_level.proof_required(entry, manifest)
            reason = str(entry.get("sensitivity_proof_missing_reason")
                         or entry.get("sensitivity_reason") or "").strip()
            present = entry.get("sensitivity_proof") or binding_receipt_ref(manifest, entry, self.store.root)
            if required and not present and not reason and test_instance_id(entry) not in red:
                unproven.append(test_instance_id(entry) or str(entry.get("test") or "?"))
        if unproven:
            problems.append(said + "no sensitivity proof (the live-check receipt) and no reason for its absence on "
                            + ", ".join(sorted(unproven)[:6])
                            + "; run `probe_by_code.py --task <T> --dispatch <critic id> --test "
                              "\"<node>\" --instance <IID>` for each (the check is live), or record "
                              "`sensitivity_proof_missing_reason` — a tool that could not give the "
                              "proof is a finding owned by the factory, not a silent null")
        return problems

    def stage_guard_errors(self, stage_id, role=None):
        """What the hook on `Agent` would refuse this dispatch for — asked BEFORE the receipt.

        The order used to be: write the receipt, call `Agent`, let the hook refuse. The
        receipt stayed, no agent existed, and `next` answered `wait_existing_job` with
        `cancel_allowed: false` forever (TP1-15045, S5). Asking the same rules here
        means a refusal leaves no receipt at all; the hook remains the second line for a
        dispatch nobody recorded.

        `stage_guard.py` owns the rules. Until `dispatch_errors` exists this adds no check —
        a story in flight must never be refused because a helper is not there yet.
        """
        try:
            import stage_guard
            errors = getattr(stage_guard, "dispatch_errors", None)
            if errors is None:
                return []
            path = self.store.root / "pipeline.json"
            pipeline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            found = [str(item) for item in errors(pipeline if isinstance(pipeline, dict) else {},
                                                  str(stage_id), task_root=self.store.root,
                                                  role=(str(role) if role else None)) or []]
        except (ImportError, AttributeError, OSError, ValueError, TypeError, KeyError):
            return []
        # Every block of this factory names the way a person's word passes it. If the stage guard's
        # message already carries the command, do not print it twice.
        if found and not any("waiver.py" in item for item in found):
            found.append("a person's word passes this: `"
                         + person_words.door(f"waiver.py --task {self._ticket()} "
                                             f"--stage {stage_id} --block \"<part of the line>\"") + "` " + person_words.WHOLE_PART)
        return found

    def _project_root(self):
        """The onboarded project this story belongs to — where the hook layer writes — or None.

        `runtime_paths.nearest_project`: the nearest folder at or above the task root with a
        `qa-factory/config.json` FILE. A fixed number of `.parent` hops was wrong for every test
        root and for any project that does not keep stories three levels down. Not found is None,
        never the task root (t-622): the task root carries no config, and every consumer that took
        it for the project read receipts and transcripts of a folder that is not one. Each consumer
        says what None means for it (the RUN gate: `_current_known_paths`; liveness: nothing is
        closed; the config reads: the default).
        """
        from runtime_paths import nearest_project
        return nearest_project(self.store.root)

    def _dispatch_starts(self):
        """dispatch id -> the epoch second its receipt was journalled."""
        starts = {}
        try:
            for event in self.store.read():
                if event.get("type") == "dispatch":
                    starts[str(event["payload"].get("id"))] = event.get("created_at")
        except (OSError, ValueError, KeyError):
            return {}
        return starts

    @staticmethod
    def _denial_time(record):
        """The epoch second a denial record says it was written, or None.

        The clock is the one `_dispatch_starts` returns: epoch seconds, a float (the event
        store's `time.time()`). The writer, `inject_context.note_denial`, writes `at` as
        `datetime.now(timezone.utc).isoformat(timespec="seconds")` - `2026-09-21T05:51:00+00:00` -
        and that shape (any explicit offset) is the only one read: a missing time, a bool, a
        number, a date with no clock, a time with no offset, an impossible date are all None,
        because a time the writer never writes is not a time anybody can compare to a launch.
        """
        value = record.get("at")
        if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}", value):
            return None
        try:
            from datetime import datetime
            return datetime.fromisoformat(value).timestamp()
        except (ValueError, OverflowError, OSError):
            return None

    def _denial_times(self, dispatch, starts, dispatches):
        """The times of the denial records that belong to this dispatch (None = a record with no
        usable time), read from `state/dispatch-denials.jsonl`; empty when none does.

        A record that NAMES the dispatch belongs to it - it needs no time. A record that names
        none (the Codex desktop host's prompt is opaque, so `dispatch_id_of` answers None there)
        belongs to the LATEST dispatch of its role and stage started before it, and to no other:
        the record's time must be usable and not earlier than the dispatch's start minus 60 s
        (the clock skew `dispatch_liveness` allows between a writer and a reader), and no later
        dispatch of that role and stage may have started by then. With the record's time or the
        dispatch's start unknown, an unnamed record counts for nothing: closing a dispatch needs
        positive evidence (FR-41), and "some refusal of this role, sometime" is not that - a
        denial of 2026-01-01 closed a live automator that way, and the spawn guard then let a
        second one start beside it.

        One owner, never two: the owner is the latest dispatch of the role and stage whose start
        is not after the record's time; the 60 s of skew is spent only when none had started by
        then (a record just before the FIRST start). So a record in the minute before a later
        dispatch started is still the earlier one's.
        """
        path = self.store.root / DENIALS_FILE
        if not path.is_file():
            return []
        identifier = dispatch.get("id")
        role, stage = str(dispatch.get("role") or ""), str(dispatch.get("stage") or "")
        belongs, unnamed = [], []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("dispatch_id"):
                if record.get("dispatch_id") == identifier:
                    belongs.append(self._denial_time(record))
            elif (role and stage and str(record.get("role") or "") == role
                    and str(record.get("stage") or "") == stage):
                when = self._denial_time(record)
                if when is not None:
                    unnamed.append(when)
        if not unnamed:
            return belongs
        if dispatches is None:
            try:
                dispatches = self.state().get("dispatches") or {}
            except (OSError, ValueError, StateConflict):
                return belongs
        try:
            from dispatch_liveness import _CLOCK_SKEW_S, _usable_time
        except ImportError:
            return belongs
        begin = _usable_time(starts.get(str(identifier)))
        peers = [_usable_time(starts.get(str(other.get("id")))) for other in dispatches.values()
                 if isinstance(other, dict) and other.get("id") != identifier
                 and str(other.get("role") or "") == role and str(other.get("stage") or "") == stage]
        if begin is None:
            return belongs
        peers = [start for start in peers if start is not None]
        for when in unnamed:
            before = [start for start in peers + [begin] if start <= when]
            owner = max(before) if before else min(
                (start for start in peers + [begin] if start - _CLOCK_SKEW_S <= when), default=None)
            if owner == begin:
                belongs.append(when)
        return belongs

    def _launched_after(self, dispatch, latest, starts, now=None):
        """Is there evidence that this dispatch was launched after its refusal, or is alive?

        (a) a receipt of THIS story that names it, is not terminal, and was bound at or after the
        refusal (`latest`) - or carries no usable `bound_at` (a receipt written before wave 5), or
        the refusal has no time to compare to: nothing then shows the receipt came first. A refused
        Agent call writes no receipt of its own on either host (the Codex receipt is written by the
        PostToolUse hook after a successful spawn, the Claude one by `story_step bind` after the
        launch), so a non-terminal receipt naming the dispatch is a launch that happened, and one
        that came after the refusal is a retry that worked. Receipts are read through
        `dispatch_liveness.host_bindings`, the reader `state` itself uses.
        (b) `dispatch_liveness.state` says ALIVE. Its failure is not evidence either way - the
        check is a veto, not a precondition - so a raising `state` vetoes nothing here.
        (c) no project found (`_project_root` is None): there is nothing to read the launch from, the
        comparison is undecided, and an undecided comparison keeps the veto - True.
        """
        identifier = str(dispatch.get("id") or "")
        project = self._project_root()
        if project is None:
            return True     # no project, so no receipts to read: undecided keeps the veto, as an undecided time does (t-622)
        names = self._story_names(project)      # a receipt under any spelling of this folder is this story's (CX2-17, E21)
        try:
            import dispatch_liveness
            for binding in dispatch_liveness.host_bindings(project):
                if (identifier and str(binding.get("dispatch_id") or "") == identifier
                        and str(binding.get("task_id") or "") in names
                        and str(binding.get("status") or "") != "terminal"):
                    bound = dispatch_liveness._usable_time(binding.get("bound_at"))
                    if bound is None or latest is None or bound >= latest:
                        return True
        except Exception:
            pass
        try:
            import dispatch_liveness
            verdict = self._liveness(project, dict(dispatch, started_at=starts.get(identifier)), now, names)
            return verdict.get("state") == dispatch_liveness.ALIVE
        except Exception:
            return False

    def _denied(self, dispatch, now=None, starts=None, dispatches=None):
        """Did the hook on `Agent` record a refusal of this very dispatch, with no launch since?

        Which records belong to it: `_denial_times`. A launch after the refusal outweighs it:
        `_launched_after`. So a dispatch `dispatch_liveness` calls alive is never "denied" - on
        this path or on `closure_repairs`, the second caller - and a denial with nothing after it
        is the refusal itself, as it was. The refusal's time compared to a receipt's `bound_at`
        is the latest of the records that belong to the dispatch; one of them with no usable time
        leaves the comparison undecided, and an undecided comparison keeps a receipt as a veto.

        `starts` (dispatch id -> start epoch) and `dispatches` (the state's map) are read here
        when the caller does not hold them; `now` is the clock `dispatch_liveness.state` judges by.
        """
        path = self.store.root / DENIALS_FILE
        if not path.is_file():
            return False
        starts = self._dispatch_starts() if starts is None else starts
        times = self._denial_times(dispatch, starts, dispatches)
        if not times:
            return False
        latest = None if any(when is None for when in times) else max(times)
        return not self._launched_after(dispatch, latest, starts, now)

    def liveness_fixes(self, state=None, now=None, by=None):
        """The `running` dispatches this host can PROVE nobody is doing, and what became of them.

        0.7.6 asked the opposite question — "is there any record of a launch?" — and on the
        Claude Code host, which writes no launch receipt at all, every genuinely running
        dispatch answered "no" until its role stopped. `dispatch_liveness` looks for proof
        instead: a fresh subagent transcript, a live host binding, a journalled return. A
        host that can prove nothing answers `unknown`, and nothing is closed.

        A recorded denial that belongs to the dispatch needs no corroboration: it is the refusal
        itself. It does not outweigh a launch that came after it, though, and it never closes a
        dispatch `dispatch_liveness` calls alive (`_denied`): since wave 5 the spawn guard trusts
        the status this writes, so a denial that closed a live agent let a second one start
        beside it. A denial that lost that way leaves the dispatch to the ordinary liveness
        verdict below - alive and unknown close nothing.

        `by` is the word of the operation that asked (the reason then says WHO closed the row: `dispatch: X was recorded ...`);
        without it the reason is the `recover` one, byte for byte.
        """
        state = self.state() if state is None else state
        dispatches = state.get("dispatches") or {}
        running = [d for d in dispatches.values() if d.get("status") == "running"]
        if not running:
            return []
        project = self._project_root()
        if project is None:
            return []       # no project, so no host records to prove anything from: nothing is closed (t-622)
        starts = self._dispatch_starts()
        told = {NEVER_STARTED: "never launched", RETURNED: "stopped without acceptance",
                ABANDONED: "left its work unfinished"}
        fixes = []
        for dispatch in running:
            identifier = str(dispatch.get("id"))
            if self._denied(dispatch, now, starts, dispatches):
                kind = NEVER_STARTED
                evidence = ["the dispatch hook refused the Agent call (state/dispatch-denials.jsonl)"]
            else:
                try:
                    import dispatch_liveness
                    # every spelling of this story's name is asked: a closure by inference needs that NO name holds it
                    verdict = self._running_verdict(project, dispatch, starts, now)
                except Exception:
                    continue
                kind = {dispatch_liveness.NEVER_STARTED: NEVER_STARTED,
                        dispatch_liveness.RETURNED: RETURNED,
                        dispatch_liveness.ABANDONED: ABANDONED}.get(verdict.get("state"))
                if not kind:
                    continue
                evidence = [str(item) for item in verdict.get("evidence") or []]
            fix = {"kind": kind, "dispatch_id": dispatch.get("id"),
                   "stage": dispatch.get("stage"), "role": dispatch.get("role"),
                   "digest": str(dispatch.get("returned_digest") or ""),
                   "reason": f"{by or 'recover'}: {identifier} was recorded as running but its role "
                             f"{told[kind]} — " + "; ".join(evidence)}
            life = dispatch_life_key(dispatch)
            if life:
                # FB-4: a second-life fix never has a first-life fix's content, so `close_settled`'s content-hash key differs
                fix["life"] = life
            fixes.append(fix)
        return fixes

    def never_started_fixes(self, state=None):
        """Only the never-launched ones; `recover` and the doctor name that kind separately."""
        return [fix for fix in self.liveness_fixes(state) if fix["kind"] == NEVER_STARTED]

    def close_settled(self, state=None, by=None):
        """Journal the closure of every dispatch nobody is doing. Idempotent; returns the fixes it WROTE.

        The repair is committed only against the revision it read (B1, TR4-7): another writer that acted in between (a `finish`
        accepting a window, the stop hook, a person's word) changed what the fixes were built from, so NOTHING is written, `[]`
        comes back, and the caller reads the state again. `by` names the asking operation in the event's reason (AR-27)."""
        state = self.state() if state is None else state
        fixes = self.liveness_fixes(state, by=by)
        if fixes:
            reason = f"{by} closed dispatches nobody is doing" if by else "recover closed dispatches nobody is doing"
            try:
                self.store.commit("state_repair", {"fixes": fixes, "reason": reason},
                                  "state_repair:" + content_hash(fixes), state.get("revision"), None, self.project)
            except EventCommitted:
                raise       # the event IS in: only the derived views are stale
            except StateConflict as exc:
                if str(exc) != "stale expected revision":
                    raise
                return []
        return fixes

    def record_return(self, dispatch_id, digest, agent=""):
        """The role stopped. Journal that fact for its dispatch; decide nothing.

        Called by the SubagentStop hook, so it never raises and never blocks the stop: a
        return the factory failed to write is recovered later from the same journal line by
        `dispatch_liveness`. The digest is the role's own last word, kept for `resolve_return`.
        """
        identifier = str(dispatch_id or "")
        if not identifier:
            return False
        for attempt in range(3):
            try:
                dispatch = (self.state().get("dispatches") or {}).get(identifier)
                if not dispatch or dispatch.get("status") != "running":
                    return False
                self.store.commit("returned",
                                  {"dispatch_id": identifier, "digest": str(digest or "")[:2000],
                                   "agent": str(agent or ""), "recorded_by": "subagent_stop"},
                                  "returned:" + identifier + dispatch_life_key(dispatch), None, None, self.project)
                return True
            except DerivedViewStale:
                # The return IS written; only the dashboard render after it failed. Retrying
                # would find the dispatch no longer running and report False for a fact that
                # was recorded, and a hook never raises or blocks the stop.
                return True
            except StateConflict:
                # Another writer holds the task lock. The orchestrator's own event wins, and
                # this fact is still in the project journal for `dispatch_liveness` to read.
                time.sleep(0.2 * (attempt + 1))
            except Exception:
                return False
        return False

    def build_checkpoint_request(self, dispatch_id, status, reason, remaining=None):
        """The whole `checkpoint` request for a dispatch, built by code from its receipt.

        The factory's one PLANNED stop before gate A — s1.md's "checkpoint the dispatch
        (`blocked`, reason `source review awaiting the person`)" — had no runnable form. The
        only route left was `--operation checkpoint --input <hand-written json>`, which
        s0.md forbids on the normal path ("do not hand-build service JSON"), so the stop that
        every story with sources reaches was the one command nobody could type (0.7.7 review,
        finding A-F3). Everything but the person's own reason is derived here.
        """
        state = self.state()
        dispatches = state.get("dispatches") or {}
        identifier = str(dispatch_id or "").strip()
        problems = []   # K1 (C3-11): the dispatch, the status and the reason are independent fields of the call
        if not identifier:
            open_ones = [d for d in dispatches.values() if d.get("status") == "running"]
            if len(open_ones) != 1:
                problems.append((ValueError, "--dispatch names the dispatch to checkpoint; running "
                                             "dispatches: "
                                             + (", ".join(sorted(str(d.get("id")) for d in open_ones)) or "none")))
            else:
                identifier = str(open_ones[0].get("id"))
        dispatch = dispatches.get(identifier) if identifier else None
        if identifier and not dispatch:
            problems.append(self._unknown_dispatch(identifier, dispatches))
        status = str(status or "").strip()
        if status not in ("blocked", "paused", "incomplete"):
            problems.append((ValueError, "--status must be one of: blocked, paused, incomplete "
                                         "(`accepted` is `--operation accept`, which needs evidence)"))
        if not str(reason or "").strip():
            problems.append((ValueError, "--reason says what this dispatch is waiting on; `next` reads it "
                                         "back to whoever resumes the story"))
        if not identifier:   # no id to look up while the first item stands: that check did not run (FR-59)
            problems = self._noted(problems, "(the unknown-dispatch check did not run: no dispatch is named)")
        self._raise_all(problems)
        items = [part.strip() for part in re.split(r"[;\n]", str(remaining or "")) if part.strip()]
        checkpoint = dict(dispatch.get("checkpoint") or {})
        checkpoint["remaining"] = items or list(checkpoint.get("remaining") or []) or [str(reason)]
        checkpoint.setdefault("completed", [])
        request = {"id": identifier, "status": status, "reason": str(reason),
                   "checkpoint": checkpoint,
                   "stage": dispatch.get("stage"), "role": dispatch.get("role"),
                   "expected_revision": state.get("revision"),
                   "idempotency_key": "checkpoint:" + identifier + dispatch_life_key(dispatch) + ":" + content_hash(
                       {"status": status, "reason": str(reason), "checkpoint": checkpoint})}
        lease = (state.get("leases") or {}).get("orchestrator") or {}
        if lease.get("owner_session_id"):
            request["owner_session_id"] = lease["owner_session_id"]
        return request

    def _reopen_stamp(self, state, words):
        """The reopening of a CLOSED story, carried on the event that carries the words.

        After gate B and S8 the story is finished, and the factory's own repairs must not be
        able to start it again quietly — that quiet restart is what TP2-2534's ghost
        tail was. A release or a rework on a closed story is a person's decision to go back
        to it, so their words travel with the event and `reopened_at` makes every reader
        (`hooklib.story_closed`) see it as open again. On an open story this is nothing.
        """
        if closure_of(state, self._pipeline())["state"] == "open":
            return {}        # a story that is executing the orders of gate B is not open either: a word reopens it
        return {REOPENED_AT: now_iso(), "reopen_words": str(words)}

    def closure_repairs(self, state=None, pipeline=None):
        """The tail a CLOSED story has no use for: dispatches and stages still claiming work.

        TP2-2534: gate B approved, S1-S8 done, MR merged, suite 173/173 — and an open
        dispatch on a `running` stage. `recover` repaired nothing, because by its own rules
        nothing was broken: a running dispatch is work in progress, and the host could prove
        nothing about it either way. What it could not see is that the story was over, so
        there was no work for that dispatch to be part of. The tail then made the stage
        guard's "single running story" fallback ambiguous and cost the LIVE story two days of
        refused dispatches (I-90, I-92).

        The retro stage is exempt — S9 reads a closed story by design — and a story a person
        reopened is not closed at all, so nothing here touches it.
        """
        state = self.state() if state is None else state
        closed = story_closed(closure_view(state, self._pipeline() if pipeline is None else pipeline))
        if not closed:
            return []
        fixes = []
        for identifier, dispatch in sorted((state.get("dispatches") or {}).items()):
            if (dispatch.get("status") not in OPEN_AFTER_CLOSURE
                    or str(dispatch.get("stage") or "") == RETRO_STAGE):
                continue
            # The same vocabulary the liveness repairs use, so one reader understands both.
            settled = NEVER_STARTED if self._denied(dispatch) else "superseded"
            fixes.append({"kind": STALE_AFTER_CLOSURE, "dispatch_id": identifier,
                          "stage": dispatch.get("stage"), "role": dispatch.get("role"),
                          "settled_as": settled, "closed_at": closed,
                          "reason": f"recover: {identifier} was still {dispatch.get('status')} "
                                    f"after the story closed at {closed}; a closed story owes "
                                    f"nobody this work"})
        claimed = {str(fix.get("stage")) for fix in fixes}
        for stage, entry in sorted((state.get("stages") or {}).items()):
            if (entry or {}).get("status") not in ("running", "blocked", "halted"):
                continue
            if stage == RETRO_STAGE or stage in claimed:
                continue
            fixes.append({"kind": STALE_AFTER_CLOSURE, "stage": stage, "closed_at": closed,
                          "reason": f"recover: {stage} was left {(entry or {}).get('status')} "
                                    f"after the story closed at {closed}"})
        return fixes

    def release_dispatch(self, dispatch_id, words):
        """A person said nobody is doing this dispatch. Their word frees it.

        The standing rule of this factory is that a person's recorded word passes any block,
        and on TP2-2523 it passed nothing: "it's dead, go on" was written down and
        `next` still answered `wait_existing_job`, `cancel_allowed: false`. Nothing the role
        wrote is removed — only the claim that somebody is still working on it.
        """
        identifier = str(dispatch_id or "").strip()
        state = self.state()
        dispatches = state.get("dispatches") or {}
        releasable = {"running", "blocked", "paused", "incomplete", RETURNED, ABANDONED}
        problems = []   # K1 (C3-11): the dispatch and the words are independent fields of the call
        if not identifier:
            open_ones = [d for d in dispatches.values() if d.get("status") in releasable]
            if len(open_ones) != 1:
                problems.append((ValueError, "--dispatch names the dispatch to release; open dispatches: "
                                             + (", ".join(sorted(str(d.get("id")) for d in open_ones)) or "none")))
            else:
                identifier = str(open_ones[0].get("id"))
        if not str(words or "").strip():
            problems.append((ValueError, "--words records the person's own words: a release is their decision, "
                                         "not the factory's. Pass --words-file <path to their words, as they were "
                                         "given>"))
        dispatch = dispatches.get(identifier) if identifier else None
        if identifier and not dispatch:
            problems.append(self._unknown_dispatch(identifier, dispatches))
        if not identifier:   # no id to look up while the first item stands: that check did not run (FR-59)
            problems = self._noted(problems, "(the unknown-dispatch check did not run: no dispatch is named)")
        self._raise_all(problems)
        if dispatch.get("status") not in releasable:
            raise StateConflict(f"{identifier} is {dispatch.get('status')}, which holds nothing back; "
                                "release applies to " + ", ".join(sorted(releasable)))
        payload = {"dispatch_id": identifier, "words": str(words),
                   "previous_status": str(dispatch.get("status") or ""),
                   "reason": "released by a person's word"}
        if not owed_executor(state, dispatch):
            # the word that frees the executor of a due order of gate B calls THAT work off (the projection cancels the order);
            # it does not reopen the story for other work, so it carries no `reopened_at`
            payload.update(self._reopen_stamp(state, words))
        self.store.commit("release", payload,
                          "release:" + identifier + ":" + content_hash(str(words)),
                          None, None, self.project)
        after = self.state()
        return {"released": True, "dispatch_id": identifier, "words": str(words),
                "status": (after.get("dispatches") or {}).get(identifier, {}).get("status"),
                "stage": dispatch.get("stage"), "role": dispatch.get("role"),
                "artifacts": "kept: a release frees the dispatch, never the work",
                "next_action": self.next_action()}

    def held_work(self, state=None):
        """The dispatches that never started and are held for a person's word (`next` lists them as `held`): on a CLOSED story
        all of them, on a story a partial `reopen_story` opened the ones it left out."""
        state = self.state() if state is None else state
        return held_dispatches(state, closure_of(state, self._pipeline())["state"] != "open")

    def _closed_dispatch_refusal(self, state, p):
        """Why this `dispatch` may not start now, or '' (B-331, C1-6a): THE closure test of the dispatch check.

        Error direction: asking when the story is in fact open is the allowed error (a person is asked once too often);
        starting work on a closed story is the forbidden one. So the reading is `story_closed` over the controller's own
        state (the ONE reading, no second one): `closed_at` set, or a legacy story (gate B decided, S8 done), or a pipeline
        file nobody can read (the state alone). Let through: the retro (S9, which reads a closed story by design), a story
        that is not closed, and a REWORK-shaped dispatch that carries a person's reopening on its own event - `reopened_at`
        AND the words, and the reopening must make the story open by that same reading (a stamp earlier than `closed_at`, or
        with no words, opens nothing: the dispatch would land while the story stayed closed). Rework-shaped is the shape
        `build_rework_request` builds: `rework_of` names an ACCEPTED dispatch of the same stage and role, and no `relaunch_of`.
        INVARIANT of that position: held work stays unreachable by a hand-stamped packet - a relaunch of held work goes through
        `reopen_story` (the `held` list, the covered set), never through a stamp the packet writes about itself. A relaunch of
        a dispatch a `reopen_story` left held is refused whatever the story's state: a word covers only what the question
        named."""
        pipeline = self._pipeline()
        named = str(p.get("relaunch_of") or "")
        if named and named in left_held_ids(state):
            return self._left_held_refusal(named, state)
        stage = str(p.get("stage") or "")
        closure = closure_of(state, pipeline)
        closed = closure["closed_at"]
        if closure["state"] == "open" or (stage == RETRO_STAGE and closure["state"] == "closed"):
            return ""
        due = orders_due(state)
        # INVARIANT of this position (t-1509): on a story whose gate B is decided, NOTHING starts but the executor of a due order,
        # a rework carrying a person's words, and - once every order is settled - the retro. The retro (S9) is refused while
        # an order is due: it reads the story's final state.
        if closure["state"] == EXECUTING and any(executes_order(gate_orders().get(name), p) for name in due):
            return ""
        stamp, words = str(p.get(REOPENED_AT) or ""), str(p.get("reopen_words") or "").strip()
        if (stamp and words and not named and self._is_rework_shape(state, p)
                and closure_of(dict(state, **{REOPENED_AT: stamp}), pipeline)["state"] == "open"):
            return ""
        if closure["state"] == EXECUTING:
            return _executing_refusal(self._ticket(), stage, due)
        return (f"the story closed at {closed} (gate B is decided and S8 is done), so {stage} does not start on it by itself: "
                "work on a closed story starts on a person's word. " + _closed_story_doors(state, p))

    @staticmethod
    def _is_rework_shape(state, p):
        """Is this dispatch request the shape `build_rework_request` builds: `rework_of` names an accepted dispatch of the same
        stage and role? Only that shape may carry its own `reopened_at` (a rework IS a person's reopening of accepted work)."""
        prior = (state.get("dispatches") or {}).get(str(p.get("rework_of") or "")) or {}
        return (prior.get("status") == "accepted" and prior.get("stage") == p.get("stage")
                and prior.get("role") == p.get("role"))

    def _left_held_refusal(self, named, state):
        """Why a relaunch of a dispatch the person's `reopen_story` left out is refused, with the doors that OPEN (FR-2, AR-9):
        `reopen_story` / `leave_unlaunched` for a held (never started) one - both accept it on the story's open state; for a
        RELEASED one (or any other status) neither does, and the door is `next`, which says what the story does now."""
        dispatch = (state.get("dispatches") or {}).get(named) or {}
        head = (f"{named} was left out when the person reopened the story: their word covered other work, and a word covers "
                "only what was named. ")
        if dispatch.get("status") != NEVER_STARTED:
            return head + (f"It is {dispatch.get('status')} and asks for no word of anyone's, so it does not start by itself; "
                           "`--operation next` says what the story does now.")
        return head + ("To start it, a person says `run again` for it: "
                       f"`{person_words.door('controller.py --operation reopen_story --dispatch ' + named)}`; "
                       "to leave it as it is: "
                       f"`{person_words.door('controller.py --operation leave_unlaunched --dispatch ' + named)}`.")

    def _held_work_refusal(self, op, p, state):
        """`validate` of `reopen_story` / `leave_unlaunched`: every problem of the call at once (K1), the call's own
        fields first (ValueError), then the story's state (StateConflict). Nothing is written on a refusal."""
        ids, words = p.get("dispatch_ids"), str(p.get("words") or "")
        closed = closure_of(state, self._pipeline())["state"] != "open"
        dispatches = state.get("dispatches") or {}
        held = {str(d.get("id")): d for d in held_dispatches(state, closed)}
        listed = ", ".join(sorted(held)) or "none"
        shape = []
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i.strip() for i in ids):
            shape.append((ValueError, "--dispatch names the held dispatches the person's word covers, comma-separated; "
                                      f"held now: {listed} (`--operation next` lists them as `held`)"))
        if not words.strip():
            shape.append((ValueError, "--words-file records the person's own words: " + op.replace("_", " ") + " is their "
                                      "decision, not the factory's. Pass --words-file <path to their words, as they were given>"))
        self._raise_all(shape)
        verb = "reopen" if op == "reopen_story" else "leave"
        problems = []
        if not closed and not held:
            problems.append((StateConflict, f"the story is not closed and holds no work back, so there is nothing to {verb}: "
                                            "`--operation next` says what the story does now"))
        for did in ids:
            dispatch = dispatches.get(did)
            if dispatch is None:
                problems.append(self._unknown_dispatch(did, dispatches))
            elif str(dispatch.get("stage") or "") == RETRO_STAGE:
                problems.append((StateConflict, f"{did} is the retro (S9), which runs on a closed story with no word of "
                                                "anyone's: nothing holds it back and there is nothing to " + verb))
            elif op == "leave_unlaunched" and dispatch.get("status") != NEVER_STARTED:
                what = ("a person released it, and a release asks for nothing" if dispatch.get("status") == RELEASED
                        else "only a dispatch that never reached an agent is left")
                problems.append((StateConflict, f"{did} is {dispatch.get('status')}, not {NEVER_STARTED}: {what}. "
                                                "`--operation next` lists what is held"))
            elif (op == "reopen_story" or not closed) and did not in held and (closed or held):
                # A word covers only work `next` lists as `held`. On an OPEN story (a partial reopen) that is the left-held
                # work, so `leave` is held to the same list; a story that is open with nothing held was refused above.
                problems.append((StateConflict, f"{did} is not held back on this story ({dispatch.get('status')}): a word "
                                                f"covers only work `next` lists as `held`: {listed}"))
        self._raise_all(problems)

    @staticmethod
    def _dispatch_ids(raw):
        """The ids a CLI call names: a list, or text separated by commas or spaces; in order, each once."""
        parts = raw if isinstance(raw, (list, tuple)) else re.split(r"[,\s]+", str(raw or ""))
        return list(dict.fromkeys(str(part).strip() for part in parts if str(part).strip()))

    def _held_work_request(self, op, dispatch_ids, words, state, **extra):
        """The whole request of the two held-work ops, built by code from state (the `build_checkpoint_request` pattern)."""
        ids = self._dispatch_ids(dispatch_ids)
        request = dict({"dispatch_ids": ids, "words": str(words or "")}, **extra)
        return self._request_scaffold(request, state, op + ":" + ",".join(sorted(ids)) + ":" + content_hash(str(words or "")))

    @staticmethod
    def _request_scaffold(request, state, key):
        """The part every code-built request of a person's word shares (the `build_checkpoint_request` pattern): the revision it
        was read at, the idempotency key, and the lease holder's session when one is held."""
        request["expected_revision"] = state.get("revision")
        request["idempotency_key"] = key
        lease = (state.get("leases") or {}).get("orchestrator") or {}
        if lease.get("owner_session_id"):
            request["owner_session_id"] = lease["owner_session_id"]
        return request

    def reopen_story(self, dispatch_ids, words):
        """A person said `run again` to the work a closed story held back (B-331): the ONE reopening of a closed story for
        never-started work. It stamps the reopening through `_reopen_stamp` (the one writer), records the set of dispatches
        the word covers and the work it left out, and the existing `next` -> `relaunch` loop starts the covered ones
        one at a time. The same key twice is the same answer: a retry after a transport doubt records nothing again.

        PARTIAL reopen (B1): the dispatches the word did not name stay listed as `held` (`next` asks again once the covered work
        is done), and both ops still accept them - this op for a later `run again`, `leave_unlaunched` for `leave`. What is
        left out is every relaunch candidate not named - on a closed story a RELEASED one too (a release asks for nothing, so
        a reopen for other work must not start it unasked); on a story already open only the held ones (a dispatch that
        merely never started on an open stage is ordinary work for `next`)."""
        state = self.state()
        request = self._held_work_request("reopen_story", dispatch_ids, words, state)
        key = request["idempotency_key"]
        for event in self.store.read():
            if event.get("idempotency_key") == key:
                return {"reopened": True, "already_recorded": True, "dispatch_ids": event["payload"].get("dispatch_ids"),
                        "next_action": self.next_action()}
        closed = closure_of(state, self._pipeline())["state"] != "open"
        pool = relaunch_candidates(state, owed=False) if closed else self.held_work(state)
        request["left_held"] = [str(d.get("id")) for d in pool if str(d.get("id")) not in request["dispatch_ids"]]
        request.update(self._reopen_stamp(state, words))
        request["reason"] = "reopened by a person's word for work that never started"
        receipt = self.apply("reopen_story", request)
        return {"reopened": True, "dispatch_ids": request["dispatch_ids"], "left_held": request["left_held"],
                "words": str(words), "receipt": receipt, "next_action": self.next_action()}

    def leave_unlaunched(self, dispatch_ids, words):
        """A person said `leave`: the work that never started is history, and nothing in this story asks for it again (the
        dispatch `superseded` with their words, its stage completed `person_left`). One replay, one event; the same key
        twice is the same answer."""
        state = self.state()
        request = self._held_work_request("leave_unlaunched", dispatch_ids, words, state)
        request["reason"] = "left by a person's word; the work never started"
        receipt = self.apply("leave_unlaunched", request)
        return {"left": True, "dispatch_ids": request["dispatch_ids"], "words": str(words), "receipt": receipt,
                "next_action": self.next_action()}

    @staticmethod
    def _hold_op_refusal(op, p, state):
        """`validate` of the four operations of the story held for code (t-2181 PC-6; t-2277 J-C10): every problem of the call at
        once (K1) - the call's own fields first (ValueError), then the story's state (StateConflict) - each with the door that
        leads on (FR-2, AR-9). Nothing is written on a refusal. `await`: a cause comes with the stage it holds from (and the
        other way round), and a stopped story is not re-held by a bare `await`. `arrive`: nothing to refuse (with nothing held it
        only records the arrival). `stop_waiting`: the
        person's words, a story that is awaiting. `first_look_continue`: the person's words, the keys the caller computed
        (`source_head` text, `register_hash` of 64 hex - stored as given, never parsed or computed here, AR-13), and a hold that
        is NOT `s5_absent_side` and NOT stopped (or no hold at all: then the call only records)."""
        hold, number = _hold_of(state)
        words, shape, problems = str(p.get("words") or ""), [], []
        doors = _hold_doors(number)
        door_arrive, door_stop, door_rework = doors["arrive"], doors["stop"], doors["rework"]
        if op == "await":
            cause, held_from = p.get("cause"), p.get("held_from")
            if (cause is None) != (held_from is None):
                shape.append((ValueError, "`cause` and `held_from` go together: a cause names why the story is held and `held_from` the "
                                          "stage it holds from (`S6` for `s5_absent_side`, `S3` for `first_look_stop`); send both, or "
                                          "neither (then the record reads `s5_absent_side` from S6)"))
            elif cause is not None:
                if not (isinstance(cause, str) and cause.strip()):
                    shape.append((ValueError, "`cause` must be a non-empty word naming why the story is held, e.g. `s5_absent_side` or `first_look_stop`"))
                if not (isinstance(held_from, str) and HELD_FROM_RE.match(held_from)):
                    shape.append((ValueError, f"`held_from` must be a stage id `S0`..`S9`, got {held_from!r}"))
            if hold["state"] == "stopped":
                problems.append((StateConflict, f"this story was stopped while it waited, and a bare `await` does not take that back: {door_arrive}, "
                                                f"or {door_rework}"))
        elif op == "arrive":
            pass    # nothing to refuse: with nothing held it only RECORDS the arrival road (t-2181 3.2, F4), like `first_look_continue`
        else:
            if not words.strip():
                shape.append((ValueError, f"--words-file records the person's own words: {op.replace('_', ' ')} is their decision, not the "
                                          f"factory's. Pass --words-file <path to their words, as they were given>"))
            if op == "stop_waiting":
                if hold["state"] == "none":
                    problems.append((StateConflict, "nothing is held for code, so there is no wait to stop: `--operation next` says what the story does now"))
                elif hold["state"] == "stopped":
                    problems.append((StateConflict, f"the wait was stopped already: {door_arrive}, or {door_rework}"))
            else:
                head, register = p.get("source_head"), p.get("register_hash")
                keys = ("the driver passes the values of `first_look.py show --json` (`current_keys`): `--source-head` the heads text, "
                        "`--register-hash` the 64 hex of the register")
                if not (isinstance(head, str) and head.strip()):
                    shape.append((ValueError, f"--source-head is the text of the code heads the first look saw, as the caller computed it: {keys}"))
                if not (isinstance(register, str) and re.fullmatch(r"[0-9a-fA-F]{64}", register)):
                    shape.append((ValueError, f"--register-hash must be 64 hex characters, got {register!r}: {keys}"))
                if hold["state"] == "stopped":
                    problems.append((StateConflict, f"the wait was stopped: `first_look_continue` does not reopen it. {door_arrive}, or {door_rework}"))
                elif hold["state"] == "awaiting" and hold["cause"] != FIRST_LOOK_STOP:
                    problems.append((StateConflict, f"this story is held for {hold['cause']}, and only the code arriving clears that hold, never "
                                                    f"a word: {door_arrive}; {door_stop}; or, for a missing side that is another team's, the "
                                                    "person's answer `not ours` to the driver's question about it, which the driver "
                                                    "carries out as the side recorded another team's and `arrive` naming that side"))
        Controller._raise_all(shape)
        Controller._raise_all(problems)

    def _hold_dispatch_refusal(self, p, state):
        """`validate` of a `dispatch` on a story held for code (F5, E-W1). INVARIANT: a STOPPED story starts no dispatch except the
        rework a person's words reopen it with - `await_reopened` (the mark the projection reads to remove `stopped`) is accepted
        ONLY on a stopped hold, on the shape `build_rework_request` builds (`_is_rework_shape`), with `person_words` true and
        non-empty words, for a stage BELOW `held_from`; a hand-written dispatch carrying it with words typed by code is refused,
        and so is any other dispatch of a stopped story. A story that is awaiting (not stopped) is not touched here: the stage
        guard (`rule_awaiting_code`) keeps its stages from `held_from` closed."""
        hold, number = _hold_of(state)
        reopened, door = p.get("await_reopened"), _hold_doors(number)
        shape, problems = [], []
        if reopened is not None:
            words = reopened.get("words") if isinstance(reopened, dict) else None
            if not (isinstance(words, str) and words.strip()) or p.get("person_words") is not True:
                shape.append((ValueError, "`await_reopened` is the person's word reopening a stopped story: it carries their own words "
                                          "(`{\"words\": <text>}`) on a rework built from `--words-file` (`person_words` true), never a "
                                          "reason typed by code. Use `controller.py --operation rework --stage <stage> --role <role> "
                                          "--words-file <file>`"))
            if hold["state"] != "stopped":
                problems.append((StateConflict, "`await_reopened` reopens a STOPPED story and this one is not stopped: "
                                                "`--operation next` says what the story does now"))
            elif not self._is_rework_shape(state, p) or _stage_no(p) >= number:
                problems.append((StateConflict, f"a stopped story is reopened only by the rework of an accepted dispatch of S0-S{number - 1} "
                                                f"(`rework_of` names it); {p.get('stage')} is not that. Doors: {door['rework']}; {door['arrive']}"))
        elif hold["state"] == "stopped":
            problems.append((StateConflict, f"this story was stopped while it waited for code: no dispatch starts on it by itself. "
                                            f"Doors: {door['rework']}; {door['arrive']}"))
        self._raise_all(shape)
        self._raise_all(problems)

    def _hold_request(self, op, words, state, **fields):
        """The whole request of `stop_waiting` / `first_look_continue`, built by code from the state (the `_held_work_request`
        pattern): the person's words and the keys as given, the revision, the lease, one idempotency key per hold, words and keys -
        a repeat of the same call is the same answer, a later hold has its own identity: the event numbers of its `await` (`opened`)
        and of the rework that reopened it (`reopened`), never its `since` (a reopening keeps that), F1."""
        hold, _ = _hold_of(state)
        request = dict({"words": str(words or "")}, **fields)      # no time in the payload: `at` is the event's own, so a retry replays
        content = "|".join([str(words or "")] + [str(fields[key]) for key in sorted(fields)]
                           + [str(hold.get("opened")), str(hold.get("reopened"))])
        return self._request_scaffold(request, state, f"{op}:{content_hash(content)}")

    def stop_waiting(self, words):
        """The person's `stop waiting` (t-2181 PC-6): the story held for code is `stopped` with their words and the time; every
        reader does nothing further (E-W1). The way out stays: their rework of S0..held_from-1 with words, or `arrive`."""
        request = self._hold_request("stop_waiting", words, self.state())
        receipt = self.apply("stop_waiting", request)
        return {"stopped": True, "words": str(words), "receipt": receipt, "next_action": self.next_action()}

    def first_look_continue(self, words, source_head, register_hash):
        """The person's `continue` after the first look stopped the story (t-2277 J-C10): clears a `first_look_stop` hold and
        records `first_look_continued {source_head, register_hash, words, at}` (projected as `pipeline.first_look_continue`). The
        two keys are what the caller computed through `first_look.current_keys` and are STORED AS GIVEN: this operation neither
        computes nor parses them (AR-13) and depends on nothing a first-look module defines. Without a hold it only records."""
        request = self._hold_request("first_look_continue", words, self.state(),
                                     source_head=source_head, register_hash=register_hash)
        receipt = self.apply("first_look_continue", request)
        return {"continued": True, "words": str(words), "source_head": source_head, "register_hash": register_hash,
                "receipt": receipt, "next_action": self.next_action()}

    def _settle_order_refusal(self, p, state):
        """`validate` of `settle_order`: every problem of the call at once, the call's own fields first (ValueError), then the
        story's state (StateConflict) with the door that opens (FR-2). Nothing is written on a refusal."""
        order, outcome = p.get("order"), p.get("outcome")
        ref, words, code = str(p.get("ref") or ""), str(p.get("words") or ""), str(p.get("reason_code") or "")
        table = gate_orders()
        shape = []
        if order not in table:
            shape.append((ValueError, f"--order names the order of gate B to settle, one of: {', '.join(table) or 'none declared'}; "
                                      f"got {order!r}"))
        if outcome not in SETTLE_OUTCOMES:
            shape.append((ValueError, f"--outcome is how the order ended, one of: {', '.join(SETTLE_OUTCOMES)}; got {outcome!r}"))
        elif outcome == ORDER_DONE and order == "bugs":
            shape.append((ValueError, "bugs is done by the accepted qa-bug-reporter dispatch, not by a word: run the reporter "
                                      "(`--operation next` names it), or call the order off with `--outcome cancelled` and the "
                                      "person's words"))
        elif outcome == ORDER_DONE and order in table and not ref.strip():
            shape.append((ValueError, "--ref is the MR's link or id: an MR order is `done` only with the record of the MR that was opened"))
        elif outcome == ORDER_CANCELLED:
            if code and order != "mr":
                shape.append((ValueError, f"--reason-code is the delivery step's reason for the `mr` order only; {order} is called off "
                                          "only by the person's words: pass --words-file <file> (or `release` the reporter's dispatch)"))
            elif code and code not in SETTLE_REASON_CODES:
                shape.append((ValueError, f"--reason-code is the factory's own reason, one of: {', '.join(SETTLE_REASON_CODES)}; got {code!r}"))
            elif code and not ref.strip():
                shape.append((ValueError, "--reason-code goes with --ref, the delivery step's own one-line record of why"))
            elif not code and not words.strip():
                door = person_words.door('controller.py --operation settle_order --order <order> --outcome cancelled')
                shape.append((ValueError, "a cancelled order is the person's call or the factory's coded reason: pass the person's own "
                                          f"words (`{door}`) or --reason-code {' | '.join(SETTLE_REASON_CODES)} with --ref"))
        if len(ref) > SETTLE_REF_MAX:
            shape.append((ValueError, f"--ref holds an MR link or id, or the delivery step's one-line record, at most {SETTLE_REF_MAX} characters"))
        self._raise_all(shape)
        decision, problems = latest_gate_b(state), []
        if decision is None:
            problems.append((StateConflict, "gate B is not decided, so it has no orders to settle: record the person's decision with "
                                            f"`{person_words.door('controller.py --operation gate-decision --gate B --drafts <refs>')}`"))
        else:
            statuses = gate_b_orders(state)
            if statuses.get(order) != ORDER_DUE:
                problems.append((StateConflict, f"the order {order} is {statuses.get(order, 'unknown')}, not due, so there is nothing to settle "
                                                f"(orders now: {', '.join(f'{n} {s}' for n, s in statuses.items()) or 'none'}): "
                                                "`--operation next` says what the story does now"))
            if p.get("decision_id") != decision.get("id"):
                problems.append((StateConflict, f"the request settles an order of {p.get('decision_id')!r}, but the newest gate B decision "
                                                f"is {decision.get('id')!r}: build the call again (`--operation next`)"))
        self._raise_all(problems)

    def settle_order(self, order, outcome, ref=None, words=None, reason_code=None):
        """An order of gate B ended without a dispatch of its own: the MR was opened (`done`, with its record), or the order was
        called off (`cancelled`, by a person's words or by the factory's coded reason). The request is built here from flags and
        state (the `reopen_story` pattern); one key per order, outcome and content, so a repeat is the same answer with no new
        event. A `bugs` order is never `done` by a word: the accepted reporter dispatch settles it (the projection)."""
        state = self.state()
        decision = latest_gate_b(state) or {}
        content = "|".join((str(decision.get("id") or ""), str(ref or ""), str(words or ""), str(reason_code or "")))
        request = {"order": order, "outcome": outcome, "decision_id": str(decision.get("id") or ""),
                   "reason": f"order {order} of gate B settled: {outcome}", "expected_revision": state.get("revision"),
                   "idempotency_key": f"settle:{order}:{outcome}:{content_hash(content)}"}
        request.update({key: str(value) for key, value in (("ref", ref), ("words", words), ("reason_code", reason_code)) if value})
        lease = (state.get("leases") or {}).get("orchestrator") or {}
        if lease.get("owner_session_id"):
            request["owner_session_id"] = lease["owner_session_id"]
        for event in self.store.read():
            if event.get("idempotency_key") == request["idempotency_key"]:
                return {"settled": True, "already_recorded": True, "order": order, "outcome": outcome, "next_action": self.next_action()}
        receipt = self.apply("settle_order", request)
        return {"settled": True, "order": order, "outcome": outcome, "receipt": receipt, "next_action": self.next_action()}

    @staticmethod
    def stage_repairs(state):
        """The internal inconsistencies `recover` can repair by itself.

        A stage left `running` while nothing is running, whose own last dispatch was accepted
        and completed it, is a projection that contradicts its own receipts. `stage_complete`
        is required there: without it the stage really was never finished, and `recover` would
        be inventing an acceptance instead of restoring one.

        The second case is TP2-2553's: the stage's LAST role was accepted without the
        flag and no dispatch of the stage is open. Nothing can close that stage any more —
        the only way out of it was a duplicate critic dispatch over unchanged evidence — and
        the closure is not invented here either: the role the stage model names as its last
        one was accepted, which is exactly what closing a stage means.
        """
        from contract import stage_closes_with
        dispatches = state.get("dispatches") or {}
        if any(d.get("status") == "running" for d in dispatches.values()):
            return []
        fixes = []
        for stage, entry in sorted((state.get("stages") or {}).items()):
            status = (entry or {}).get("status")
            if status not in ("running", "pending"):
                continue
            own = [d for d in dispatches.values() if d.get("stage") == stage
                   and d.get("status") not in DISCOUNTED]
            last = own[-1] if own else {}
            if status == "running" and last.get("status") == "accepted" and last.get("stage_complete"):
                fixes.append({"kind": "stage_completed", "stage": stage, "dispatch_id": last.get("id"),
                              "reason": f"recover: {stage} was left running with no active dispatch "
                                        f"after {last.get('id')} was accepted as stage_complete"})
            elif (last.get("status") == "accepted" and not last.get("stage_complete")
                  and not last.get("unresolved")  # work it named itself is not a closure
                  and stage_closes_with(stage, str(last.get("role") or ""))
                  and not any(d.get("status") in OPEN_AFTER_CLOSURE for d in own)):
                fixes.append({"kind": "stage_completed", "stage": stage, "dispatch_id": last.get("id"),
                              "reason": f"recover: {stage}'s last role {last.get('role')} was accepted "
                                        f"in {last.get('id')} without stage_complete and no dispatch "
                                        f"of the stage is open, so nothing else could close it"})
        return fixes

    def recover(self):
        """Rebuild the projections from the journal and repair what code can repair.

        Two different repairs. Re-projecting alone heals a state written by an older reducer —
        TP1-15045 left an accepted S3 as `running` in both controller.json and
        pipeline.json, and replaying the same journal under the monotonic rule puts it back.
        A state whose own receipts already contradict it is repaired through a journalled
        `state_repair`, so the fix is a durable fact rather than a quiet rewrite of a cache.
        The person is never asked to edit state files: this is the factory's own defect, and this operation is the whole of its repair.
        """
        before = self._pipeline_stage_statuses()
        # Up to four commits (the re-projection and three kinds of repair); the derived views
        # are refreshed ONCE, after the last of them, and also when nothing needed repairing —
        # a refresh that failed after an earlier event is repaired by exactly this operation.
        with self.store.deferred_after_commit():
            revision = self.store.recover(self.project)
            # Dispatches nobody is doing go first: closing them is what makes a stranded stage
            # visible to `stage_repairs` instead of hiding behind a job nobody was doing.
            fixes = self.close_settled()
            # Then the tail of a story that is already over. This one needs no liveness proof:
            # the proof is gate B (TP2-2534). It runs before `stage_repairs` for the same
            # reason `close_settled` does — a stranded stage is invisible behind an open dispatch.
            settled_after_closure = self.closure_repairs()
            if settled_after_closure:
                fixes = fixes + settled_after_closure
                self.store.commit("state_repair",
                                  {"fixes": settled_after_closure,
                                   "reason": "recover settled the tail of a closed story"},
                                  "state_repair:" + content_hash(settled_after_closure),
                                  None, None, self.project)
            stranded = self.stage_repairs(self.state())
            if stranded:
                fixes = fixes + stranded
                event = self.store.commit("state_repair",
                                          {"fixes": stranded, "reason": "recover repaired internal state"},
                                          "state_repair:" + content_hash(stranded), None, None, self.project)
                revision = event["sequence"]
            elif fixes:
                revision = self.state()["revision"]
        after = self._pipeline_stage_statuses()
        return {"revision": revision, "journalled_repairs": fixes,
                "retry_packets": self.retry_packets(),
                "reprojected_stages": [{"stage": stage, "from": before.get(stage), "to": after.get(stage)}
                                       for stage in sorted(set(before) | set(after))
                                       if before.get(stage) != after.get(stage)],
                "next_action": self.next_action()}

    def retry_packets(self, state=None):
        """One ready retry packet per stopped dispatch nothing has replaced.

        `recover` prints them and journals nothing for them: whether a role is retried is the
        orchestrator's decision, and the packet only removes the hand-building that cost
        TP2-2553 two rejected receipts.
        """
        state = self.state() if state is None else state
        entries = list((state.get("dispatches") or {}).values())
        packets = []
        for index, dispatch in enumerate(entries):
            if dispatch.get("status") not in STOPPED:
                continue
            if any(other.get("stage") == dispatch.get("stage")
                   and other.get("role") == dispatch.get("role") for other in entries[index + 1:]):
                continue
            packet = self._retry_packet(state, dispatch)
            if packet:
                # Same three fields `next` carries, so a reader learns one shape: the packet
                # itself stays exactly what `--operation dispatch --input` takes.
                packets.append({"dispatch_id": dispatch.get("id"),
                                "reason": self._retry_reason(dispatch, packet), "packet": packet})
        return packets

    def _pipeline_stage_statuses(self):
        try:
            pipeline = json.loads((self.store.root / "pipeline.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
        return {name: (entry or {}).get("status") for name, entry in (stages or {}).items()
                if isinstance(entry, dict)}

    def next_action(self):
        """The one next action — and never `wait_existing_job` for a job nobody is doing.

        `next` settles such a dispatch itself. A person asking "what now?" after a refused
        dispatch got "wait, and you may not cancel" and had no way out of it; the proof of
        what became of the agent is already on this host, so the answer is the repair.

        When the host can prove nothing, the answer is still "wait" — but it says so, and it
        carries the one command a person's word needs, because on TP2-2523 that word
        was recorded and freed nothing.
        """
        state = self.state()
        if any(d.get("status") == "running" for d in state.get("dispatches", {}).values()):
            if self.close_settled(state):
                state = self.state()
        action = self._next_action_for_state(state, self._pipeline())
        if action.get("action") == "wait_existing_job":
            import launch_card   # late, like dispatch_liveness: the card layer is read where it is asked
            dispatch = (state.get("dispatches") or {}).get(action.get("dispatch_id")) or {}
            answer, verdict = self.launch_answer(dispatch)
            if answer:
                # POSITION INVARIANT: after `close_settled` and after the liveness verdict - a dispatch the
                # host can prove `alive`, or that a repair already closed, never reaches this; `launch`
                # needs the verdict `unknown`. What it replaces is the answer "wait" for work nobody started.
                return answer
            action["liveness"] = verdict.get("state")
            action["evidence"] = verdict.get("evidence") or []
            action["release"] = launch_card.release_door(self.store.root, action.get("dispatch_id"))
        return self.with_resume_command(action, state)

    def with_resume_command(self, action, state):
        """`action` with the resume door beside the retry packet (FB-4, F-9): a `resume_checkpoint` whose agent is recorded can
        go on in place. The ONE place both `next` and `where` (`story_step._next`) decorate the action; others pass unchanged."""
        if action.get("action") == "resume_checkpoint":
            command = self._resume_command((state.get("dispatches") or {}).get(action.get("dispatch_id")))
            if command:
                action["resume_command"] = command
        return action

    def launch_answer(self, dispatch, rebuild=None):
        """`(answer, liveness verdict)` for one open dispatch; reads only (but for what `rebuild` writes).

        `answer` is the finished `launch` / `wait_start` dict - `liveness` and `evidence` already in it - or
        None, and the callers (`next_action`, `story_step._launch_from_where`) take it as it is: this is the
        ONE place the dict is built, so `next` and `where` cannot answer differently (FR-10).

        A desktop host that kept no transcript and no receipt for a dispatch nobody launched used to get
        `wait_existing_job` / `unknown` for ever (TP2-2406, the card lost to the exec cell's
        yield). `launch_card.launch_action` answers only when this host's own records show no launch,
        and only on the verdict `unknown`: `alive` is a proof of work, `returned` / `abandoned` /
        `never_started` are settled by the repair, and a launch offered for any of them could double an
        agent. The wrong direction here is only "do not offer a launch" (the old answer).

        `rebuild(dispatch) -> (written, why)`, when given, is asked once if the answer is `wait_start` (no
        card yet): it may write the card (`where` does); written -> the card layer alone is asked again (the
        liveness verdict, the costly read, is not taken twice); not written -> `why` replaces the reason of
        the `wait_start`. An exception of `rebuild` is the caller's (it writes a file).

        Never raises otherwise: the old answer stands. A reader that cannot be run is no ground for a launch,
        and the evidence NAMES it (FR-59): an empty list says "nothing is in the way", which is not what
        happened."""
        verdict = {"state": "unknown", "evidence": []}
        project = self._project_root()
        if project is None:
            verdict["evidence"] = [f"no qa-factory/config.json at or above {self.store.root}: the host's records of "
                                   "this dispatch cannot be located, so nothing is proved either way"]
            return None, verdict
        starts = self._dispatch_starts()
        record = dict(dispatch, started_at=starts.get(str(dispatch.get("id"))))
        try:
            verdict = self._liveness(project, record)
        except Exception as exc:   # the old answer; and a verdict that could not be taken is no ground for a launch
            return None, {"state": "unknown", "evidence": [
                f"the liveness verdict could not be taken ({type(exc).__name__}: {exc}), so nothing is proved either way"]}
        if verdict.get("state") != "unknown":
            return None, verdict
        evidence = list(verdict.get("evidence") or [])

        def ask():
            try:
                import launch_card
                extra = self._denial_evidence(dispatch, starts)
                # A receipt under ANY spelling of this folder forbids a launch (`launch_evidence`), so one name that
                # answers None answers for all; the answer is the first name's, `_ticket()`, as it always was (E21).
                answers = [launch_card.launch_action(project, name, self.store.root, record, extra_evidence=extra)
                           for name in self._story_names(project)]
                return None if any(answer is None for answer in answers) else answers[0]
            except Exception as exc:
                evidence.append(f"the launch card layer could not be read ({type(exc).__name__}: {exc}), so no "
                                "launch is offered")
                return None
        launch = ask()
        if launch and launch["action"] == "wait_start" and rebuild is not None:
            written, why = rebuild(dispatch)
            if written:
                launch = ask()
            elif why:
                launch["reason"] = why
        verdict = dict(verdict, evidence=evidence)
        if not launch:
            return None, verdict
        return dict(launch, liveness=verdict.get("state"), evidence=list(evidence)), verdict

    def _denial_evidence(self, dispatch, starts):
        """The refusals of the dispatch hook that belong to this dispatch, as evidence lines for
        `launch_card.launch_action`: this controller's own reader (`_denial_times`), so a row that names
        the dispatch AND a row of the Codex desktop host that names none (attributed by role, stage and
        time) are both seen, and `next` and `where` cannot disagree about them. Any row that belongs to
        the dispatch forbids a launch, whether or not a later launch outweighs it: the launch has its own
        evidence. A file that cannot be read is evidence too (an unknown is never a launch: FR-59); a
        single broken LINE that `_denial_times` cannot attribute to anybody is not (the worst that costs
        is one refused Agent call, never a double agent)."""
        try:
            times = self._denial_times(dispatch, starts, None)
        except OSError as exc:
            return [f"could not read {DENIALS_FILE}: {type(exc).__name__}"]
        if times:
            return [f"the dispatch hook refused the Agent call for this dispatch ({DENIALS_FILE})"]
        return []

    def checkpoint_packet(self, options=None):
        from session_handoff import continuation_packet
        options = options or {}
        state = self.state()
        state["next_action"] = self._next_action_for_state(state, self._pipeline())
        return continuation_packet(state, reason=options.get("reason"),
                                   page=options.get("page", 0), page_size=options.get("page_size", 50))

    @staticmethod
    def _free_dispatch_id(s, stage, role):
        """The next free `<stage>-<role>-<n>` — the naming every packet of this file uses."""
        taken = set(s.get("dispatches") or {})
        number = len([d for d in (s.get("dispatches") or {}).values()
                      if d.get("stage") == stage and d.get("role") == role]) + 1
        identifier = f"{stage}-{role}-{number}"
        while identifier in taken:
            number += 1
            identifier = f"{stage}-{role}-{number}"
        return identifier

    @staticmethod
    def _portable_paths(known):
        """The `known_paths` a stopped dispatch recorded, as a retry / relaunch packet carries them (t-329, B-249): the
        paths made portable against the roots THE RECORD names (`project_root`, `plugin_root` - its own generation,
        not this process's), so a story moved to another machine hands out a packet that `dispatch` resolves there,
        and a packet of another package generation is refused there by its fingerprint. A copy: the record is never
        touched. A record with no roots, or no paths, comes back as it was."""
        import contract
        known = copy.deepcopy(known or {})
        if not isinstance(known, dict):
            return known
        return contract.portable_known_paths(known, known.get("project_root"), known.get("plugin_root"))

    @staticmethod
    def _package_stamp():
        """`{"package_fingerprint", "package_version"}` of THIS package, or None when it cannot be read.

        The one definition is `runtime_paths.resolve_runtime`; it wants a project with a config only to list the
        repositories, which the fingerprint does not depend on, and a builder below is static (no store, no task), so
        it reads the package through a throwaway project (the temp dir holds nothing of the story and is gone
        before this returns)."""
        from runtime_paths import resolve_runtime
        try:
            with tempfile.TemporaryDirectory(prefix="qa-stamp-") as home:
                (Path(home) / "qa-factory").mkdir()
                (Path(home) / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
                runtime = resolve_runtime(home, home)
            return {"package_fingerprint": runtime["package_fingerprint"], "package_version": runtime["package_version"]}
        except (OSError, ValueError, KeyError):
            return None

    @staticmethod
    def _stamped_paths(known):
        """The `known_paths` of a packet built NOW from a recorded one (rework, retry, relaunch; t-335 A1): portable, and
        stamped with the fingerprint and version of the package that builds it. `dispatch` compares the package that
        BUILT a packet with the one that dispatches it; the record's own stamp names the package that made the OLD
        dispatch, so copying it refused every rework after any package change, and the door the refusal names
        (`prepare`) cannot make a rework. A stamp this package cannot read is left out - an unknown is not compared
        (FR-41) - never the old one. A record that carried NO stamp (a legacy packet, a hand-built one) gets none: it
        was never compared, and the project check of `known_paths_for_dispatch` is what stands for it. An empty or
        non-dict record comes back as it was."""
        made = Controller._portable_paths(known)
        if not isinstance(made, dict) or "package_fingerprint" not in made:
            return made
        made.pop("package_fingerprint", None)
        made.pop("package_version", None)
        made.update(Controller._package_stamp() or {})
        return made

    @staticmethod
    def _retry_packet(s, dispatch):
        """The ready `--operation dispatch` request that resumes a stopped role in one step.

        TP2-2553: a role stopped, the hook refused the resume (pipeline.json recorded
        no `agent_id`), `accept` refused the blocked dispatch, and the orchestrator hand-built
        this packet — five steps, two receipts, about two hours. Everything in it belongs to
        the dispatch that stopped; only the id is new. The checkpoint is inherited verbatim
        because the validator demands it: a retry that rewrites what the role still owes is a
        new dispatch, not a resume. `parent_retry` is what makes the old one `superseded`
        instead of a second open dispatch of the same window.

        A retry is the orchestrator's decision — this builds the packet and journals nothing.
        """
        stage, role = str(dispatch.get("stage") or ""), str(dispatch.get("role") or "")
        if not stage or not role or not dispatch.get("input_hash"):
            return None
        if dispatch.get("reason") == BUDGET_EXHAUSTED:
            return None  # the validator refuses this resume; a packet would only be rejected
        identifier = Controller._free_dispatch_id(s, stage, role)
        packet = {"id": identifier, "stage": stage, "role": role,
                  "scope": copy.deepcopy(dispatch.get("scope") or []),
                  "input_hash": dispatch.get("input_hash"),
                  "known_paths": Controller._stamped_paths(dispatch.get("known_paths")),
                  "budget": copy.deepcopy(dispatch.get("budget") or {}),
                  "parent_retry": dispatch.get("id"),
                  "expected_revision": s.get("revision"),
                  "idempotency_key": "dispatch:" + identifier}
        if dispatch.get("checkpoint") is not None:
            packet["checkpoint"] = copy.deepcopy(dispatch["checkpoint"])
        packet.update(Controller._original_request(dispatch))
        # `plan_rows` is part of the binding, so a recorded binding wins; a record with none (or one
        # made before the field) falls back to the record's own rows, by presence (`[]` stays `[]`).
        if "plan_rows" not in packet:
            Controller._carry_plan_rows(dispatch, packet)
        return packet

    @staticmethod
    def _original_request(dispatch):
        """What a continuation carries over from the request its dispatch was made with.

        Read from `request_binding` - the request as committed, which nothing afterwards
        rewrites - and never from the record's own fields: a checkpoint, an acceptance and the
        liveness repair all overwrite the record's `reason`, and a pin may have moved since, so
        the links are the ORIGINAL ones and are never re-resolved. Every value is a deep copy:
        a packet is edited by whoever dispatches it, and the record must not move with it.
        A record with no binding (imported from a pre-controller pipeline, or built by a caller
        that predates the field) falls back to the four fields this always copied."""
        binding = dispatch.get("request_binding")
        if isinstance(binding, dict):
            return copy.deepcopy(binding)
        return {key: copy.deepcopy(dispatch[key])
                for key in ("purpose", "execution_kind", "manual_case_ids", "limits")
                if dispatch.get(key)}

    @staticmethod
    def _carry_plan_rows(dispatch, packet):
        """A resumed or relaunched S4 designer is credited exactly as the original would have been.

        By PRESENCE, not truthiness: a present `plan_rows: []` means "zero rows" and an absent key
        means "made before this field" - dropping an empty list would turn the first into the
        second and let the evidence clause credit a receipt it must not (B-224, E-2/E-6).
        """
        if isinstance(dispatch.get("plan_rows"), list):
            packet["plan_rows"] = copy.deepcopy(dispatch["plan_rows"])

    @staticmethod
    def _retry_reason(dispatch, packet):
        """What `next`/`recover` say beside the packet — or beside its absence."""
        stopped = str(dispatch.get("reason") or "").strip()
        if packet:
            return ((stopped + "; " if stopped else "")
                    + "dispatch this packet with --operation dispatch --input <file>; it "
                    + f"inherits the checkpoint and supersedes {dispatch.get('id')}")
        if dispatch.get("reason") == BUDGET_EXHAUSTED:
            return (stopped + "; no retry packet: a hard quota exhaustion is not "
                    "automatically retried. Raise the quota or dispatch fresh work with a "
                    "new input hash.")
        return stopped

    @staticmethod
    def _relaunch_packet(s, dispatch):
        """The ready dispatch request for work that never reached an agent.

        Everything it needs is in the receipt that was written before the launch failed —
        stage, role, scope, input hash, paths, budget. Only the id has to be new, because the
        old one is history now.
        """
        from contract import retry_reason_for
        stage, role = str(dispatch.get("stage") or ""), str(dispatch.get("role") or "")
        if not stage or not role or not dispatch.get("input_hash"):
            return None
        identifier = Controller._free_dispatch_id(s, stage, role)
        packet = {"id": identifier, "stage": stage, "role": role,
                  "scope": copy.deepcopy(dispatch.get("scope") or []),
                  "input_hash": dispatch.get("input_hash"),
                  "known_paths": Controller._stamped_paths(dispatch.get("known_paths")),
                  "budget": copy.deepcopy(dispatch.get("budget") or {}),
                  "relaunch_of": dispatch.get("id"),
                  # The cause travels with the packet, so the second attempt is recorded with
                  # the reason the first one stopped instead of being another bare repeat.
                  "retry_reason": retry_reason_for(dispatch),
                  "expected_revision": s.get("revision"),
                  "idempotency_key": "dispatch:" + identifier}
        packet.update(Controller._original_request(dispatch))
        if "plan_rows" not in packet:
            Controller._carry_plan_rows(dispatch, packet)
        return packet

    @staticmethod
    def _next_action_for_state(s, pipeline=None):
        environment_jobs = [job for job in s.get("environment_jobs", []) if not job.get("settled")]
        if environment_jobs:
            job = environment_jobs[0]
            return {"action": "observe_environment_job", "stage": "S5", "job_id": job.get("job_id"),
                    "status": job.get("status"), "receipt_ref": job.get("receipt_ref"),
                    "reason": "continue the recorded preparation; do not start a duplicate"}
        active = [d for d in s["dispatches"].values() if d["status"] == "running"]
        if active:
            return {"action": "wait_existing_job", "dispatch_id": active[0]["id"],
                    "cancel_allowed": bool(active[0].get("cancellation")),
                    "reason": "Polling timeout, missing digest and 30+ minute discovery do not authorize cancellation"}
        # A stopped dispatch that LATER corrective work on the same stage already replaced is
        # history, not an open checkpoint. Without this, a story kept being told to resume a
        # dispatch whose job was done: the corrective path marks nothing on its predecessor
        # unless it goes through reconcile_dispatch, so the old `incomplete` stayed forever at
        # the end of the list and won every recommendation.
        #
        entries = list(s["dispatches"].values())
        # The closure test the `closed` answer below uses - one reading, computed once - and the work a person's word is owed
        # on (`held`): on a closed story every dispatch that never started, on a story a PARTIAL `reopen_story` opened the ones
        # it left out (B1).
        closure = closure_of(s, pipeline)
        closed = closure["closed_at"] if closure["state"] == "closed" else ""
        held = held_dispatches(s, closure["state"] != "open")

        # A dispatch that never reached an agent leaves the stage startable - and the packet
        # to start it with. On TP1-15045 the orchestrator spent three minutes rebuilding
        # that packet out of `events.jsonl` by hand. (Decided here, before the returns and stops
        # below, because whether it HAS a move decides what it may hide.)
        #
        # A REWORK of an accepted stage that never started is relaunchable whatever the stage's
        # status: the stage is completed BECAUSE the work was accepted, and the repair somebody
        # asked for is what is still owed - on TP2-2406 S5 was repaired at S8's request
        # after it had been accepted, the repair never started, and `next` had no move for it.
        # Two limits, both invariants. The EXEMPTION (a never-started rework of a completed
        # stage) does not apply to a CLOSED story: reopening one is a person's word (`release`,
        # `rework --reason`, which stamp `reopened_at`) and a relaunch carries no such stamp, so
        # the exemption is what must never start work there. It does not cover a dispatch a
        # person RELEASED either (that word freed the stage, it asked for nothing). What is NOT
        # changed here: a never-started dispatch of a stage that is still OPEN is judged as
        # before, on a closed story too (`closure_repairs` leaves such a state on purpose), and
        # one with no `rework_of` on a completed stage is history - that stage's work was done
        # by something else.
        # B-331 (C1-6a): on a CLOSED story nothing but the retro is relaunched - the rest is `held` (below) until a person
        # says `run again` (`reopen_story`) or `leave` (`leave_unlaunched`). A dispatch a `reopen_story` LEFT out of the set
        # it covered stays held after the reopen too: a word covers only what the question named.
        left_held = left_held_ids(s)

        def relaunchable(d):
            if not relaunch_shape(s, d) or str(d.get("id")) in left_held:
                return False
            if d.get("stage") == RETRO_STAGE and held:
                return False        # edge 3: the retro reads the story's final state, so it runs AFTER the held question's answer
            if closure["state"] == EXECUTING:
                return owed_executor(s, d)      # never the retro, never another dispatch: only the executor of a due order
            if closed:
                return (d.get("stage") == RETRO_STAGE
                        and (s["stages"].get(RETRO_STAGE, {}) or {}).get("status") not in ("completed", "skipped"))
            return True

        unlaunched = [d for index, d in enumerate(entries) if relaunchable(d) and not has_later_work(entries, index)]
        has_a_move = {id(d) for d in unlaunched}

        def holds_a_move(later):
            """Will `next` act on this dispatch, or has it been settled for good?"""
            status = later.get("status")
            if status in (NEVER_STARTED, RELEASED):
                return id(later) in has_a_move
            return status == "accepted" or status == "running" or status in SETTLED or status in STOPPED

        # A stopped dispatch that LATER work on the same stage already took over is history, not
        # an open checkpoint. Without this, a story kept being told to resume a dispatch whose
        # job was done: the corrective path marks nothing on its predecessor unless it goes
        # through reconcile_dispatch, so the old `incomplete` stayed forever at the end of the
        # list and won every recommendation.
        #
        # "Later work" is a LATER dispatch of the same stage that is still a fact of the story
        # (not `superseded` / `stale`, which a retry or an invalidation already made history)
        # AND that `next` acts on or that is settled: accepted, running, returned, stopped, or
        # actually in `unlaunched`. It used to be only an ACCEPTED later dispatch, so an older
        # return kept shadowing a newer dispatch that never started (TP2-2406, B-312);
        # hiding behind ANY later dispatch went too far the other way - one `next` does not act
        # on (never started on an accepted stage, released there) took the older return with it
        # and `await_gate` answered over an unsettled return. INVARIANT (FR-40, FR-42): every
        # return or stop is acted on, or hidden by a dispatch that is - nothing is dropped silently.
        superseded_by_later_work = {
            id(d) for index, d in enumerate(entries)
            if any(later.get("stage") == d.get("stage")
                   and later.get("status") not in {"superseded", "stale"}
                   and holds_a_move(later)
                   for later in entries[index + 1:])
        }
        # A role that stopped without acceptance. The evidence it wrote is still on disk and
        # its digest is in the receipt, so the orchestrator settles it — accept, record the
        # block, or send the work back — instead of waiting for an agent that is gone.
        returned = [d for d in entries if d.get("status") in SETTLED
                    and id(d) not in superseded_by_later_work]
        if returned:
            last = returned[-1]
            from contract import retry_reason_for
            return {"action": "resolve_return", "dispatch_id": last.get("id"),
                    "stage": last.get("stage"), "role": last.get("role"),
                    "dispatch_status": last.get("status"),
                    "digest": last.get("returned_digest") or "",
                    "options": ["accept", "checkpoint", "rework"],
                    # A rework built from here carries the cause, never a bare repeat.
                    "retry_reason": retry_reason_for(last),
                    "reason": last.get("reason") or "the role stopped without acceptance; accept its "
                              "evidence, record the block, or send the work back"}
        stopped = [(index, d) for index, d in enumerate(entries)
                   if d["status"] in STOPPED and id(d) not in superseded_by_later_work]
        if stopped:
            index, last = stopped[-1]
            action = {"action": "resume_checkpoint", "dispatch_id": last["id"],
                      "reason": last.get("reason"), "checkpoint": last.get("checkpoint")}
            # The packet only goes out while nothing of the same stage+role came after: once a
            # successor exists, the answer is that dispatch, not a second retry of this one.
            if not any(other.get("stage") == last.get("stage")
                       and other.get("role") == last.get("role") for other in entries[index + 1:]):
                packet = Controller._retry_packet(s, last)
                if packet:
                    action["packet"] = packet
                action["reason"] = Controller._retry_reason(last, packet)
            return action
        # t-2181 PC-6 (B3, B4), t-2277 J-4: the story HELD FOR CODE. POSITION: after the returned / stopped dispatches above (work that
        # somebody started is settled first) and BEFORE `if unlaunched:` and the stage loop. INVARIANT this position preserves: a held
        # story never dispatches a stage >= `held_from` - the relaunch below is cut to the never-started dispatches of stages BELOW
        # `held_from` (the rest are listed in `held`, never relaunched, never prepared) - and a rework of a stage < `held_from` runs
        # inside the hold (its dispatch is relaunched / waited on above, its stage is prepared by the loop) and the hold answers again
        # at `held_from`, in the stage loop. A STOPPED story is terminal: no relaunch of any dispatch. The record is the controller's
        # own state, never the pipeline argument (E-W2): `next` called without a pipeline still holds a story that was parked.
        hold, held_number = _hold_of(s)
        if hold["state"] != "none":
            held_ids = [d for d in unlaunched if _stage_no(d) >= held_number]
            unlaunched = [d for d in unlaunched if _stage_no(d) < held_number]
            below_open = [i for i in range(held_number) if s["stages"].get(f"S{i}", {}).get("status") not in ("completed", "skipped")]
            if hold["state"] == "stopped" or (not unlaunched and not below_open):
                return _hold_action(s, hold, held_number, held_ids)
        if unlaunched:
            packet = Controller._relaunch_packet(s, unlaunched[-1])
            if packet:
                return {"action": "relaunch", "stage": unlaunched[-1].get("stage"),
                        "role": unlaunched[-1].get("role"),
                        "closed_dispatch_id": unlaunched[-1].get("id"),
                        "retry_reason": packet.get("retry_reason"),
                        "reason": unlaunched[-1].get("reason") or "this dispatch never reached an agent",
                        "dispatch_request": packet, "revision": s["revision"]}
        # The orders of gate B (t-1509): gate B is decided and S8 is done, but what the person decided there is not carried out
        # yet - the story is neither open nor closed. After the settling of started work above, before `closed` below.
        if closure["state"] == EXECUTING:
            return _execute_gate_b_action(s, held)
        # Everything above settles work somebody started; everything below asks what the
        # story does next — and a CLOSED story does nothing next. TP2-2534 answered
        # `await_gate A` with gate B decided, S8 done and the MR merged, because the stage
        # loop below knows stage statuses and nothing else (I-92). The retro is the one
        # stage that still runs on a closed story, so its id travels with the answer.
        #
        # A story a person reopened for PART of its held work (B1) is open, and still owes that person the question about
        # the rest: the covered work above ran first (relaunch / wait / settle), and now the held work is asked again - before
        # the stage loop answers `prepare_stage S9`. It travels in the same `closed` action (the driver has one branch for
        # held work), with the reopening beside the original `closed_at`.
        if closed or held:
            if closed:
                action = {"action": "closed", "closed_at": closed, "revision": s["revision"],
                          "reason": "gate B is decided and S8 is done, and every order it gave is settled: this story is finished. "
                                    "Going back to it is a person's word. " + _closed_story_doors(s, None, held)}
            else:
                view = closure_view(s, pipeline)
                action = {"action": "closed", "closed_at": str(view.get(CLOSED_AT) or ""), "reopened_at": str(view.get(REOPENED_AT) or ""),
                          "revision": s["revision"],
                          "reason": "this story was reopened by a person's word for other work, and the work it held back "
                                    "that was not named still never started."}
            if held:
                # Work that never started: asked about first, never started on a closed story (B-331). No packet travels
                # with it - a packet dispatched on a closed story is refused; `reopen_story` is the one road.
                action["held"] = [{"dispatch_id": d.get("id"), "stage": d.get("stage"), "role": d.get("role"),
                                   "reason": str(d.get("reason") or "this dispatch never reached an agent")}
                                  for d in held]
                action["reason"] += (f" {len(held)} dispatch(es) that never started are held for a person's word: "
                                     "`--operation reopen_story` starts them, `--operation leave_unlaunched` leaves them.")
            if s["stages"].get(RETRO_STAGE, {}).get("status") not in ("completed", "skipped"):
                action["stage"] = RETRO_STAGE
                action["retro_pending"] = True
            return action
        rollover = orchestrator_rollover_due(s.get("window_counters", {}),
                                             s.get("window_context_percent"))
        if rollover["rollover_pending"]:
            from session_handoff import can_takeover
            safe = can_takeover(s)
            if safe["ready"]:
                return {"action": "handoff_ready", "revision": s["revision"], **rollover}
            return {"action": "rollover_pending", "revision": s["revision"],
                    "wait_for": safe, **rollover}
        for i in range(10):
            if s["stages"].get(f"S{i}", {}).get("status") not in ("completed", "skipped"):
                # t-2181 PC-6: the stop INSIDE the stage loop. A held story answers here for the first stage at or after
                # `held_from` that is not done (the work below it - a rework of S0..held_from-1 - was prepared by this loop
                # and its end lands here again); a story that is DUE (S0..S5 done, a deliverable side absent, no `await` yet)
                # is asked to wait before S6 is prepared. `i` is the loop's own number, read BEFORE `awaits_acceptance` moves
                # it, so "S5 is done" is exactly what reaching `i >= 6` means. No pipeline (E-W2): not due, the hold above stands.
                if hold["state"] != "none" and i >= held_number:
                    return _hold_action(s, hold, held_number, [])
                import contract
                if (i >= 6 and hold["state"] == "none" and isinstance(pipeline, dict) and contract.parks_after_s5(pipeline)):
                    return {"action": "await_implementation", "cause": contract.AWAITING_DEFAULT_CAUSE,
                            "held_from": contract.AWAITING_DEFAULT_HELD_FROM, "sides": contract.story_sides(pipeline),
                            "revision": s["revision"],
                            "reason": "S5 is done and a side this story delivers does not exist yet: record the wait (`--operation await`), "
                                      "no stage from S6 runs until the code arrives"}
                # X7-6: the author stopped and its stage awaits the CONSUMER's acceptance - the next stage is the consumer's to open
                # (the one reader `awaits_acceptance`, AR-13); the loop then asks that stage's gate like any other.
                from acceptance import awaits_acceptance
                if i < 9 and awaits_acceptance(s, f"S{i}", pipeline if isinstance(pipeline, dict) else None):
                    i += 1
                    # F6 (POSITIONAL): the move can carry `i` into the held range (a hold from S7 while S6 awaits its analyst), and
                    # no stage of that range is prepared on a held story: the stop is repeated after the move
                    if hold["state"] != "none" and i >= held_number:
                        return _hold_action(s, hold, held_number, [])
                gate = "B" if i == 9 else "A" if i >= 5 else None
                if gate and not any(d.get("gate") == gate and d.get("status") == "approved"
                                    and d.get("source_revision") == s.get("source_revision")
                                    for d in s["decisions"].values()):
                    return {"action": "await_gate", "gate": gate, "revision": s["revision"]}
                return {"action": "prepare_stage", "stage": f"S{i}", "revision": s["revision"]}
        return {"action": "complete", "revision": s["revision"]}


# Each of these has its OWN handler in `main`; some of them write (`next` through close_settled, `recover`,
# `gate-decision`, `rework`, `release` commit to the journal; `gate-preflight` writes a PROJECT-level file,
# REPORTER_REHEARSALS_FILE, not a story folder). The tuple names the route, not "read-only" (CX1-18 I6).
ROUTED_OPERATIONS = ("prepare", "next", "checkpoint-packet", "baseline-inputs", "deployment-inputs",
                     "gate-inputs", "stage-scope", "recover", "gate-decision", "rework",
                     "gate-preflight", "release")
# These go through `Controller.apply` / `Controller.validate` (the `else` branch of `main`).
APPLY_OPERATIONS = ("initialize", "dispatch", "checkpoint", "accept", "decision", "invalidate",
                    "revise_plan", "reconcile_dispatch", "technical_normalize", "semantic_reopen",
                    "handoff", "orchestrator_telemetry", "coverage_migration", "request_cancel",
                    "policy", "code_only", "mutation", "reopen_story", "leave_unlaunched", "resume", "settle_order",
                    # t-2181 PC-6: the story held for code. `await` and `arrive` take `--input` (the driver builds them); the other two
                    # are the person's word and build their request from flags (`stop_waiting`, `first_look_continue`).
                    "await", "arrive", "stop_waiting", "first_look_continue")
HOLD_OPERATIONS = ("await", "arrive", "stop_waiting", "first_look_continue")
# The operations whose EVENT has another name than the operation: the person's `first_look_continue` is recorded as the fact
# `first_look_continued` (the one place that maps them; `apply` commits under it, the projection reads it).
EVENT_KIND = {"first_look_continue": "first_look_continued"}
OPERATIONS = ROUTED_OPERATIONS + APPLY_OPERATIONS     # every name the CLI accepts
# The operations whose CLI branch does `Path(a.input)` with no guard: every APPLY operation but the four that build
# their request from flags (`checkpoint` from --dispatch/--status/--reason; `reopen_story` and `leave_unlaunched` from
# --dispatch + the person's words; `resume` from --dispatch [--agent-id]), plus the routed `baseline-inputs`. The ONE list
# `_cli_story_root` reads (S7-1).
INPUT_FILE_OPERATIONS = tuple(op for op in APPLY_OPERATIONS
                              if op not in ("checkpoint", "reopen_story", "leave_unlaunched", "resume", "settle_order",
                                            "stop_waiting", "first_look_continue")) + ("baseline-inputs",)

# `gate_A` was the cost experiment's stop; `gate_B` stops a story that is delivered but whose retro the
# project does not want. Anything else in config.json is read as no stop at all (moved here from
# story_step.py, HF1-8: the gate-decision answer applies the same marker, so there is ONE reader).
# `STOP_VALUES` is imported from hooklib (the one list, GW1-19).
# Which gate each marker waits for, and which stages are past it.
STOP_GATES = {"gate_A": ("A", {f"S{i}" for i in range(5, 10)}), "gate_B": ("B", {"S9"})}


def stop_after() -> str | None:
    """The project's `pipeline.stop_after` when it is exactly `gate_A` or `gate_B`, else None.

    The ONE reader of the key. An absent project, a config that is not an object, a `pipeline` that is
    not an object and a value of any other kind or spelling all mean "no stop": the key is matched
    whole, and an unknown value never becomes a stop, nor a refusal of a gate."""
    try:
        config = load_config() or {}
    except Exception:
        config = {}
    block = config.get("pipeline") if isinstance(config, dict) else None
    value = block.get("stop_after") if isinstance(block, dict) else None
    return value if isinstance(value, str) and value in STOP_VALUES else None


def with_stop_after(action: dict, marker: str | None) -> dict:
    """`action` as the project's planned stop reads it: the gate the marker names is presented and
    recorded as usual, a stage past it is `{"action": "stop", ...}`, everything else is unchanged."""
    if not marker:
        return action
    gate, past = STOP_GATES[marker]
    if action.get("action") == "await_gate" and action.get("gate") == gate:
        return dict(action, stop_after=marker,
                    note=f"present Gate {gate}, record the person's decision, then STOP: "
                         f"pipeline.stop_after is {marker}, no later stage runs in this project")
    if action.get("stage") in past:
        return {"action": "stop", "reason": f"pipeline.stop_after is {marker} and Gate {gate} is "
                "decided; no later stage runs in this project", "revision": action.get("revision")}
    return action


def write_risk_line(c: "Controller", reason: str) -> tuple:
    """The journal line the delivery guard reads (`stage_guard.rule_delivery`) for a decision to deliver with known gaps: `(True, "")`,
    or `(False, <what stopped it and the door>)`. ONE writer, `log_append.write`, in this process (AR-14, no subprocess). Its `task` is
    the story's name as the guard compares it (`c._ticket()`, exactly). `validate` runs first (`write` does not call it). `write`
    prints an OK line and calls `require_project`, which EXITS with code 3 when no project marker resolves: both are caught - the
    decision stands whatever happens here (E7) - and the printed line never reaches the answer."""
    import contract
    import io
    ticket = c._ticket()
    door = contract.risk_journal_door(ticket)
    try:
        import log_append
        record = log_append.build_record({"event": "deliver_with_risks", "task": ticket, "reason": reason})
        why = "; ".join(log_append.validate(record))
        if not why:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                log_append.write([record])
    except (Exception, SystemExit) as exc:
        why = f"{type(exc).__name__}: {exc}" if isinstance(exc, Exception) else "no project marker resolved for the journal"
    if why:
        return False, (f"the decision is recorded, but the journal line the delivery guard reads was not written ({why}). Write it, "
                       f"with the reason in a file: `{door}`")
    return True, ""


def gate_decision_answer(c: "Controller", request: dict, as_is_ids=(), manual_pass=(), risk_line="", questions=None) -> dict:
    """The answer of a RECORDED gate decision: what to do next first, the window verdict, the receipt last.

    DC1-19: `questions` (when the caller gives it) is what the person's words did to the question register and the plan
    (`_gate_questions_view`): `recorded`, `already`, `unread`, `named_not_recorded`, `lines`, `rework`, `plan_not_changed`. It sits before the
    receipt with `risks`, so an answer never says "recorded" for a line the register does not hold.

    HF8-23: a request that carries `deliver_with_risks` gets its journal line HERE, AFTER the decision is recorded (POSITION: no journal
    line stands over an unrecorded decision; a refused or build-only call never reaches here). The answer's `risks` says what was
    recorded and what was not: `{"recorded": true, "journal": true|false, "line": <why and the door, when the line was not written>}`;
    `risk_line` is the controller's own note when the words held a decision it did not record (two different reasons) or when the
    reason came from the flag over a different line of the words.

    `next_action` is composed with the project's `stop_after` (the same composition `story_step` applies,
    so `where`, `finish` and this answer cannot differ). `window` is computed AFTER the decision is
    recorded and after `next_action`: a refused or build-only call never reaches here, so a window line
    never stands over an unrecorded decision. It is `null` exactly when the next action is `stop` (nothing
    follows in this run, and a stop and a window line never print together). The verdict says WHERE the
    orchestrator continues (this window or the next); `next_action` says WHAT it runs - a change never
    alters or skips it. The receipt stays whole and last: an answer cut by a reader keeps the first keys."""
    receipt = c.apply("decision", dict(request))
    risks = {}
    risks_field = request.get("deliver_with_risks")
    reason = risks_field.get("reason") if isinstance(risks_field, dict) else None
    if isinstance(reason, str) and reason.strip():
        written, why = write_risk_line(c, reason)
        said = " ".join(part for part in (why, risk_line) if part)
        risks = {"recorded": True, "journal": written, **({"line": said} if said else {})}
    elif risk_line:
        risks = {"recorded": False, "journal": False, "line": risk_line}
    action = with_stop_after(c.next_action(), stop_after())
    window = None
    if action.get("action") != "stop":
        try:
            import window_budget
            verdict, line = window_budget.window_verdict(
                c._ticket(), {"A": "S4", "B": "S8"}[request["gate"]], gate_recorded=True)
        except Exception:
            verdict, line = "unknown", ""
        window = {"verdict": verdict, "line": line}
    # `approve as is` (RH1-6): the row says over WHICH items, between the window and the receipt (the receipt stays last)
    as_is = {"as_is": "approved as is over: " + ", ".join(as_is_ids)} if as_is_ids else {}
    # HF4-14: what the manual-agent pass did before the decision (a row made executable, or an obligation that stayed as
    # planned and why), one line each; absent when the plan has no manual-agent row. Before the receipt, which stays last.
    manual = {"manual_pass": list(manual_pass)} if manual_pass else {}
    return {"recorded": True, "next_action": action, "window": window, **as_is, **manual,
            **({"risks": risks} if risks else {}), **({"questions": questions} if questions is not None else {}),
            "decision": receipt}


# --- DC1-19: one executor of a person's words at a gate, for the conductor and the driver alike --------------------------------
# `gate-decision` is the ONE call that records what a person decides at gate A or B (AR-15). Gate A: the answers are applied to the plan
# BEFORE the decision is built (the decision binds the plan as patched); a call that does not record leaves the plan, `test-plan.md`
# and the answers file as they were, and a REFUSED call then records the answers alone (the words stand, FR-8; the next call's
# `apply_recorded_answers` patches the plan). Gate B: the answers are recorded, the plan is never read or written.

ANSWER_REWORK_OWNERS = {"strategist": ("S3", "qa-test-strategist", "--rows"), "designer": ("S4", "qa-case-designer", "--cases")}


def _flag_text(flag: str, path: str) -> tuple:
    """`(text, problem)`: the text of a file a gate-decision flag names, whole; the problem names THAT flag (`person_words.read` takes the
    file flag's name, F-9). The caller (`main`) refuses with it, so no refusal is raised from a helper."""
    import person_words
    try:
        return person_words.read(None, path, flag, flag), ""
    except ValueError as exc:
        return "", str(exc)


def _flag_json(flag: str, path: str, what: str) -> tuple:
    """`(object, problem)`: the JSON object a gate-decision flag's file holds, else the problem naming the flag and the shape expected (E21)."""
    text, problem = _flag_text(flag, path)
    if problem:
        return {}, problem
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return {}, f"{flag} {path} is not JSON. Expected {what}; nothing was recorded"
    if not isinstance(data, dict):
        return {}, f"{flag} {path} holds {type(data).__name__}. Expected {what}; nothing was recorded"
    return data, ""


def _gate_inputs_of(a) -> tuple:
    """`(answers text or None, shown, remedies, problems)` from the gate-decision flags, read ONCE in `main` before any state is read or
    written (E21): a missing or broken file, or `--no-answers` with `--answers-file`, is a problem that names the flag (`main` refuses).
    `--risks-file` is read here too and set on `a.risks_text` (None without the flag): its refusal names `--risks-file`, not `--words-file`."""
    problems = []
    if a.risks_file is not None:     # the same reader as the other files, the refusal names THIS flag (F-9, HF8-23)
        a.risks_text, bad_risks = _flag_text("--risks-file", a.risks_file)
        if bad_risks:
            problems.append(bad_risks)
    if a.no_answers and a.answers_file is not None:
        problems.append("--no-answers and --answers-file contradict each other: the first records no answer, the second names the lines to "
                        "record. Give one of them")
    text, shown, remedies = None, {}, {}
    for flag, path, what in (("--answers-file", a.answers_file, ""), ("--shown-file", a.shown_file, "an object {question id: the row hash the person was shown}"),
                             ("--remedies-file", a.remedies_file, "an object {case id: remedy}")):
        if path is None:
            continue
        got, problem = _flag_text(flag, path) if not what else _flag_json(flag, path, what)
        if problem:
            problems.append(problem)
        elif flag == "--answers-file":
            text = got
        else:
            shown, remedies = (got, remedies) if flag == "--shown-file" else (shown, got)
    return text, shown, remedies, problems


def _gate_risks(a, gate: str, text: str) -> tuple:
    """`(reason or None, the controller's note)`: the person's decision to deliver with known gaps (HF8-23, gate B only), from the flag or
    from a whole line of the answer's own lines (`text`: not the `Earlier answer at this gate:` tail, F1). The flag wins over a line that
    differs (E4), two lines with different reasons record nothing as risk (E5); a line with no reason is refused by the builder (E1)."""
    risks, risk_line = (a.risks_text.strip() if a.risks_text is not None else None), ""     # the outer blanks of a file are not the reason
    if gate != "B":
        return risks, risk_line
    import question_register as QR
    try:
        token = QR.risk_reason_of(text)
    except RuntimeError as exc:         # the vocabulary file is unusable: a package defect, said in the answer, the decision goes on (P1)
        return risks, f"the words were not read for a decision to deliver with known gaps: {exc}"
    if a.risks_text is not None and token["found"] and (token["conflict"] or token["reason"] != risks):
        risk_line = ("the reason of --risks-file was recorded; the words hold a `deliver with known gaps` line with "
                     + ("another reason" if not token["conflict"] else "different reasons") + ", which was not used")
    elif a.risks_text is None and token["conflict"]:
        risk_line = ("the words hold two `deliver with known gaps` lines with different reasons, so no decision to deliver with "
                     "known gaps was recorded: ask the person which reason stands, then give it by --risks-file")
    elif a.risks_text is None and token["found"]:
        risks = token["reason"]
    return risks, risk_line


def _story_file_paths(root: Path) -> list:
    """The three files a gate A answer moves BEFORE the decision (`test-plan.json`, `test-plan.md`, the answers file): the paths whose
    bytes a call that does not record puts back. NOT the manifest: its put is deferred until the call is certain to record (B1)."""
    import contract
    import planning_contract
    import question_register as QR
    paths = [planning_contract.story_plan_path(root), contract.artifact(root, "test-plan.md"), Path(root).joinpath(*QR.ANSWERS_REL)]
    return [Path(p) for p in paths if p is not None]


def _snapshot_files(root: Path) -> dict:
    """{path: its bytes, or None when the file is absent} of `_story_file_paths`."""
    return {p: (p.read_bytes() if p.is_file() else None) for p in _story_file_paths(root)}


def _restore_files(snapshot: dict) -> None:
    """The snapshot's bytes back: a file that differs is rewritten, one that was absent is removed. The owner's rollback (a byte copy, never
    `git checkout`); the ONE place the controller writes these files itself."""
    for path, data in snapshot.items():
        if data is None:
            path.unlink(missing_ok=True)
        elif not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)


def _owed_rework_parts(root, rework: list) -> tuple:
    """`(parts, doors)`: which owner must rework what, and the door that opens each (`rework`, by file). The one reading of an owed rework
    for the refusal (`_owed_rework_text`) and for the recorded `approve as is` (`_rework_left_text`)."""
    import person_words
    parts, doors = [], []
    for owner, (stage, role, flag) in ANSWER_REWORK_OWNERS.items():
        where = list(dict.fromkeys(str(w.get("where")) for w in rework if w.get("owner") == owner))
        if where:
            parts.append(f"the {owner} must rework {', '.join(where)}")
            doors.append(person_words.door(f"controller.py --task-root {root} --operation rework --stage {stage} --role {role} {flag} {','.join(where)} --cause question_answer --brief"))
    other = sorted({str(w.get("owner")) for w in rework if w.get("owner") not in ANSWER_REWORK_OWNERS})
    if other:
        parts.append("someone must rework what " + ", ".join(other) + " owns")
    return parts, doors


def _owed_rework_text(root, rework: list) -> str:
    """One sentence for the rework gate A cannot record over (B2): which owner must rework what, and the door that opens it (`rework`, by
    file) - or the word that approves over it."""
    parts, doors = _owed_rework_parts(root, rework)
    try:
        import gate_brief
        word = gate_brief.as_is_word_of("A")
    except Exception:
        word = ""
    return ("your recorded answers no longer fit the plan, so gate A is not recorded yet: " + "; ".join(parts) + ". Run "
            + " and ".join(f"`{d}`" for d in doors or ["the rework of the owner named above"]) + (f", or answer `{word}` to approve over it" if word else ""))


def _unchanged_branches(root, view: dict) -> list:
    """Gate B: the questions the words answered (`recorded` and `already` - a retry after a refusal records nothing new, F-5) whose
    plan rows still branch on them: `[{id, rows}]`. Reads the plan only."""
    import planning_contract as PC
    _path, _doc, rows, _problem = PC._plan_state(Path(root))
    seen, out = set(), []
    for item in [*view.get("recorded", []), *view.get("already", [])]:
        qid = str(item).split(":", 1)[0]
        held = [str(r.get("id") or f"row[{i}]") for i, r, _e in PC._row_branches(rows or [], qid)]
        if held and qid not in seen:
            out.append({"id": qid, "rows": held})
        seen.add(qid)
    return out


def _gate_questions_view(root, text: str, before, case_ids: list, gate: str, told: dict, refused: bool) -> dict:
    """The `questions` key of a gate decision's answer or refusal: the register's own view of the words (`QR.gate_words_view`) and what
    the plan did (`lines`, `rework`, `not_applied_yet`, `plan_not_changed`). Reads only; an unreadable register is `{"unknown": ...}` with
    the rest (FR-41); it never raises.

    `told` = `{"moves": what the plan's patch did, "notes": what the call itself could not do, "rework": what the answers owe}`. A
    REFUSED call put the plan back: its `moves` are what WOULD happen once it records (`lines_if_recorded`), never `lines` (F-2, FR-10:
    the answer says what was recorded and what was not); `notes` are true either way."""
    import question_register as QR
    try:
        view = QR.gate_words_view(root, text, before, case_ids)
    except Exception as exc:
        view = {"unknown": f"the register could not be read ({type(exc).__name__}: {' '.join(str(exc).split())[:160]})"}
    plan_not_changed, not_applied = [], []
    try:
        if gate == "B" and "unknown" not in view:
            plan_not_changed = _unchanged_branches(root, view)
        if refused:
            read = QR.parse_choices(text, QR.load(root)["questions"], case_ids)
            not_applied = [f"{t['written']}: {t['decision']}" for t in read["case_tokens"]]
    except Exception:
        pass
    moves, notes = list(told.get("moves") or []), list(told.get("notes") or [])
    return {**view, "lines": notes if refused else moves + notes, **({"lines_if_recorded": moves} if refused and moves else {}),
            "rework": list(told.get("rework") or []), "not_applied_yet": not_applied, "plan_not_changed": plan_not_changed}


def _rework_left_text(root, rework: list) -> str:
    """The recorded `approve as is` over an owed rework (F-4): the person's word wins, the rework is NOT started; it stays named with the
    door that opens it, and runs only by the person's word (`rework`)."""
    parts, doors = _owed_rework_parts(root, rework)
    return ("you approved the plan as it is, so the rework your recorded answers owe was not started: " + "; ".join(parts)
            + ". It runs only on your word: " + " and ".join(f"`{d}`" for d in doors or ["the rework of the owner named above"]))


def _leave_rework(result: dict, root, rework: list, by: str) -> None:
    """After a RECORDED `approve as is` over an owed rework: the sentence with its door goes into the answer's `questions`
    (`rework_left`), and one `answers_applied` record (`what: rework_left`) keeps it for the report's "Left with you"
    (`report_facts._owed_rework_gap`). A record that could not be written is said in the answer's lines (FR-41)."""
    import planning_contract as PC
    import question_register as QR
    questions = result.setdefault("questions", {})
    questions["rework_left"] = _rework_left_text(root, rework)
    owed = [{k: w.get(k) for k in ("owner", "where", "question", "answer")} for w in rework if isinstance(w, dict)]
    try:
        QR._append(Path(root), {"kind": PC.ANSWERS_APPLIED, "what": "rework_left", "owed": owed, "where": "gate A", "by": by, "at": QR._now()})
    except (OSError, QR.Refused) as exc:
        questions.setdefault("lines", []).append(f"the rework left with you could not be noted for the report ({type(exc).__name__})")


def _apply_gate_a_first(a, root, by: str, text: str, manual_pass: list) -> tuple:
    """Gate A, before the decision is built: `(lines, late)` - the recorded answers, then the answers of these words, laid over the plan
    (`blocked="skip"`: the manifest is not touched). `--no-answers`: the manual-agent pass alone, no answer read, recorded or applied."""
    import planning_contract as PC
    if a.no_answers:
        return PC.apply_gate_answers(root, "", "gate A", by, pass_lines=manual_pass, blocked="skip"), {"lines": [], "rework": []}
    late = PC.apply_recorded_answers(root, "gate A", by)
    return PC.apply_gate_answers(root, text, "gate A", by, shown=a.shown, remedies=a.remedies, pass_lines=manual_pass, blocked="skip"), late


def _put_blocked(a, root, by: str, text: str, lines: list) -> bool:
    """Gate A, a call that WILL record: `accept as blocked` goes to the manifest now (`blocked="only"`); True when it ran (the caller
    rebuilds the request: the put moved the revision)."""
    import planning_contract as PC
    if a.no_answers:
        return False
    lines += PC.apply_gate_answers(root, text, "gate A", by, shown=a.shown, remedies=a.remedies, blocked="only")
    return True


def _refuse_gate_decision(a, root, text: str, by: str, before, case_ids: list, told: dict, refusal: dict) -> None:
    """The plan is as it was (the caller put the files back). A refused gate A call records the answers ALONE (F-1 B: the words stand,
    and the next call's `late` patches the plan); only then is the refusal printed, so it can list what was recorded. Exits 2."""
    import question_register as QR
    gate = str(a.gate or "").upper()
    if not a.no_answers and gate == "A":
        try:
            QR.record_answers(root, text, "gate A", by, a.shown, case_ids)
        except Exception as exc:
            told["notes"].append(f"gate A: the answers could not be recorded ({type(exc).__name__}: {' '.join(str(exc).split())[:160]})")
    refusal["questions"] = _gate_questions_view(root, text, before, case_ids, gate, told, True)
    print(json.dumps(refusal, ensure_ascii=False), file=sys.stderr)
    sys.exit(2)


def _gate_decision_call(a, c: "Controller", root, words: str) -> dict:
    """`--operation gate-decision` with the project PINNED to the story's own (F-1): the side writes of a decision (the journal line the
    delivery guard reads, the manifest put of `accept as blocked`) resolve the project from the process, and the process's env or cwd may
    sit in ANOTHER project than the story. The story's own marker (`c._project_root()`, the nearest `qa-factory/config.json` above the
    task root) wins, because the file being decided lives there; no marker found: NO pin, and the side writes keep their own doors (E7,
    E22) - a root is never invented. The pin lasts this call (`hooklib.selftest_root_restored`)."""
    project = c._project_root()
    if project is None:
        return _gate_decision_run(a, c, root, words)
    import hooklib
    with hooklib.selftest_root_restored():
        hooklib.pin_project_root(project)
        return _gate_decision_run(a, c, root, words)


def _gate_decision_run(a, c: "Controller", root, words: str) -> dict:
    """The ONE road of a gate decision, for the conductor and the driver (DC1-19). Returns the answer of a
    RECORDED decision (or the preview of `--build-only`); a refusal prints and exits 2 here. The ORDER below is the invariant (B1, B4):

      1. gate A: the recorded answers, then the answers of these words, are laid over the plan (`blocked="skip"`: the manifest is not
         touched). BEFORE the decision is built, so the decision binds the plan as patched. Gate B: the words are recorded, the plan is
         never read or written.
      2. the decision is built and checked; the person's own words stand over any problem (`approve as is` per item).
      3. a call that will record: `accept as blocked` goes to the manifest NOW (`blocked="only"`), the request is rebuilt (the put moves the
         revision), and the decision is recorded. A preview or a refusal has moved no manifest event; an exception from the rebuild or from
         the record itself, AFTER the put, can leave the manifest event over an unrecorded decision (a narrow window, not closed here).
      4. in `finally`, gate A, not recorded: the three files are put back as they were. AFTER that, a REFUSED call records the answers alone
         (F-1 B), and only then is the refusal printed - so it can list what was recorded.
    """
    gate = str(a.gate or "").upper()
    import question_register as QR
    text, by = a.answers_text or words, a.answers_by or "conductor"
    risks, risk_line = _gate_risks(a, gate, text)
    try:
        before = QR.load(root)
    except Exception:
        before = None
    try:
        import gate_brief
        case_ids = list(gate_brief.story_cases(root)[0])
    except Exception:
        case_ids = []
    manual_pass, lines, notes, late = [], [], [], {"lines": [], "rework": []}
    snapshot = _snapshot_files(root) if gate == "A" else {}
    result = refusal = None
    kept = False

    def build():
        return c.build_gate_decision(a.gate, words, (a.drafts or "").split(","), a.bugs, a.mr, risks)

    try:
        if gate == "A":
            lines, late = _apply_gate_a_first(a, root, by, text, manual_pass)
        elif not a.no_answers and not a.build_only:
            try:
                QR.record_answers(root, text, "gate B", by, a.shown, case_ids)
            except Exception as exc:
                notes.append(f"gate B: the answers could not be recorded ({type(exc).__name__}: {' '.join(str(exc).split())[:160]}); the decision goes on")
        request = build()
        problems = c.check_decision(request)
        owed = bool(late.get("rework")) and not a.as_is       # F-8 (a): `approve as is` passes over an owed rework, and says so
        if owed:
            problems = problems + [_owed_rework_text(root, late["rework"])]
        recorded_ids = ()
        with c.items_scope():       # one rehearsal for the whole decision (M5): the read, the check in `apply` and `validate` share it
            if a.as_is and not a.build_only and not problems:
                recorded_ids = c.record_as_is(a.gate, words)
            open_problems, open_items = c.open_gate_items(a.gate, factory_problems=bool(problems))
            # `item_problems_from`: where the items' sentences start in `problems` - the driver prints the factory's own before them
            refusal = {"recorded": False, "problems": problems + open_problems, "item_problems_from": len(problems),
                       **({"open_items": open_items} if open_items else {}),
                       **({"manual_pass_if_recorded": manual_pass} if manual_pass else {}), "request": request}
            if a.build_only:
                return refusal
            if not (problems or open_problems):
                if gate == "A" and _put_blocked(a, root, by, text, lines):
                    request = build()           # `manifest_put` moved the revision: the request must hold the fresh one
                told = {"moves": late["lines"] + lines, "notes": notes, "rework": late["rework"]}
                questions = _gate_questions_view(root, text, before, case_ids, gate, told, False)
                result = gate_decision_answer(c, request, recorded_ids, manual_pass, risk_line, questions)
                kept = True
    finally:
        if gate == "A" and not kept:
            _restore_files(snapshot)
    if kept:
        if late["rework"] and a.as_is:       # F-4: the person's word wins; the owed rework stays named with its door, and in the report
            _leave_rework(result, root, late["rework"], by)
        return result
    _refuse_gate_decision(a, root, text, by, before, case_ids,
                          {"moves": late["lines"] + lines, "notes": notes, "rework": late["rework"]}, refusal)


def _keys_given(request, limit=12):
    """The request's key names for a refusal: sorted, at most `limit`, the cut named (`and N more`, FR-41) -
    a refusal says what the call HAD, so the caller sees the key it spelt otherwise (SC1-7, E7). The list cut is
    `detector_verdict.named`, the one helper for ids named inside a finding (S7-8)."""
    from detector_verdict import named      # late, like the other helper reads of this file
    return named(sorted(str(key) for key in (request if isinstance(request, dict) else ())), limit) or "none"


def apply_door(operation, story_root, dispatch_id="", dispatches=None) -> str:
    """The one sentence a refusal of an APPLY operation adds: what to run instead, filled with what is KNOWN.

    Run 12586: 27 of the scout's refusals were its own hand-built controller requests (`accept` with no
    `idempotency_key`, no `--input`, a `dispatch_id` for `id`) - none named the command that writes the
    request whole. The table is inside the function (the operations are the controller's own, as
    `OPERATIONS` is). A value the call cannot know stays a `<...>` placeholder that says where it comes from
    (FR-59): `<ID>` is the dispatch named, else the ONLY running one, else the sorted candidates - the code
    never picks one of two. With no `story_root` there is no door to build ("")."""
    if story_root is None:
        return ""
    key, root = _folder_name(story_root), str(story_root)
    named = dispatch_id if isinstance(dispatch_id, str) and dispatch_id else ""
    if dispatches is None:
        shown = named or "<the dispatch id>"
    elif named and named in dispatches:
        shown = named
    else:
        # The candidates are the dispatches the operation can still finish (S7-4): a role's stop moves its dispatch
        # to RETURNED, and that one is the conductor's normal accept target; a checkpoint needs a running one.
        open_now = {"running", RETURNED} if operation == "accept" else {"running"}
        running = sorted(str(i) for i, d in dispatches.items() if isinstance(d, dict) and d.get("status") in open_now)
        shown = (running[0] if len(running) == 1 else "<one of: " + ", ".join(running) + ">" if running
                 else "<no dispatch is running>")
    doors = {
        "accept": f"Run instead `story_step.py finish --task {key} --dispatch-id {shown} --digest \"<the role's digest line>\"`: "
                  "it writes this request whole (idempotency_key, expected_revision, evidence) and records the stage. "
                  "Accepting a role's work is the conductor's move - a role that reads this returns its digest instead.",
        "checkpoint": f"Run instead `controller.py --task-root {root} --operation checkpoint --dispatch {shown} "
                      "--status blocked|paused|incomplete --reason \"<what it waits on>\" --brief` (no --input needed).",
        "dispatch": f"Run instead `story_step.py start --task {key} --stage <stage> --role <role>` (a retry: the packet "
                    f"`controller.py --task-root {root} --operation recover` prints, as it stands).",
        "decision": f"Run instead `controller.py --task-root {root} --operation gate-decision --gate A|B --words-file <file>`.",
    }
    return doors.get(operation) or (f"`--operation {operation}` reads its request from `--input <file.json>`; "
                                    "references/controller-api.md names its fields.")


def _cli_story_root(a):
    """`(root, problems)`: the story folder the command line names, and every problem with the call.

    Runs first in `main`, before the person's words are read and before a `Controller` exists, so a refusal
    leaves no byte behind: nothing here can reach `EventStore.lock`, the one `mkdir` of the store (I1-I3 of
    CX1-10). The problems are independent and are refused whole (K1); the journal check comes only when they
    are none.

    The folder must EXIST: `--task` goes through `hooklib.story_root` (the exact folder name, no guessing),
    `--task-root` through `hooklib.story_root_at` (the same rule over a path, returned as given). On a folder with no `state/events.jsonl` the controller writes nothing
    unless the operation is `prepare` (documented before `initialize`; it only reads) or `initialize` of a
    folder that holds the `pipeline.json` S0 writes before it. Any other operation on a folder that has that
    pipeline.json is refused with «initialize task before work» (the driver reads that phrase and initializes);
    on a folder that has neither, the phrase is NOT used - `initialize` would be refused there too, and the
    driver must not loop. `require_project` (`--task` outside a project) exits `hooklib.EXIT_NO_PROJECT` on its
    own, before the other problems are collected: that exit code is a contract shared with every writer."""
    problems = []
    if a.operation not in OPERATIONS:
        problems.append((ValueError, f"operation {a.operation!r} must be one of: "
                         + ", ".join(sorted(OPERATIONS))))
    root = None
    try:
        if a.task is not None:
            root = story_root(a.task, "controller.py --task", "Or pass --task-root <the story's folder>.")
        else:      # the path twin of the same rule (CX1-18): the exact name, no cwd for an empty value
            root = story_root_at(a.task_root, "controller.py --task-root", "Or pass --task <KEY>.")
    except ValueError as exc:
        problems.append((ValueError, str(exc)))
    if a.operation in INPUT_FILE_OPERATIONS and not a.input:
        # The operations that read a file (`INPUT_FILE_OPERATIONS`; `checkpoint`, `reopen_story` and `leave_unlaunched`
        # take flags and words). `Path(None)` was a traceback (R1, run 12586); the door needs the folder, so with
        # none the text says it comes after (E5).
        problems.append((ValueError, f"--operation {a.operation} takes its request from --input <file.json>, and none was given. "
                         + (apply_door(a.operation, root) or "The story's folder was not found (see above): pass --task "
                            "<KEY> or --task-root <the story's folder> first, then the command to run instead is named here.")))
    if problems or (root / "state" / "events.jsonl").is_file() or a.operation == "prepare":
        return root, problems
    if not (root / "pipeline.json").is_file():
        problems.append((ValueError, f"{root} is not a story folder: it holds neither a story journal "
                         "(state/events.jsonl) nor the pipeline.json that S0 writes, so --operation "
                         f"{a.operation} has nothing to act on, and nothing was written. Pass --task <KEY> or "
                         "--task-root <the story's folder> of a story whose S0 has closed"))
    elif a.operation != "initialize":
        problems.append((StateConflict, f"initialize task before work: {root} holds no story journal "
                         f"(state/events.jsonl), so --operation {a.operation} has nothing to act on, and "
                         "nothing was written. Run --operation initialize for this story, or pass --task "
                         "<KEY> or --task-root <the story's folder> if this is not it"))
    return root, problems


# --- `--brief`: a short answer for the conductor, the whole result in a file (speed-cost SC1-8 A1, release 0.10.3) ---
# TP1-12586: 33 controller calls printed 157 311 characters into the conductor's context, `--operation rework` alone 109 675
# (largest 14 117) - the request and the receipt of a dispatch the conductor never reads field by field. Without the flag the answer
# is byte for byte what it always was (the driver parses it, FR-14); with it, an answer over BRIEF_MAX_BYTES is a summary that keeps
# the keys the conductor ACTS on whole, and the whole result is in `state/output/controller-<operation>.json`.
# ONLY the two operations where the weight is (`rework` 110 thousand of the 157 thousand, `checkpoint`) are briefed: everything the
# conductor acts on in their answers sits in the ALWAYS_WHOLE keys. The other operations print whole, flag or not - their answers
# carry keys a summary would hide (`prepare`: missing_facts / resolved_paths; `next`: dispatch_request / options / digest;
# `gate-decision`: the receipt `decision`, read whole by s4.md and s8.md).
BRIEF_MAX_BYTES = 1500
BRIEF_OPERATIONS = ("rework", "checkpoint")
ALWAYS_WHOLE =("error", "problems", "recorded", "dispatched", "next_action", "next", "window", "action", "stage", "dispatch_id")
BRIEF_SCALAR_MAX = 200      # another scalar is shown by value up to this many characters, else as `<n> chars`
BRIEF_KEYS_SHOWN = 8        # an object is shown by its first keys


def _brief_result(result) -> list:
    """The summary lines of a result: the ALWAYS_WHOLE keys as whole JSON, another scalar by value (up to BRIEF_SCALAR_MAX
    characters), a list as `[N items]`, an object as its first keys. Nothing is cut: what a line does not carry is in the file."""
    if isinstance(result, list):
        return [f"result: [{len(result)} items]"]
    if not isinstance(result, dict):
        return [f"result: {json.dumps(result, ensure_ascii=False)}"]
    lines = []
    for key, value in result.items():
        if key in ALWAYS_WHOLE:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        elif isinstance(value, dict):
            names = list(value)[:BRIEF_KEYS_SHOWN]
            lines.append(f"{key}: {{{', '.join(map(str, names))}{', ...' if len(value) > len(names) else ''} ({len(value)} keys)}}")
        elif isinstance(value, list):
            lines.append(f"{key}: [{len(value)} items]")
        elif isinstance(value, str) and len(value) > BRIEF_SCALAR_MAX:
            lines.append(f"{key}: {len(value)} chars")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    return lines


def _output_rel(target: Path) -> str:
    """The path as the project spells it (`qa-factory/artifacts/<T>/state/output/...`), else the absolute path: the one printed is
    always one that exists (FR-37), also for a story folder given outside the project."""
    try:
        from hooklib import project_root
        return target.resolve().relative_to(project_root().resolve()).as_posix()
    except (ValueError, OSError):
        return str(target)


def _print_result(result, a, root) -> None:
    """Print the answer. No `--brief`: the whole result in one line, as before. `--brief` on an operation outside BRIEF_OPERATIONS:
    the same line. `--brief` on `rework` / `checkpoint`: the same line when it is at most BRIEF_MAX_BYTES bytes; else the summary
    plus a last line naming the file that holds the whole result. A file that cannot be written leaves nothing hidden: the whole
    line is printed and the reason goes to stderr."""
    whole = json.dumps(result, ensure_ascii=False)
    if (not getattr(a, "brief", False) or a.operation not in BRIEF_OPERATIONS
            or len(whole.encode("utf-8", "replace")) <= BRIEF_MAX_BYTES):
        print(whole)
        return
    target = Path(root) / "state" / "output" / f"controller-{a.operation}.json"
    try:
        atomic_json(target, result)   # the package's one atomic JSON writer (unique temp name, the Windows reader-handle retry)
    except (OSError, ValueError) as exc:   # ValueError: a lone surrogate or a value JSON cannot hold
        print(whole)
        print(f"controller: --brief could not save the full result ({type(exc).__name__}: {exc}); printed whole", file=sys.stderr)
        return
    print("\n".join(_brief_result(result) + [f"full result: {_output_rel(target)} ({target.stat().st_size} bytes)"]))


def main():
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(prog="controller.py", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--task", help="the story's ticket key: the folder of that name under the artifact "
                                      "root, matched exactly; the folder must exist")
    which.add_argument("--task-root", help="the story's folder itself; it must exist")
    ap.add_argument("--operation", required=True)
    ap.add_argument("--input")
    ap.add_argument("--window", help="accept: the S5 window acceptance record, as written by "
                                     "`window_record.py` — no role types this JSON")
    ap.add_argument("--gate", help="gate-decision / gate-preflight: A or B")
    ap.add_argument("--words", help="gate-decision / release / reopen_story / leave_unlaunched: the person's own words, verbatim - "
                                    "one line typed by code; their words as they were given go "
                                    "in a file (--words-file)")
    ap.add_argument("--words-file", help="gate-decision / release: a file holding the person's own "
                                         "words as they were given (UTF-8; "
                                         "<story folder>/state/words/<name>.txt); instead of --words; "
                                         "rework: the same file, instead of --reason - the person's "
                                         "words; the rework then also sets aside what runs after it "
                                         "(`rerun_after`), which --reason (a finding typed by code) "
                                         "never does")
    ap.add_argument("--stage", help="rework: the accepted stage to go back over, e.g. S4")
    ap.add_argument("--role", help="rework: the role that did that work, e.g. qa-case-designer")
    ap.add_argument("--cases", help="rework: comma-separated case ids from the approved scope "
                                    "(optional on S1-S3, whose roles have no cases)")
    ap.add_argument("--rows", help="rework: comma-separated plan row ids to go back over")
    ap.add_argument("--reason", help="rework: what this round repairs; checkpoint: what the "
                                     "dispatch is waiting on")
    ap.add_argument("--dispatch", help="release / checkpoint / resume: the dispatch to act on "
                                       "(checkpoint may omit it when exactly one is running); reopen_story / "
                                       "leave_unlaunched: the held dispatches the person's word covers, comma-separated")
    ap.add_argument("--agent-id", dest="agent_id",
                    help="resume: the host's id of the agent that continues; default: the one recorded on the dispatch")
    ap.add_argument("--status", help="checkpoint: blocked, paused or incomplete")
    ap.add_argument("--remaining", help="checkpoint: the remaining work, ';'-separated "
                                        "(default: the reason)")
    ap.add_argument("--bugs", help="gate-decision --gate B: ordered | not_ordered - whether the bug reporter files bugs (drafts "
                                   "chosen with --drafts always order it)")
    ap.add_argument("--mr", help="gate-decision --gate B: open | do_not_open | not_offered - what the person decided about the MR "
                                 "(omitted: the delivery step opens it)")
    ap.add_argument("--risks-file", dest="risks_file", help="gate-decision --gate B: a file holding the person's reason to deliver with "
                                                            "known gaps, whole (UTF-8; <story folder>/state/words/<name>.txt); it records the "
                                                            "decision and writes the journal line the delivery guard reads. A line "
                                                            "`deliver with known gaps: <reason>` of their words does the same (the flag wins)")
    ap.add_argument("--answers-file", dest="answers_file", help="gate-decision: a file holding the lines the register records and the plan follows "
                                                                "(`Q1: a`, `<case id>: accept as blocked`), when they are not the person's words whole "
                                                                "(the driver passes the NEW answer's lines without the earlier answer it keeps); "
                                                                "default: the words")
    ap.add_argument("--shown-file", dest="shown_file", help="gate-decision: a JSON file {question id: the row hash the person's card showed}; an "
                                                            "answer is recorded against it (default: the row as it stands)")
    ap.add_argument("--remedies-file", dest="remedies_file", help="gate-decision --gate A: a JSON file {case id: remedy} for the cases a level "
                                                                  "accept names; each is blocked by that remedy")
    ap.add_argument("--answers-by", dest="answers_by", default="conductor",
                    help="gate-decision: who recorded the answers (a value of `by` in references/question-vocabulary.json; default conductor)")
    ap.add_argument("--no-answers", dest="no_answers", action="store_true",
                    help="gate-decision: record and apply no answer (a dry run); the manual-agent pass of gate A still runs")
    ap.add_argument("--order", help="settle_order: the order of gate B to settle, bugs | mr")
    ap.add_argument("--outcome", help="settle_order: done | cancelled")
    ap.add_argument("--source-head", dest="source_head", help="first_look_continue: the code heads the first look saw (the text "
                                                              "`first_look.py show --json` gives as `current_keys`); stored as given")
    ap.add_argument("--register-hash", dest="register_hash", help="first_look_continue: the 64-hex hash of the register the first look "
                                                                  "counted (`current_keys`); stored as given")
    ap.add_argument("--ref", help="settle_order: the MR link or id (done), or the delivery step's one-line record "
                                  "(cancelled with --reason-code); at most 2000 characters")
    ap.add_argument("--reason-code", dest="reason_code", help="settle_order --outcome cancelled without a person's words: "
                                                              + " | ".join(SETTLE_REASON_CODES))
    ap.add_argument("--drafts", help="gate-decision --gate B: the bug drafts the person chose, "
                                     "comma-separated refs; omit for none")
    ap.add_argument("--purpose", default="repair_verify",
                    help="rework: one of " + ", ".join(sorted(PURPOSES)))
    ap.add_argument("--cause", choices=REPAIR_CAUSES,
                    help="rework: why this round exists (default test_defect, the only cause "
                         "that spends the repair cap)")
    ap.add_argument("--parallel-window", dest="parallel_window", action="store_true",
                    help="rework (the driver's scheduler only, t-1937): this S5 round may start beside a running window of other "
                         "cases; the controller still checks stage, role, disjoint scopes and the cap")
    ap.add_argument("--build-only", action="store_true",
                    help="gate-decision / rework / checkpoint: print the request without "
                         "recording it")
    ap.add_argument("--as-is", dest="as_is", action="store_true",
                    help="gate-decision --gate A only: the person answered the closed word `approve as is` (the caller's declaration, "
                         "read by the driver's one normaliser): one waiver per open item with their words, then the decision")
    ap.add_argument("--brief", action="store_true",
                    help="%s only: print a short answer when the result is over %d bytes - the keys you act on whole (%s), the "
                         "rest as counts, and the whole result in <story folder>/state/output/controller-<operation>.json. Any "
                         "other operation prints the whole result exactly as without this flag, and so does a result within "
                         "the limit" % (" and ".join(BRIEF_OPERATIONS), BRIEF_MAX_BYTES, ", ".join(ALWAYS_WHOLE)))
    a = ap.parse_args()
    # The story folder and the operation are settled FIRST (K1, one refusal for all of it): a wrong root must not
    # cost the person's words a read, nor any byte on disk (CX1-10).
    root, problems = _cli_story_root(a)
    Controller._raise_all(problems)
    # The person's words are resolved ONCE, here, before any state is read or written: a refusal
    # (both options, a bad file, inline words through the cmd launcher) leaves no event behind.
    # Only the two operations that record words take them; for the rest `--words` was and stays
    # unread. The same reader serves waiver, archive_task and project_decisions (FR-17, M30).
    words = a.words
    if a.operation in ("gate-decision", "release", "reopen_story", "leave_unlaunched", "settle_order",
                       "stop_waiting", "first_look_continue"):
        import person_words
        words = person_words.read(a.words, a.words_file, "--words")
    a.risks_text = None
    a.answers_text, a.shown, a.remedies, a.risks_text = None, {}, {}, None
    if a.operation == "gate-decision":
        a.answers_text, a.shown, a.remedies, bad_flags = _gate_inputs_of(a)          # DC1-19, E21: before any state is read or written
        if bad_flags:
            raise ValueError("; ".join(bad_flags))
        if a.as_is and str(a.gate or "").upper() != "A":
            raise ValueError("--as-is is gate A only: `approve as is` passes the open items of gate A; gate B's questions have "
                             "their own executors - leave --as-is out")
    # `rework` takes the person's words from a file ONLY when `--words-file` is given: the same reader, so a
    # multi-line reason is stored whole and both options at once are refused (exit 2) before any event. Inline
    # `--reason` stays as it was: the factory's own finding text goes there, not a person's words (C1-2, FR-8).
    reason = a.reason
    if a.operation == "rework" and a.words_file is not None:
        import person_words
        reason = person_words.read(a.reason, a.words_file, "--reason")
    # The wait is chosen HERE, at the command's entry, and handed to the controller: a hook that
    # builds a Controller and calls the same methods (SubagentStop's record_return) never
    # inherits it. Read from the module at call time so a test can shorten it.
    c = Controller(root, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS)
    if a.operation == "prepare":
        result = c.prepare(json.loads(Path(a.input).read_text(encoding="utf-8-sig")) if a.input else None)
    elif a.operation == "next":
        result = c.next_action()
    elif a.operation == "checkpoint-packet":
        result = c.checkpoint_packet(json.loads(Path(a.input).read_text(encoding="utf-8-sig")) if a.input else None)
    elif a.operation == "baseline-inputs":
        result = c.baseline_inputs(json.loads(Path(a.input).read_text(encoding="utf-8-sig")))
    elif a.operation == "deployment-inputs":
        result = c.deployment_inputs()
    elif a.operation == "gate-inputs":
        result = c.gate_inputs()
    elif a.operation == "stage-scope":
        options = json.loads(Path(a.input).read_text(encoding="utf-8-sig")) if a.input else {}
        # The pure reader, not `next_action()`: `stage-scope` is documented read-only.
        result = c.stage_scope(options.get("stage")
                               or c._next_action_for_state(c.state(), c._pipeline()).get("stage"),
                               None, options.get("execution_kind"))
    elif a.operation == "recover":
        result = c.recover()
    elif a.operation == "gate-decision":
        result = _gate_decision_call(a, c, root, words)
    elif a.operation == "release":
        result = c.release_dispatch(a.dispatch, words)
    elif a.operation == "reopen_story":
        result = c.reopen_story(a.dispatch, words)
    elif a.operation == "leave_unlaunched":
        result = c.leave_unlaunched(a.dispatch, words)
    elif a.operation == "settle_order":
        result = c.settle_order(a.order, a.outcome, a.ref, words, a.reason_code)
    elif a.operation == "stop_waiting":
        result = c.stop_waiting(words)
    elif a.operation == "first_look_continue":
        result = c.first_look_continue(words, a.source_head, a.register_hash)
    elif a.operation == "checkpoint" and not a.input:
        # Flags, not a hand-written JSON file: s0.md forbids hand-building service JSON on the
        # normal path, and `--input` stays for the full shape a role's own counters need.
        request = c.build_checkpoint_request(a.dispatch, a.status, a.reason, a.remaining)
        result = ({"recorded": False, "request": request} if a.build_only
                  else {"recorded": True, "request": request,
                        "receipt": c.apply("checkpoint", dict(request)),
                        "next_action": c.next_action()})
    elif a.operation == "resume":
        # FB-4: built from the journal, never from a file - a request carried in a file could be a stale one.
        if a.input:
            raise ValueError("--operation resume is built from flags, never from a file: run `story_step.py resume --task "
                             f"{c._ticket()} --dispatch-id <id>` (or `controller.py --task-root {root} --operation resume "
                             "--dispatch <id> [--agent-id <id>]`)")
        request = c.build_resume_request(a.dispatch, a.agent_id)
        result = ({"recorded": False, "request": request} if a.build_only
                  else {"recorded": True, "request": request,
                        "receipt": c.apply("resume", dict(request)),
                        "next_action": c.next_action()})
    elif a.operation == "rework":
        request = c.build_rework_request(a.stage, a.role, (a.cases or "").split(","),
                                         reason, a.purpose, (a.rows or "").split(","),
                                         a.cause, words_given=a.words_file is not None,
                                         parallel_window=bool(a.parallel_window))
        import launch_card   # late, like the other card-layer reads of this file
        result = ({"dispatched": False, "request": request} if a.build_only
                  else {"dispatched": True, "request": request,
                        "receipt": c.apply("dispatch", dict(request)),
                        # TP2-2406 S3-3, 15.10.2026: the packet is committed and has no brief, handover form
                        # or launch card, and `story_step start` cannot write them for it (it builds a fresh
                        # request): `materialize` writes them from this one. The store root is the task folder.
                        "next": launch_card.materialize_door(c._ticket(), request["id"])})
    elif a.operation == "gate-preflight":
        try:
            from gate_preflight import run
        except ImportError as exc:
            raise ValueError("gate_preflight.py is not installed beside controller.py; "
                             f"reinstall the plugin ({exc})") from exc
        result = run(root, str(a.gate or "A").upper())
    else:  # an APPLY operation: `_cli_story_root` has refused every name that is in neither list
        payload = json.loads(Path(a.input).read_text(encoding="utf-8"))
        if a.window:
            # The window is a FILE `window_record.py` wrote, not JSON somebody pasted into the
            # completion (TP2-2553). A completion that still carries `window` inline
            # keeps working; the file wins when both are given.
            payload["window"] = json.loads(Path(a.window).read_text(encoding="utf-8-sig"))
        result = c.apply(a.operation, payload)
    _print_result(result, a, root)


if __name__ == "__main__":
    try:
        main()
    except KeyError as exc:
        # A bare KeyError reached the CLI as `{"error": "'supported'"}` and told a reader
        # nothing about which request was missing which field.
        print(json.dumps({"error": f"the request is missing a required field: {exc}"}), file=sys.stderr)
        sys.exit(2)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(2)
