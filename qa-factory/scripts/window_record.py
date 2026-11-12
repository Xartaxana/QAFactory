"""Build the S5 window acceptance record from what is already on disk — nothing typed.

TP2-2553: `acceptance.validate_window` and the controller's S5 completion path
demanded `scope_instances`, per-instance `input_hash`, `execution_fingerprint`,
`obligation_refs/ids/hash`, `assertion_id`, `defect_location`, `change_disposition`,
`change_basis_ref`, `evidence_refs`, `review` and `probe`, plus the project's quality checks
and receipts — and NO script wrote any of it. The orchestrator discovered the shape by
repeated rejection, one field per refusal; two waivers were spent and the critic's last
interval ran close to two hours.

Every one of those facts already exists in an artifact somebody wrote:

  the dispatch (state/events.jsonl)   scope, input_hash, author and reviewer dispatch ids
  work/automation-manifest.json       the instance rows: trace_binding.test_content_sha,
                                      obligation_refs, assertion_id, defect_location,
                                      change_disposition, change_basis_ref, critic_verdict
  work/run-blocks/*.json              the outcome, the execution fingerprint and the run
                                      evidence of each instance (written by run_suite.py)
  work/sensitivity-receipts/*.json    the probe (live, or catches a broken product), reached
                                      through the row's sensitivity_proof.receipt_ref, else the
                                      manifest's obligation_bindings[].probe_receipt_ref
  state/controller.json               the project's required_quality_checks
  s5_precheck.expectation_changes     the tests that changed between a red run and the next green run
                                      (read-only), joined to the manifest's expectation_changes[]
                                      records and the critic's verdicts on them

So this script reads them and writes the record. The verdict it prints lists EVERY structural
error (`contract.window_shape_errors`) and EVERY semantic gap (`acceptance.validate_window`)
at once, each with the artifact the value was missing from and the command that produces it —
the opposite of learning the shape one refusal at a time.

  window_record.py --task QA-1 --dispatch S5-qa-code-critic-1
  window_record.py --task QA-1 --dispatch S5-qa-code-critic-1 --review-receipt
  window_record.py --task QA-1 --dispatch S5-qa-code-critic-1 --out /tmp/window.json

Exit 0 when the window is acceptable, 1 when it is not. A window whose ONLY gaps are instances the
stand blocked (their unresolved[] row says `blocked_by_env` and carries a remedy; the critic's verdict
on each is `unverified`) is "acceptable as unresolved": exit 0, and `story_step.py finish` derives the
`unresolved` pair from the record; so is an instance that ran green whose probe could not run here, when a recorded
word of the person names it (`waiver.py --stage S5 --block "probe gap: <case key>"`, the critic's
`unverified`). A review row `rejected` (blocked instance or not) is the critic sending the test back: when every
non-derivable gap belongs to such an instance, `--review-receipt` still writes and publishes the receipt (finish needs
it) and the exit stays 1 - the window goes back to its author, it is never "acceptable". A person never sees a
traceback from here: a gap is a finding with an owner, not a crash.

HF2-4 (TP1-12586): a RED instance that the manifest's `unresolved[]` row `contradicts_requirement` explains
(`acceptance.red_by_requirement`, the one reader) closes the window with that row: its gap is
`contradicts_requirement:<iid>`, the item carries a `probe_not_applicable` block instead of a `probe` (a probe on a red
test depends on the order of its asserts, F-20), and a window whose gaps are all derivable is "acceptable as
unresolved" like a stand-blocked one: exit 0, the review receipt written, and S7 triages the red. A red instance with
no matching row stays a `product:` gap, said with the one road that closes it.

B-375: an instance the manifest hands to the person (`acceptance.handed_instances`, the one reader, asked here and by
`validate_window`) is acceptable as unresolved the same way, and owes no run evidence; a record that merely claims it is
`handed_unconfirmed:<iid>` (not derivable). B-380: a probe built from a sensitivity receipt carries `reason_detail`
(`reporters.reason_detail`), read back as a `note:` when its reason matched on the failure's first line only.
"""
import argparse
import collections
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import person_words  # noqa: E402
import proof_level  # noqa: E402
import reporters  # noqa: E402
from acceptance import (BLOCKED_OUTCOME, BLOCKED_REVIEW_VERDICT, CONTRADICTS_REQUIREMENT, HANDED_OUTCOME,  # noqa: E402
                        HANDED_UNCONFIRMED_KIND, PROBE_GAP_KIND, PROBE_GAP_UNRECORDED_KIND, blocked_instances,
                        change_word, expectation_change_gaps, green_on_current_bytes_why, handed_instances, ran_red,
                        pending_instances, PENDING_OUTCOME, probe_gap_named, red_by_requirement, run_freshness_of, validate_window)
from event_store import atomic_json, content_hash  # noqa: E402
from hooklib import artifacts_dir, require_project  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402

EXIT_REFUSED = 1
EXIT_BAD_ARGS = 2

WINDOW_DIR = "work/windows"
REVIEW_RECEIPT_DIR = "work/review-receipts"
RUN_BLOCK_DIR = "work/run-blocks"

# The probe's door: the critic's own command (what a receipt needs). HF1-14 adds the second door for a probe that
# cannot run here: the person's word for THAT instance, recorded by the orchestrator (a role records no word, so the
# critic returns the item). The second door is appended to the NOTE `build` writes for a missing probe (below), not to
# `ORIGIN["probe"]`: `test_red_sandbox_reports` holds every `--flag` of that door to the flags `probe_by_code.py`
# takes, and `--words-file` is `waiver.py`'s. `GAP_ORIGIN` rows of a probe that RAN and missed keep the first door
# alone: the word passes nothing for them.
PROBE_DOOR = ("run `probe_by_code.py --task <T> --dispatch <critic id> --test \"<node>\" "
              "--instance <IID>` (the check is live: every new or changed test)")
# The word names the CASE KEY of the test (B-16): `contract.prefix_value` reads one token only, and an instance id is a phrase
# with spaces, so a word typed with it is refused by `waiver.block_name_row`. ONE door text (AR-13); the controller imports it.
PROBE_GAP_RECORD = person_words.door(f"waiver.py --task <T> --stage S5 --block \"{C.PROBE_GAP_MATCH_PREFIX} <case key>\"")
PROBE_GAP_DOOR = ("; or, when the person accepts that this test is not probed here, the orchestrator records `"
                  + PROBE_GAP_RECORD + "` for a case key of this instance (an instance id that is one token works too; "
                  "a phrase with spaces is never a word the window reads) (return this item: a role records no word)")
# t-1968 N2: the tail of the `probe is missing` line of an owed green item whose probe record is `incomplete`, `cause: judgment`
# and has no judgment yet; `probe_by_code.JUDGE_DOOR` (the critic's own command) follows it. Not a person's word (AR-24).
UNJUDGED_NOTE = "its probe failed at the mutated line with a text the factory cannot read; the code critic judges it: "
# fix round D (B2): the tail of the `probe is missing` line of an owed green item whose walk has NO check owing a judgment; `PROBE_DOOR` follows.
PLAIN_CALL_NOTE = ("its probe walk is not finished and no check of it owes the code critic's `--judge` (some checks were not selected, or have "
                   "no model entry yet); the plain call walks the rest: ")
# t-1968 N5: the note of an owed green item whose probe the code critic could not judge (`cannot_judge`): the person's OWN word, a
# separate prefix, never a `probe gap:` word (the owner's word 05.11.2026). ONE door text (AR-13).
NOT_PROVED_RECORD = person_words.door(f"waiver.py --task <T> --stage S5 --block \"{C.PROBE_NOT_PROVED_PREFIX} <case key>\"")
NOT_PROVED_NOTE = ("the code critic could not tell whether its probe failed because of the broken check; the person decides: `"
                   + NOT_PROVED_RECORD + "` (return this item: a role records no word)")
PRINTED_LINES, PRINTED_LINE_LIMIT = 3, 160    # how much of the failure text `probe_judgment_cases` carries for the person to read
# The door of a RED instance no manifest row explains (HF2-4, FR-2): the automator's own road - `manifest_put.py
# --fragment` is the command the role may run - and not the critic's probe (a probe on a red test closes nothing) and not
# a person's word (the word of a person never turns a red into a passed window, FR-18). The marker `qa_unresolved` is not
# named as the door: the fragment is the one road a row written by hand has (the marker writes the same row from the
# test file, `instance_ids=` and `thens=`, HF2-12).
RED_ROW_DOOR = ("a red test closes its window with its manifest row: the automator sends the `unresolved[]` row "
                "{case, reason: contradicts_requirement, instance_ids: [<this instance>], thens: [<the red Then>], "
                "detail} through `manifest_put.py --task <T> --fragment <file>`; S7 judges the red")

# Where each field of an instance record comes from, and the one command that produces it.
# Printed beside the gap so a reader repairs the ARTIFACT, never the record.
ORIGIN = {
    "input_hash": ("the test file the manifest row names (`file`) cannot be found under the project, "
                   "so its current bytes cannot be read",
                   "the automator records the test's project-relative file and its bytes through "
                   "`manifest_from_tests.py`"),
    "outcome": ("no run block under work/run-blocks/ holds a terminal result for this instance",
                "run it with `run_suite.py --mine <case>`"),
    "execution_fingerprint": ("no run block under work/run-blocks/ names this instance",
                              "run it with `run_suite.py --mine <case>`"),
    "evidence_refs": ("no run block and no receipt on disk names this instance",
                      "run it with `run_suite.py --mine <case>`"),
    "obligation_refs": ("the manifest row carries no `obligation_refs`",
                        "the automator writes the plan's obligation ids and hashes there"),
    "obligation_ids": ("the manifest row carries no `obligation_refs`",
                       "the automator writes the plan's obligation ids and hashes there"),
    "obligation_hash": ("the manifest row carries no `obligation_refs` to hash",
                        "the automator writes the plan's obligation ids and hashes there"),
    "assertion_id": ("the manifest row carries no `assertion_id`",
                     "the automator names the assertion that fails when the behaviour breaks"),
    "defect_location": ("the manifest row carries no `defect_location`",
                        "the automator names the product location the obligation damages"),
    "change_disposition": ("the manifest row carries no `change_disposition`",
                           "`new_or_changed` or `unchanged`, written by the automator"),
    "change_basis_ref": ("the manifest row carries no `change_basis_ref`",
                         "the automator names what the disposition is read from"),
    "review": ("the manifest row carries no `critic_verdict`",
               "the critic records its verdict through `manifest_put.py`"),
    "probe": ("no sensitivity receipt reaches this instance through the row's "
              "`sensitivity_proof.receipt_ref` or the manifest's "
              "`obligation_bindings[].probe_receipt_ref`",
              PROBE_DOOR),
}


# What each `tests[]` row of the automation manifest must carry before the S5 window or the test run will take it
# (HF2-12, EP1-18 (a)): the ONE list of the row fields, so that the role learns them before its work and not from a
# refusal (FR-38), and the window, the S5 pre-check and the printed form read the same names (AR-13, FR-13).
#   what        one line for the role: what the field holds
#   when        `always` - every row; `plan_obligation` - a row of a case whose plan row carries an automated
#               (non-`manual-*`) obligation; `shared_root` - a row whose file lies under a test root that several
#               profiles share (execution_request.profiles_owning)
#   values      the closed set the field takes, or () for free text
#   filled_by   `automator` - the role writes it into a fragment; `marker` - `manifest_from_tests.py` writes it from
#               the test file's marker, a fragment would only be overwritten by the next marker run
#   origin_door the one command that produces it (FR-11: a command the role has)
#   window      whether `build` copies it into the window's instance record
RowField = collections.namedtuple("RowField", "what when values filled_by origin_door window")
FRAGMENT_DOOR = "manifest_put.py --task <T> --fragment <file>"
MARKER_DOOR = "the marker `qa(obligations=[...])` on the test, then `manifest_from_tests.py`"
REQUIRED_ROW_FIELDS = dict(zip(
    ("assertion_id", "defect_location", "change_disposition", "change_basis_ref", "obligation_refs", "profile_id"),
    (RowField("the assertion that fails when the behaviour breaks (a file:line or an id)",
              "always", (), "automator", FRAGMENT_DOOR, True),
     RowField("the product location the obligation damages (a file:line)",
              "always", (), "automator", FRAGMENT_DOOR, True),
     RowField("`new_or_changed` or `unchanged`",
              "always", ("new_or_changed", "unchanged"), "automator", FRAGMENT_DOOR, True),
     RowField("what the disposition is read from (for example `manifest:<case>`)",
              "always", (), "automator", FRAGMENT_DOOR, True),
     RowField("the plan's obligation ids and hashes the test proves",
              "plan_obligation", (), "marker", MARKER_DOOR, True),
     RowField("the execution profile that runs the test; the file lies under a test root several profiles share",
              "shared_root", (), "automator", FRAGMENT_DOOR, False))))


def window_text_fields() -> tuple:
    """The names the window copies from a row as TEXT - the automator's own words - in the carrier's order. Read from
    the carrier at the call, never at import. `obligation_refs` is copied as a list beside two fields derived from it,
    so `build` handles it by itself."""
    return tuple(name for name, spec in REQUIRED_ROW_FIELDS.items() if spec.window and spec.filled_by == "automator")


def _is_blank(value) -> bool:
    """A field is missing when its key is absent, `None` or `""` - and nothing else: the window copies `str(x or "")`
    and deletes an empty result, so a string of spaces is a VALUE to it and to the acceptance (FR-59: what the window
    reads as present is never called missing here, what it reads as missing is never called present)."""
    return value is None or value == ""


def _typo_hint(entry: dict, field: str) -> str:
    """` (the row carries `assertionId`; the field is spelled `assertion_id`)` for a key that is the field name in
    other letters (case, `_`, `-`), else ''. `profile` is the alias `entry_profile_id` reads, not a typo."""
    def flat(text) -> str:
        return str(text).casefold().replace("_", "").replace("-", "")
    for key in entry:
        if isinstance(key, str) and key != field and flat(key) == flat(field):
            return f" (the row carries `{key}`; the field is spelled `{field}`)"
    return ""


def _text_problem(value, spec) -> str:
    """'' or the problem of a field the automator writes as text: `missing`, or outside the closed set `values`."""
    if _is_blank(value):
        return "missing"
    if spec.values and str(value) not in spec.values:
        return "not one of " + ", ".join(spec.values)
    return ""


def _obligation_refs_problem(entry: dict, plan) -> str:
    """'' or the problem of `obligation_refs`, read as `acceptance.validate_window` reads the item (schema 2): among the
    dict objects every one carries a non-empty `obligation_id`, no id twice; non-dict items are skipped as `build` skips
    them. Demanded only when `plan` (the obligations of THIS row's case, as `contract.plan_obligations` lists them)
    holds an automated one: a `manual-*` obligation is discharged by the runner's evidence, and no plan, or a legacy
    plan that asks for none, demands nothing - the error direction is "not demanded" (the marker refuses an id the plan
    does not name, so a finding the role cannot fill would be a trap, FR-57)."""
    owed = [ob for ob in plan or [] if isinstance(ob, dict) and ob.get("obligation_id")
            and not str(ob.get("decision") or "").startswith("manual-")]
    if not owed:
        return ""
    refs = entry.get("obligation_refs")
    ids = [str(ref.get("obligation_id") or "") for ref in refs if isinstance(ref, dict)] \
        if isinstance(refs, (list, tuple)) else []
    if not any(ids):
        return "missing"
    if not all(ids) or len(ids) != len(set(ids)):
        return "an `obligation_refs` object has an empty or a repeated `obligation_id`"
    return ""


def _profile_problem(entry: dict, cfg) -> str:
    """'' or the problem of `profile_id`, by the same predicates the run uses (`execution_request`: `entry_profile_id`,
    `profiles_owning`, `known_profile`, `unknown_profile_refusal`). Demanded only where the run would refuse the row
    without it: its file lies under the test root of two or more selected profiles. A config that cannot be read, holds
    no profiles, or a file outside every root demands nothing (the run's own refusal stays), and an exception inside
    these readers is not a demand either."""
    if not isinstance(cfg, dict) or not cfg.get("profiles"):
        return ""
    try:
        import execution_request as ER
        named = ER.entry_profile_id(entry)
        if named:
            return "" if ER.known_profile(cfg, named) else ER.unknown_profile_refusal(cfg, named, ER.NAMED_BY_ROW)
        file = entry.get("file")
        owners = ER.profiles_owning(cfg, file) if file else []
        if len(owners) > 1:
            return (f"its file {file} lies under the test root that profiles {', '.join(owners)} share"
                    + _typo_hint(entry, "profile_id"))
    except Exception:
        return ""
    return ""


def row_field_gaps(entry, cfg=None, plan=None) -> list:
    """`[(field, problem), ...]` in the carrier's order: what a `tests[]` row still lacks of `REQUIRED_ROW_FIELDS`.
    Pure and total - a row that is no dict answers `[]`. `problem` is `missing` (key absent, `None` or `""`; for
    `obligation_refs` also a list with no object carrying an `obligation_id`), `not one of a, b` for a value outside the
    closed set, or the text of the one reader that refused (`unknown_profile_refusal`). A key that is the field name
    in other letters adds ` (the row carries `x`; the field is spelled `y`)` to `missing`.
    `cfg` is the project's config.json and `plan` the plan obligations of the row's case: without them the fields that
    depend on them are NOT demanded (the safe side: the gates behind this check stay on their own path)."""
    if not isinstance(entry, dict):
        return []
    gaps = []
    for field, spec in REQUIRED_ROW_FIELDS.items():
        if spec.when == "plan_obligation":
            problem = _obligation_refs_problem(entry, plan)
        elif spec.when == "shared_root":
            problem = _profile_problem(entry, cfg)
        else:
            problem = _text_problem(entry.get(field), spec)
        if problem == "missing":
            problem += _typo_hint(entry, field)
        if problem:
            gaps.append((field, problem))
    return gaps


# The same table for `validate_window` gaps, whose vocabulary is its own.
GAP_ORIGIN = {
    # HF2-4: a red test a manifest row explains is `contradicts_requirement` below; this gap is the red that NO row
    # explains (or whose row names another instance, partition or Then), so the door is the row, not "S7 will see it".
    "product": ("the latest run block for this instance is not `passed`, and no `contradicts_requirement` row of the "
                "manifest names this instance", RED_ROW_DOOR),
    CONTRADICTS_REQUIREMENT: ("the latest run block for this instance is `failed` and a `contradicts_requirement` row "
                              "of the manifest names it: the test went red against the requirement",
                              "accepted as unresolved: `story_step.py finish` derives the pair; S7 triages the red"),
    # The door of a review gap is the critic's `manifest_put.py` record - and for an instance the STAND blocked
    # the word is `unverified` (a static review), which `build` says per instance in its own note. NO recorded
    # word of a person passes this gap (the controller reads none for a window gap of this kind), so the door
    # is never `waiver.py` (Q7 B', FR-57: that door is queued as debt, design/factory-rules-debt.md).
    "review": ("the manifest row's `critic_verdict` is not `approved`",
               ORIGIN["review"][1] + " (`unverified` for an instance the stand blocked; `approved` or `unverified` for "
               "an instance the person runs)"),
    "stale_review": ("the review is bound to bytes the manifest no longer carries",
                     "re-review the current bytes, or record the mechanical round"),
    "mechanical_green": ("the record claims a mechanical round and no green run of its author "
                         "on these bytes exists",
                         "the author runs the fixed test with `run_suite.py --mine <case>`"),
    # HF2-11: the instance's latest run ran other code than the test holds now (the run row's per-test shas, `run_identity`,
    # against `instance_identity`, `proof_level.run_freshness`). `{why}` is filled by `verdict` from the same predicate.
    # What this gap is NOT (the honest invariant): code does not derive an `unresolved` pair for it (`derivable` below and
    # `story_step._derived_pair` refuse the kind), and no recorded word of a person is read for it (the kind is not in
    # `WORD_READ_KINDS`). A pair typed by hand carries it like any other gap (`controller.py` accept); the road is the run.
    "stale_run": ("the latest run of this instance ran other code than it holds now: {why}",
                  "run it again with `run_suite.py --mine <case>`"),
    "sensitivity": ("the sensitivity receipt does not show the intended assertion failure",
                    PROBE_DOOR),
    "semantic_sensitivity": ("the probe's obligations, assertion or defect location do not "
                             "match the instance's",
                             PROBE_DOOR),
    "probe_mutation_kind": ("a probe that claims to catch a broken product did not mutate the product",
                            "an assertion mutation proves the check is live — that is "
                            "probe_by_code.py's receipt"),
    "probe_level": ("the probe names a proof level `references/verification-levels.json` does not know",
                    PROBE_DOOR),
    "probe_evidence": ("the probe names no hashed evidence inside this instance", PROBE_DOOR),
    # HF1-14: an instance that ran green whose probe could not run here, and whose gap the person's recorded word
    # names. Not a defect of this record and not a product finding: the window is accepted as unresolved, and
    # `story_step.py finish` derives the pair. S8 reads it as the critic's `unverified` ("Left with you", D-0013).
    PROBE_GAP_KIND: (
        "this instance ran green and its probe could not run here; a recorded word of the person names it, or the factory "
        "named it (its own data gap)",
        "this window is accepted as unresolved: `story_step.py finish` derives the `unresolved` pair from this "
        "record; the test goes to the person's debt at S8"),
    # The block claims a gap that no live word of the person names (a revoked or never-recorded word, or a record
    # written by hand): the shape of the claim is fine, the consent is missing.
    PROBE_GAP_UNRECORDED_KIND: (
        "the record claims a probe gap, and no recorded word of the person names this instance",
        "the orchestrator records `" + PROBE_GAP_RECORD + "` (a case key of this instance), then builds this record again with "
        "`window_record.py`; or a probe that writes a receipt removes the gap"),
    "evidence": ("an evidence path is missing from disk or its hash moved",
                 "the run block and the receipts are the evidence; do not edit them"),
    "obligation_binding": ORIGIN["obligation_ids"],
    "obligation_hash": ORIGIN["obligation_hash"],
    "assertion_identity": ORIGIN["assertion_id"],
    "defect_location": ORIGIN["defect_location"],
    "change_disposition": ORIGIN["change_disposition"],
    "change_basis": ORIGIN["change_basis_ref"],
    "malformed_instance": ORIGIN["input_hash"],
    "quality": ("no script writes a quality receipt for this check",
                "record the person's word with `waiver.py --stage S5 --block \"not receipted\"`"),
    HANDED_OUTCOME: ("this instance was handed to the person and never ran here",
                     "accept the window with `unresolved` naming `handed_to_person`"),
    # B-375: the record SAYS the person runs this instance and the manifest does not. The fault is the record's or the
    # manifest's (the automator's), not the product's (FR-46): no `product:` and no derived pair. `run_suite.py` is no door
    # here - the profile is the person's, the factory cannot execute it.
    HANDED_UNCONFIRMED_KIND: (
        "the record says the person runs this instance, and the story's manifest does not: no unresolved[] row with "
        "reason `handed_to_person` covers every case of its scope, or a run of it reached a result",
        "the automator moves each case the person runs to `unresolved[]` (reason `handed_to_person`, the profile and what "
        "the person runs in `detail`) through `manifest_put.py --task <T> --fragment <file>`, splits a test that also "
        "proves a case the person does not run, or drops the stale row beside a run the same way; then `window_record.py` "
        "builds this record again - never edit the record"),
    # An instance the stand blocked (t-219): its unresolved[] row says so and carries the fix, no run of it
    # reached a verdict, and the critic's review of it is static. Not a defect of this record, and not a
    # product finding: the window is accepted as unresolved, and `story_step.py finish` derives the pair.
    BLOCKED_OUTCOME: ("the manifest's unresolved[] row says the stand blocked this instance (reason "
                      "`blocked_by_env`, with its remedy); no run of it reached a verdict",
                      "this window is accepted as unresolved: the critic's `story_step.py finish` derives "
                      "the `unresolved` pair from this record; the remedy is the person's to apply or hand over "
                      "at gate B"),
    "empty_scope": ("the manifest has no instance for any case of the dispatched scope",
                    "the automator writes the tests, or the case moves to `unresolved[]`"),
    # A test changed between its red run and the next green run (t-108, B-194): one row per kind of gap
    # `acceptance.expectation_change_gaps` names, and each says whose move it is. The base row is the
    # critic's (a missing verdict) and is the one `_explain` finds by the gap's own kind. A window that
    # lists such a change is accepted only as an unresolved acceptance - a person's informed pass.
    "expectation_change": ("a test changed after its red run and the manifest's `expectation_changes[]` "
                           "record of that change carries no `critic_verdict`",
                           "the critic records one verdict per change through `manifest_put.py` "
                           "(`critic_verdict`, one of the closed list) and builds this record again; "
                           "or the window is accepted with `unresolved` and a `reason`, a person's word"),
    # ONE road for `could_not_judge`, said the same way in the vocabulary, the rubric and the critic's
    # charter: the critic's note is the reason, and the CONDUCTOR records the window as unresolved.
    "expectation_change_could_not_judge": (
        "the critic recorded `could_not_judge` for a test changed after its red run",
        "the conductor records the window as unresolved with the reason (the critic's note): accepted "
        "with `unresolved` and a `reason`"),
    "expectation_change_fitted_to_code": (
        "the critic recorded `fitted_to_code`: a test's expected value was changed to what the code did",
        "the automator restores the Then's value and hands the test over RED with "
        "`contradicts_requirement`, then this record is built again; or the window is accepted with "
        "`unresolved` and a `reason`, a person's word"),
    "expectation_change_unknown_verdict": (
        "the `critic_verdict` of a change record is not one of the closed list",
        "the critic rewrites it with one of the allowed words through `manifest_put.py`"),
}


def change_origin(code: str) -> tuple:
    """The `GAP_ORIGIN` row of one kind of `expectation_change` gap (`acceptance.expectation_change_gaps`)."""
    return GAP_ORIGIN.get("expectation_change_" + code) or GAP_ORIGIN["expectation_change"]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _origin_text(field: str) -> str:
    """"<what was not on disk>; <the command that puts it there>" for one field."""
    missing, command = ORIGIN[field]
    return missing + "; " + command


def _safe_name(value: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "._-") else "-" for ch in str(value))[:120] or "window"


def _load(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _same_window(other: dict, dispatch: dict) -> bool:
    """The controller's own definition of "the same window", so a record this script builds
    is never rejected for naming a pair the controller does not recognise. An S5 PLAN dispatch is never the window's peer
    (its scope is every case, which with one window is the window's own; SC1-14 B1a): `controller.s5_part_of` is the one reader."""
    from controller import s5_part_of
    return (other.get("stage") == dispatch.get("stage") and s5_part_of(other) != "plan"
            and set(other.get("scope") or []) == set(dispatch.get("scope") or [])
            and other.get("input_hash") == dispatch.get("input_hash"))


def _peer(state: dict, dispatch: dict, role: str) -> dict:
    """The accepted dispatch of `role` covering the same window, latest first."""
    peers = [d for d in (state.get("dispatches") or {}).values()
             if isinstance(d, dict) and d.get("role") == role and d.get("id") != dispatch.get("id")
             and d.get("status") == "accepted" and _same_window(d, dispatch)]
    return peers[-1] if peers else {}


def _terminal_runs(task_root: Path) -> dict:
    """instance id -> (the latest terminal result row, its block, the block's path).

    "Latest" is the story's ONE block order, `run_history.read_run_blocks`: the block's own clock,
    a reparse block right after the block it supersedes. File-name order is not chronological for
    a `--reparse-block` block (named `<attempt>-reparse-<hash>.json`, no stamp): the reparse of an
    attempt whose id starts with a digit below `2` sorts before every `2026...` block, and the
    instance's "latest" outcome (and the evidence the window cites) came from an OLDER block
    (t-149, F-order). Only `passed`/`failed` count (`contract.TERMINAL_RESULT_STATUSES`):
    `skipped` and `not_run` are not a product outcome.
    """
    import run_history
    found: dict = {}
    blocks, _unreadable = run_history.read_run_blocks(task_root)
    for item in blocks:
        block = item["data"]
        for row in block.get("results") or []:
            if not isinstance(row, dict):
                continue
            identity = str(row.get("instance_id") or "")
            if identity and C.result_status(row) in C.TERMINAL_RESULT_STATUSES:
                found[identity] = (row, block, task_root / RUN_BLOCK_DIR / item["name"])
    return found


def _run_evidence(task_root: Path, block: dict, path: Path) -> list:
    """The run block itself, plus the reporter bytes it names when they are still on disk."""
    refs = [{"path": path.relative_to(task_root).as_posix(), "sha256": _digest(path)}]
    for item in block.get("evidence") or []:
        raw = str((item or {}).get("report_path") or "")
        if not raw or Path(raw).is_absolute():
            continue
        report = (task_root / raw).resolve()
        if report.is_relative_to(task_root.resolve()) and report.is_file():
            refs.append({"path": Path(raw).as_posix(), "sha256": _digest(report)})
    return refs


def _blocked_entry(task_root: Path, identity: str, cases: list, row: dict, run) -> dict:
    """One element of the window's `blocked_by_env[]`: `{instance_id, cases, detail, remedy, stand, last_run}`.

    `stand` is the environment the instance's latest terminal run block says it ran against
    (`runtime_provenance.environment_id`), else the story's own (`pipeline.json` `environment`), else
    `unknown` - never a guess (FR-41). `last_run` is `{status, reason, block}` of that run, or null when no
    run reached a terminal result: a test that stayed on a page that never loaded is a `failed` row here,
    and the critic's `unverified` reads it against the changed files (code does not judge, FR-47)."""
    stand = ""
    last = None
    if run:
        row_run, block, path = run
        stand = str(((block.get("runtime_provenance") or {}) if isinstance(block.get("runtime_provenance"), dict)
                     else {}).get("environment_id") or "").strip()
        last = {"status": C.result_status(row_run), "reason": str(row_run.get("reason") or ""),
                "block": path.relative_to(task_root).as_posix()}
    if not stand:
        stand = str(_load(task_root / "pipeline.json").get("environment") or "").strip() or "unknown"
    return {"instance_id": identity, "cases": list(cases), "detail": str(row.get("detail") or ""),
            "remedy": row.get("remedy"), "stand": stand, "last_run": last}


def _red_row_record(row: dict) -> dict:
    """One element of a `probe_not_applicable.rows[]`: the case of the `unresolved[]` row that makes an instance red,
    and the keys that say WHICH part of the case it is about (`contract.UNRESOLVED_SLICE_KEYS` and `thens`), exactly as
    the manifest holds them - copied, never reworded and never completed (the window records what the manifest said, a
    later reader compares it with the manifest). A key the row does not hold is not written."""
    record = {"case": str(row.get("case") or "")}
    for key in (*C.UNRESOLVED_SLICE_KEYS, C.UNRESOLVED_THENS_KEY):
        if key in row:
            record[key] = copy.deepcopy(row[key])
    return record


def _row_receipt_ref(entry: dict, task_root: Path) -> dict:
    """`{path, sha256}` of the receipt the manifest row itself names
    (`sensitivity_proof.receipt_ref`), the hash taken from the file on disk the way
    `contract.binding_receipt_ref` takes it; `{}` when the row names none, or the file is not
    there, or the path leaves the task."""
    proof = entry.get("sensitivity_proof")
    ref = proof.get("receipt_ref") if isinstance(proof, dict) else None
    raw = str(ref.get("path") or "") if isinstance(ref, dict) else ""
    if not raw or Path(raw).is_absolute():
        return {}
    path = (task_root / raw).resolve()
    if not path.is_relative_to(task_root.resolve()) or not path.is_file():
        return {}
    return {"path": raw, "sha256": _digest(path)}


def _window_receipt_ref(entry: dict, manifest: dict, task_root: Path) -> dict:
    """The receipt the window reads: what `proof_level.reached` says the row reaches (the best
    VALID receipt for the bytes the row binds now). A receipt for other bytes is never chosen.
    When nothing is valid, the old lookups (the row's ref, then the binding's) still find a
    record `reached` cannot vouch for - the mutable probe record of before receipts, which the
    window has always counted as the live check - but never one measured on other bytes."""
    got = proof_level.reached(entry, manifest, task_root)["ref"]
    if got.get("path") and (task_root / got["path"]).is_file():
        return {"path": got["path"], "sha256": _digest(task_root / got["path"])}
    if not proof_level.current_test_sha(entry):
        return {}  # the test's bytes are unknown: no record can be vouched for as theirs (FR-41)
    for ref in (_row_receipt_ref(entry, task_root), C.binding_receipt_ref(manifest, entry, task_root)):
        if ref and not proof_level.other_bytes(entry, _load(task_root / ref["path"])):
            return ref
    return {}


# t-1968 N4: the door of a `semantic_sensitivity` gap that comes from a probe of ANOTHER line than the obligation's check
# (`proof_level.receipt_off_target`, the one reader). Only that cause gets it: the gap has other causes (obligation hash, ...).
OFF_TARGET_DOOR = (PROBE_DOOR + "; for a probe of another line: probe the Then's line "
                   "(`probe_by_code.py ... --at <n>`, <n> = the line of the Then's check; a Python test has no `--at`); or, when no "
                   "check of the Then can be inverted here, return the item `unverified` with its reason and finish the window with "
                   "`story_step.py finish ... --unresolved <why> --reason \"<what could not be probed>\"`: the test stays not proved, "
                   "and delivery says it requires a current sensitivity proof. No word of the person closes it")


def off_target_note(identity: str, probe) -> tuple:
    """`(identity, "semantic_sensitivity", "<what>; <door>")` for a probe that broke another line than the obligation's check,
    else `()`. The same note shape `build` gives the other conditional doors; `_explain_parts` reads it."""
    why = proof_level.receipt_off_target(probe)
    return (identity, "semantic_sensitivity", why + "; " + OFF_TARGET_DOOR) if why else ()


def _scope_note(identity: str, probe, ref: dict) -> tuple:
    """`(identity, "sensitivity", "<what>; <door>")` for a probe block that is NOT a proof of the whole test - a one-check product receipt
    (`partial_product`) or a receipt whose entries are no longer the ones in play (`model_changed`) - else `()`. The keys are named; the
    door is a thing the reader of the note can do (FR-2). The same note shape `build` gives the other conditional doors."""
    if not isinstance(probe, dict):
        return ()
    if probe.get("verdict") == PARTIAL_PRODUCT:
        keys = ", ".join(str(c.get("key")) for c in probe.get("checks") or [] if isinstance(c, dict) and c.get("key")) or "no check it could read"
        return (identity, "sensitivity",
                f"the product receipt {ref.get('path')} proves one check ({keys}) and the other checks of this test stay owed; "
                "to count it, the critic writes the entry `{\"check\": \"<key>\", \"product\": \"<the receipt's path>\"}` into the model file "
                "`work/probe-models/<dispatch id>.json` and makes the plain `probe_by_code.py` call again, which walks the other checks")
    if probe.get("verdict") == MODEL_CHANGED:
        keys = ", ".join(str(k) for k in probe.get("stale_checks") or [])
        if probe.get("stale_note"):
            return (identity, "sensitivity",
                    f"the receipt {ref.get('path')} cannot be shown to stand on the entries now in play: "
                    f"{' '.join(str(probe['stale_note']).split())} (checks: {keys or 'none named'}); "
                    "make the plain `probe_by_code.py` call again, so every check stands on the entries now written")
        return (identity, "sensitivity",
                f"the receipt {ref.get('path')} was made on other model entries than the ones now in play (checks: {keys}); "
                "make the plain `probe_by_code.py` call again, so every check stands on the entries now written")
    return ()


def _probe_scope_notes(window: dict, info: list) -> None:
    """Info lines (never a gap) for what a probe block says about its own reach, each once per instance: an OLD product receipt (no `scope`,
    `probe_tool: red_sandbox.py`) or an OLD live one (no `checks`, `probe_tool: probe_by_code.py`), written before receipts named what
    they prove, stands on the same bytes as before and says that it
    proves ONE check (EP-I); a `whole_unlisted` receipt stands and says the factory cannot list this test's checks (EP-W: a test whose
    language has no reader keeps its only door); a kept aggregate carries `last_attempt`, a later attempt that ended unproved while this
    proof stands. A block with none of these says nothing (AR-23). Reads the window only."""
    for item in window.get("instances") or []:
        probe = item.get("probe") if isinstance(item, dict) else None
        if not isinstance(probe, dict):
            continue
        who = item.get("instance_id")
        old_product = "scope" not in probe and probe.get("probe_tool") == "red_sandbox.py"
        old_live = "checks" not in probe and "scope" not in probe and probe.get("probe_tool") == "probe_by_code.py"
        if (old_product or old_live) and probe.get("verdict") == "intended_failure":
            # ONE carrier of the line for both kinds (EP-I, F7); info only: the block's verdict and level are never touched here
            info.append(f"the probe is an older {'product' if old_product else 'live'} receipt that proves one check, the one it broke ({who})")
        elif probe.get("scope") == proof_level.WHOLE_UNLISTED:
            info.append(f"the factory cannot list this test's checks (no reader for its language), so the product receipt proves "
                        f"the test as it always did ({who})")
        last = probe.get("last_attempt")
        if isinstance(last, dict) and last:
            info.append(f"a later probe attempt ended {last.get('verdict')} ({' '.join(str(last.get('why') or '').split())}); the proof "
                        f"above is the earlier one, and it stands on the entries now in play ({who})")


def _unknown_target_notes(window: dict, info: list) -> None:
    """One line per probe whose `target` the probe recorded as UNKNOWN (`is_assertion_id: null`, E4.1): it counts as today and
    is said, not hidden (FR-41). A probe that records no `target` at all reads as unknown and says nothing (AR-23)."""
    for item in window.get("instances") or []:
        probe = item.get("probe") if isinstance(item, dict) else None
        target = probe.get("target") if isinstance(probe, dict) else None
        if isinstance(target, dict) and "is_assertion_id" in target and target["is_assertion_id"] is None:
            info.append("the probe's target could not be compared with the obligation's assertion (no `assertion_id` of the "
                        f"form `<file>:<line>`) ({item.get('instance_id')})")


def unproved_keys_text(task_root, identity: str, current: str) -> str:
    """The sentence that names the checks of `identity`'s aggregate (`work/probes/<iid>.json`, of THESE bytes) that are not proved, and the
    `not_owed` ones with the reason the critic gave, for the tier above; `""` when there is no aggregate of these bytes, it has no
    `checks`, or every check stands (t-2064 P6 item 1). `probe_record_state` says whether the record is of these bytes (the ONE reader of
    that); the rows are read from the file it names. Nothing is cut: a list that hid keys would hide unproved checks (AR-28). Never raises."""
    try:
        state = proof_level.probe_record_state(task_root, identity, current)
        if state["state"] == "not_run" or not state.get("record"):
            return ""
        rows = [r for r in _load(Path(task_root) / state["record"]).get("checks") or [] if isinstance(r, dict) and r.get("key")]
        owed = [r for r in rows if r.get("verdict") != "not_owed"]
        unproved = [f"{r['key']} ({r.get('verdict')})" for r in owed if r.get("verdict") != "intended_failure"]
        excused = [f"{r['key']} ({' '.join(str(r.get('reason') or 'no reason recorded').split())})"
                   for r in rows if r.get("verdict") == "not_owed"]
        parts = []
        if unproved:
            parts.append(f"{len(owed) - len(unproved)} of {len(owed)} checks of this test are proved, not proved: " + ", ".join(unproved))
        if excused:
            parts.append("not owed, the critic's word that this instance does not reach them (the tier above reads the reasons): "
                         + ", ".join(excused))
        # no `; ` inside: a note is `<missing>; <door>`, split at its first `; ` (`_explain_parts`), and a reason is free text
        return (" / ".join(parts) + ".").replace("; ", ", ") if parts else ""
    except Exception:  # noqa: BLE001 - a text that only adds keys never stops the window
        return ""


def _keys_first(task_root, item: dict) -> str:
    """`unproved_keys_text` of a window item plus one space, or `""`: what a probe note starts with when the instance's aggregate names
    unproved or not-owed checks (the whole list: the window's note is where nothing is cut)."""
    text = unproved_keys_text(task_root, str(item.get("instance_id") or ""), str(item.get("input_hash") or ""))
    return text + " " if text else ""


PARTIAL_PRODUCT = "partial_product"    # block verdict of a product receipt that proves ONE check of several (EP-W); never `intended_failure`
MODEL_CHANGED = "model_changed"           # block verdict of a receipt whose entries are no longer the ones in play (the P4b hand-over)


def _entries_in_play(task_root, identity: str) -> tuple:
    """`(aggregate dict or None, {key: entry sha of the per-check record}, why)`: the entry shas now in play for `identity`'s checks, read
    from the aggregate's rows (`probe_by_code._entry_sha` of each row's `entry`, the one function the receipt's `checks[].entry_sha` is
    made with) and from the per-check records, which a call that was kept under an older proved aggregate (`keep_standing_record`) has
    already rewritten for the changed check. THREE answers, never two (t-2064 fix round F, F9; FR-59, AR-28): an ABSENT aggregate (no
    file, or no rows) is `(None, {}, "")` - the comparison is not made, as today; an UNREADABLE one (the file exists but cannot be read
    or parsed, is not an object, its `checks` is not a list; or a per-check record that exists and cannot be read) is `(None, {}, <why>)`
    - an unknown, which the caller reads as stale. Reads files. Never raises."""
    path = proof_level.probe_record_path(task_root, identity)
    try:
        if not path.exists():
            return None, {}, ""
        try:
            aggregate = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError) as exc:
            return None, {}, f"{path.name} exists and cannot be read ({type(exc).__name__})"
        if not isinstance(aggregate, dict):
            return None, {}, f"{path.name} is not a JSON object"
        if aggregate.get("checks") and not isinstance(aggregate["checks"], list):
            return None, {}, f"{path.name} has `checks` that is not a list"
        rows = [r for r in aggregate.get("checks") or [] if isinstance(r, dict) and r.get("key")]
        if not rows:
            return None, {}, ""
        import probe_by_code      # the ONE key grammar and the ONE per-check reader (F8, AR-13); lazy: this module is imported by many that never probe
        shas = {}
        for row in rows:
            try:
                file, line, ordinal = probe_by_code._parse_at_row(row["key"])
            except probe_by_code.Refusal:
                continue            # a key that is no `<file>:<line>[#n]` names no per-check record
            stored = probe_by_code._read_check_record(task_root, identity, line, ordinal, file=file or None)
            if stored is None:
                record_path = proof_level.record_read_path(task_root, identity, line, ordinal, file=file or None)
                if record_path.exists():
                    return None, {}, f"the check record {record_path.name} exists and cannot be read as an object"
                continue
            if stored.get("entry_sha"):
                shas[str(row["key"])] = str(stored["entry_sha"])
        return aggregate, shas, ""
    except Exception as exc:  # noqa: BLE001 - a reader that only adds a fact never stops the window; what it could not read is said
        return None, {}, f"the probe record of {identity} could not be compared ({type(exc).__name__})"


def _stale_checks(receipt: dict, task_root, identity: str) -> tuple:
    """`(keys, why)`: the keys of a receipt's `checks[]` that no longer stand on the entries in play - no row of the aggregate for the key, a
    different `statement_sha`, a different entry sha (the aggregate's row, or the newer per-check record), and the keys of the aggregate the
    receipt does not name at all (so `checks: []` against an aggregate with rows is never a pass) - and `why`, a note when the comparison
    could not be made because what it compares with is UNREADABLE (`_entries_in_play`) or failed inside: an unknown is stale (keys = the
    receipt's own, so the block names them), never a pass (F9; FR-59, AR-28). `([], "")` when the receipt has no `checks` list (an old one,
    read as before: EP-I item 5), is `whole_unlisted`, when `task_root` is unknown, or when there is NO aggregate to compare with (today's
    behaviour: the comparison is just not made). Pure of judgment: it compares recorded shas."""
    held = receipt.get("checks") if isinstance(receipt, dict) else None
    if not isinstance(held, list) or task_root is None or receipt.get("scope") == proof_level.WHOLE_UNLISTED:
        return [], ""                   # (`checks: []` of a live receipt is NOT skipped: it names nothing, so every row of the aggregate is stale)
    aggregate, per_check, why = _entries_in_play(task_root, identity)
    if aggregate is None:
        return ([str(one.get("key")) for one in held if isinstance(one, dict) and one.get("key")], why) if why else ([], "")
    try:
        import probe_by_code      # the ONE `_entry_sha` (AR-13); lazy: this module is imported by many that never probe
        now = {str(r["key"]): r for r in aggregate["checks"] if isinstance(r, dict) and r.get("key")}
        stale = []
        for one in held:
            key = str((one or {}).get("key") or "") if isinstance(one, dict) else ""
            row = now.get(key)
            if row is None:
                stale.append(key)
                continue
            entry_sha = probe_by_code._entry_sha(row["entry"]) if isinstance(row.get("entry"), dict) else ""
            if (str(one.get("statement_sha") or "") != str(row.get("statement_sha") or "")
                    or str(one.get("entry_sha") or "") != entry_sha
                    or (key in per_check and str(one.get("entry_sha") or "") != per_check[key])):
                stale.append(key)
        named = {str((one or {}).get("key") or "") for one in held if isinstance(one, dict)}
        return [k for k in dict.fromkeys(stale + [k for k in now if k not in named]) if k], ""
    except Exception as exc:  # noqa: BLE001 - a comparison that failed is an unknown: stale, with the class said, never a silent pass
        return ([str(one.get("key")) for one in held if isinstance(one, dict) and one.get("key")],
                f"the comparison with the probe record failed ({type(exc).__name__})")


def _probe_from_receipt(receipt: dict, ref: dict, item: dict, task_root=None) -> dict:
    """The window's `probe` block, read from the immutable sensitivity receipt, and what the receipt SAYS IT PROVES (t-2064 P6).

    `_receipt_block` reads the facts as before. On top of it: a `scope: "one_check"` receipt (a product receipt, EP-W) proves the one
    check it names: its block's verdict is `partial_product`, so `acceptance.validate_window` gives `sensitivity:` by its own line
    and the keys travel in `checks`; a receipt that carries `checks` and no longer stands on the entries now in play (`_stale_checks`:
    the model changed after the receipt, or a check was added) reads `model_changed`, the keys named in `stale_checks`, never
    `intended_failure`; a receipt with neither key is an old one and reads exactly as before (EP-I). `scope` and `checks` are copied
    as recorded (an absent one stays absent). `task_root` is needed only for the staleness comparison; without it that is not made."""
    block = _receipt_block(receipt, ref, item)
    for key in ("scope", "checks", "probe_tool"):
        if receipt.get(key) is not None:
            block[key] = copy.deepcopy(receipt[key])
    if receipt.get("scope") == proof_level.ONE_CHECK:
        block["verdict"] = PARTIAL_PRODUCT
        return block
    stale, why = _stale_checks(receipt, task_root, str(item.get("instance_id") or ""))
    if stale or why:
        block["verdict"], block["stale_checks"] = MODEL_CHANGED, stale
        if why:
            block["stale_note"] = why           # the comparison could not be made: an unknown, said as one (F9)
    elif task_root is not None and isinstance(receipt.get("checks"), list):
        kept = _load(proof_level.probe_record_path(task_root, str(item.get("instance_id") or ""))).get("last_attempt")
        if isinstance(kept, dict) and kept:
            block["last_attempt"] = copy.deepcopy(kept)     # a later attempt that ended unproved; this proof is the earlier one
    return block


def _receipt_block(receipt: dict, ref: dict, item: dict) -> dict:
    """The window's `probe` block, read from the immutable sensitivity receipt.

    `red_sandbox.write_sensitivity_receipts` writes a receipt ONLY after `verify()` accepted
    the probe, which is exactly the check that the observed failure was the intended assertion
    at the expected location. So the location is one value here, recorded twice the way
    `validate_window` reads it; `failure_kind` and the mutation are copied verbatim, so a
    receipt that shows anything but a real-behaviour assertion failure still fails the window
    instead of being talked up by this script.
    """
    # Two probes write two shapes. `probe_by_code.py` — the ONLY probe the code critic's brief
    # authorises — prepares the block this function has to produce and calls it `window_probe`
    # ("the critic copies this, never retypes it"); nothing read it, so this function read its
    # fields under red_sandbox's names, found `mutation` = "invert" instead of "real_behavior" and
    # `expected_assertion_failure` missing, and refused the window. Live TP1-13797 run 5: seven
    # critic dispatches, $13.64, on a receipt that was unreachable by construction while both
    # probes sat on disk as `intended_failure`. The proof is the same; only the spelling differed.
    #
    # The level is the receipt's own (`proof_level.level_of`): an old mutable probe record is the
    # live check, an old `red_sandbox.py` receipt caught a broken product, and a receipt of neither
    # (an unknown level) carries the unknown word through so `acceptance` names it instead of
    # this script talking it up.
    level = proof_level.level_of(receipt)
    prepared = receipt.get("window_probe")
    # What the probe measured about the test's bytes travels with it: the code of those bytes and, when
    # the probe had one, the per-test identity (`proof_level.proof_identity`). Absent when the receipt
    # or record predates them - the window then binds the probe by the raw file, as it always did.
    measured = {key: receipt[key] for key in ("test_code_sha", "instance_identity") if receipt.get(key)}
    # t-1968: facts the probe recorded about HOW it proved (`proved_by`, N1) and WHAT it mutated (`target`, N4). The receipt
    # core spells the other probe fields under red_sandbox's names, so `probe_by_code.WINDOW_PROBE_FIELDS` cannot be copied
    # through here; these two keep their names on both sides, and an absent one stays absent (never a placeholder, FR-41).
    measured.update({key: receipt[key] for key in ("proved_by", "target") if receipt.get(key)})
    if isinstance(prepared, dict) and prepared.get("verdict"):
        block = dict(prepared)
        block.setdefault("obligation_ids", list(item.get("obligation_ids") or []))
        block.setdefault("obligation_hash", item.get("obligation_hash"))
        block.setdefault("defect_location", item.get("defect_location"))
        block.setdefault("assertion_id", item.get("assertion_id"))
        block["evidence_ref"] = block.get("evidence_ref") or ref.get("path")
        block["proof_level"] = level if level else receipt.get("proof_level")
        # The window compares the probe's bytes with the instance's, and the instance carries the
        # raw sha256 of the test file. The old record's prepared `input_hash` is the run's
        # fingerprint over test and helper files - another quantity (t-035); the same record
        # measured the raw file too, before it mutated anything, and that is what is compared.
        if receipt.get("test_file_sha256"):
            block["input_hash"] = str(receipt["test_file_sha256"])
        return {**block, **measured}
    location = str(receipt.get("assertion_location") or "")
    # ONE rule for "the same reason", shared with the producer (`red_sandbox.reason_matches`) and
    # read by `acceptance.validate_window` as plain equality: whole folded texts when they agree
    # (every receipt written before this existed keeps matching), else the headlines - a .NET
    # assertion's Expected/Actual lines are the reporter's, not the author's pin (Fact 9).
    expected_reason, actual_reason = reporters.assertion_reason(
        receipt.get("expected_assertion_failure"), receipt.get("actual_failure"))
    return {"verdict": "intended_failure", "input_hash": str(receipt.get("test_content_hash") or ""),
            "expected_location": location, "actual_location": location,
            "expected_reason": expected_reason, "actual_reason": actual_reason,
            # B-380: the lines the reasons were compared on; the pair above stays byte for byte what it was
            "reason_detail": reporters.reason_detail(receipt.get("expected_assertion_failure"),
                                                     receipt.get("actual_failure")),
            "failure_kind": receipt.get("failure_kind"),
            "mutation_kind": receipt.get("mutation_kind") or receipt.get("mutation"),
            "proof_level": level if level else receipt.get("proof_level"),
            "obligation_ids": list(item.get("obligation_ids") or []),
            "obligation_hash": item.get("obligation_hash"),
            "defect_location": item.get("defect_location"),
            "assertion_id": item.get("assertion_id"),
            "evidence_ref": ref.get("path"), **measured}


def _gap_why(text) -> str:
    """One line of at most `C.PROBE_GAP_WHY_LIMIT` characters: whitespace folded, the cut marked by `…` (which counts)."""
    one = " ".join(str(text or "").split())
    return one if len(one) <= C.PROBE_GAP_WHY_LIMIT else one[:C.PROBE_GAP_WHY_LIMIT - 1] + "…"


def probe_gap_block(task_root: Path, item: dict, keys: list, words: dict, class_word=None, proved_words=None):
    """The window item's `probe_gap` block, or None when no gap is to be written (HF1-14).

    Written ONLY when a recorded word of the person names the instance: its id, else one of its case keys `keys`
    (`words` is `contract.probe_gap_words`; identifier equality, never `*`). The factory names no gap of its own (t-1968 N2): a
    green item whose probe record of THESE bytes is `incomplete` with `cause: judgment` (`proof_level.probe_owes_judgment`) is
    the code critic's to judge, and its window note names `JUDGE_DOOR` (`build`). The probe's record
    (`proof_level.probe_record_state`, the ONE reader) says what happened: `not_executed` / `incomplete` of THESE bytes is the
    verdict as it stands; no record, an unreadable one, one of other bytes or one with no verdict is `not_run`. A record
    that JUDGED the current bytes (`intended_failure` with no valid receipt, `no_failure`, `wrong_location`) writes
    no gap: a probe that caught something is not one that could not run, and its roads are the probe's own (E8).
    `class_word` (GW1-43, `contract.probe_gap_class_word`) is read LAST, after every equality: it names the instance only when
    the item ran green and the tool could not read the probe (`proof_level.probe_could_not_run`); then `named_by` is
    `class:probe_gap_accepted`. A probe nobody ran, one of other bytes, or a stand that was down takes no class word.
    The class word `probe gap: tooling:<language>` (EP1-36) names the instance too, but ONLY as the LAST key, so a word about
    the instance itself stays `named_by`: it is read when the probe's record says the tool could not read this language
    (`proof_level.tooling_gap_key`: `cause: tooling`, `not_executed`/`incomplete`, the current bytes); a record that judged the
    test, one of other bytes, none, or a red test take no such word.
    A test whose probe the code critic could not judge (`cannot_judge`, t-1968 N5) is named ONLY by the person's `probe not proved:
    <case key>` word (`proved_words`, `contract.probe_not_proved_words`) of the judgment's time or later; none of the words above is
    read for it (the owner's word 05.11.2026), and it takes no class word. A record still `unjudged` (`cause: judgment`, no judgment
    yet - a re-probe of a case that was named for tooling, say) is NEVER named, by any word, instance, case, `tooling:` or class: it is
    the code critic's to judge (t-2007 F1). `class_word=None` / `proved_words=None` read as no class word / no `probe not proved:` word.
    Error direction: toward `not_run` (a gap that still needs the word), never toward 'probed'."""
    identity = str(item.get("instance_id") or "")
    current = str(item.get("input_hash") or "")
    if proof_level.probe_owes_judgment(task_root, identity, current) == "unjudged":
        return None
    facts = proof_level.cannot_judge_facts(task_root, identity, current)
    if facts is not None:
        found = proof_level.not_proved_word(facts, keys, proved_words or {})
        if found is None:
            return None
        state = proof_level.probe_record_state(task_root, identity, current)
        keys = unproved_keys_text(task_root, identity, current)       # unproved checks first: `why` is bounded (PROBE_GAP_WHY_LIMIT) and keeps the head; the window's note carries the whole list (P6)
        return {"verdict": "incomplete", "record": state["record"],
                "why": _gap_why((keys + " " if keys else "") + "the code critic could not judge it: " + facts["why"]),
                "named_by": f"{C.PROBE_NOT_PROVED_PREFIX} {found[0]}", "words": found[1]["words"], "at": found[1]["at"]}
    klass = proof_level.tooling_gap_key(task_root, identity, current)
    named = next((key for key in [identity] + list(keys) + [klass] if key and key in words), None)
    said = words.get(named) if named is not None else None
    if named is None and class_word and item.get("outcome") == "passed" \
            and proof_level.probe_could_not_run(task_root, identity, current):
        named, said = class_word["key"], class_word
    if named is None:
        return None
    state = proof_level.probe_record_state(task_root, identity, current)
    if state["state"] == "judged":
        return None
    keys = unproved_keys_text(task_root, identity, current)
    return {"verdict": state["state"], "record": state["record"], "why": _gap_why((keys + " " if keys else "") + state["why"]), "named_by": named,
            "words": said["words"], "at": said["at"]}


def _word_owed(window: dict, root) -> tuple:
    """`(items by instance id, the ids of the green items whose word the window still owes)`: an item that ran green (`passed`) and
    has the shape line `<id>: probe is missing ...`, or a `probe_gap` block that `acceptance.probe_gap_named` does not name. The ONE
    computation (t-2007, item 6) of `probe_gap_cases`, `probe_judgment_cases` and `probe_word_door`. Raises only what its readers raise."""
    items = {str(i.get("instance_id") or ""): i for i in window.get("instances") or [] if isinstance(i, dict)}
    shape, named = set(C.window_shape_errors(window)), probe_gap_named(window, root)
    owed = {iid for iid, item in items.items() if iid and item.get("outcome") == "passed"
            and (f"{iid}: {C.PROBE_MISSING_ERROR}" in shape or (isinstance(item.get("probe_gap"), dict) and iid not in named))}
    return items, owed


def probe_gap_cases(window, root) -> list:
    """`[(case key, [instance ids])]`, sorted by case key: the cases whose probe-gap word the person can give at the S5 seam (B-16).

    Joins ids by equality, reads no verdict. An instance qualifies when it ran green (`passed`), the window still owes its
    word (the shape line `<id>: probe is missing ...`, or a `probe_gap` block that `acceptance.probe_gap_named` does not name)
    and the tool could not read its probe (`proof_level.probe_could_not_run`: not a probe nobody ran, a stand that was down or a
    probe that judged). A case is listed only when EVERY green word-owed instance of it qualifies: one never-run sibling keeps
    the whole case off the list, because a case word closes its siblings by equality. Error direction: toward fewer cases (an
    instance in no case, a window that is no dict, an unreadable pipeline contribute nothing); never raises."""
    try:
        if not isinstance(window, dict) or not isinstance(window.get("scope_instances"), dict):
            return []
        items, owed = _word_owed(window, root)
        found = []
        for case, ids in window["scope_instances"].items():
            if not isinstance(ids, list):
                continue
            mine = [str(i) for i in ids if str(i) in owed]
            if mine and all(proof_level.probe_could_not_run(root, i, str(items[i].get("input_hash") or "")) for i in mine):
                found.append((str(case), mine))
        # the reader `contract.probe_gap_words` takes ONE token: a key it would refuse is left out, so a door named here always opens
        return sorted(f for f in found
                      if C.prefix_value(f"{C.PROBE_GAP_MATCH_PREFIX} {f[0]}", C.PROBE_GAP_MATCH_PREFIX) == f[0])
    except Exception:  # noqa: BLE001 - a helper that offers a door must never stop the seam
        return []


def _printed(text) -> str:
    """The first `PRINTED_LINES` non-empty lines of a failure text, each folded and at most `PRINTED_LINE_LIMIT` characters (the
    cut marked by `…`, which counts), joined by ` / `; `""` for no text. Pure."""
    lines = [" ".join(line.split()) for line in str(text or "").splitlines()]
    kept = [line for line in lines if line][:PRINTED_LINES]
    return " / ".join(line if len(line) <= PRINTED_LINE_LIMIT else line[:PRINTED_LINE_LIMIT - 1] + "…" for line in kept)


def probe_judgment_cases(window, root) -> list:
    """`[(case key, [{iid, file, line, statement_inverted, statement_after, printed, why}])]`, sorted by case key: the cases whose "not
    proved" word the person can give at the S5 seam because the code critic could not judge their probe (t-1968 N5, the owner's word
    05.11.2026).

    An item qualifies when it ran green (`passed`), the window still owes its word (`_word_owed`, as `probe_gap_cases`) and its probe
    record of THESE bytes says `cannot_judge` (`proof_level.cannot_judge_facts`). A case is listed when EVERY owed green item of it is
    `cannot_judge` OR could not run (`proof_level.probe_could_not_run`: a tooling gap, which the next question of the seam covers
    with its own word) and at least one is `cannot_judge`; only the `cannot_judge` tests are shown, and the word names those only
    (t-2007 S3, the coordinator's decision, marked for the Lead). A red item, an unjudged record or a never-run probe keeps the case
    off the list (a person never judges a probe's text before the critic did). `printed` = the first 3 non-empty failure lines, each at
    most 160 characters, joined by ` / ` (`""` when the record kept no text). Error direction: toward fewer cases; never raises."""
    try:
        if not isinstance(window, dict) or not isinstance(window.get("scope_instances"), dict):
            return []
        items, owed = _word_owed(window, root)
        found = []
        for case, ids in window["scope_instances"].items():
            mine = [str(i) for i in ids if str(i) in owed] if isinstance(ids, list) else []
            facts = {i: proof_level.cannot_judge_facts(root, i, str(items[i].get("input_hash") or "")) for i in mine}
            judged = [i for i in mine if facts[i]]
            rest_is_tooling = all(proof_level.probe_could_not_run(root, i, str(items[i].get("input_hash") or ""))
                                 for i in mine if not facts[i])
            if judged and rest_is_tooling and C.prefix_value(f"{C.PROBE_NOT_PROVED_PREFIX} {case}", C.PROBE_NOT_PROVED_PREFIX) == str(case):
                found.append((str(case), [{"iid": i, "file": facts[i]["file"], "line": facts[i]["line"],
                                           "statement_inverted": facts[i]["statement_inverted"],
                                           "statement_after": facts[i]["statement_after"],
                                           "printed": _printed(facts[i]["failure_text"]), "why": facts[i]["why"]} for i in judged]))
        return sorted(found, key=lambda pair: pair[0])
    except Exception:  # noqa: BLE001 - a helper that offers a door must never stop the seam
        return []


def probe_gap_keys_line(window, root) -> str:
    """The sentence that follows `PROBE_GAP_RECORD` in a refusal: the case keys this window needs, one record each; `""` when
    `probe_gap_cases` lists none. The ONE text of it (AR-13); data only, never raises."""
    keys = [case for case, _ids in probe_gap_cases(window, root)]
    return " The case keys this window needs: " + ", ".join(keys) + " (one record each)." if keys else ""


def probe_word_door(window, root, ticket: str, rest_door: str) -> str:
    """The door sentences of a refusal about owed green tests, built from what the probe records of THOSE tests say (t-2007 F4,
    FR-2/FR-37). The ONE helper of the two controller refusals (AR-13). Per owed item (`_word_owed`): `unjudged` -> the code critic's
    `probe_by_code.JUDGE_DOOR` (a person's word does not close it); `cannot_judge` -> the person's `probe not proved:` word
    (`NOT_PROVED_RECORD`) with the case keys `probe_judgment_cases` lists; any other -> `rest_door`, the old `probe gap:` door text the
    caller builds (it carries `PROBE_GAP_RECORD` and `probe_gap_keys_line`). When no owed item can be classified (a window that is
    not readable), `rest_door` stands alone as before. Data only; never raises."""
    try:
        items, owed = _word_owed(window, root)
    except Exception:  # noqa: BLE001
        return rest_door
    kinds: dict = {"unjudged": [], "cannot_judge": [], "": [], "plain": []}
    for iid in sorted(owed):
        hashed = str(items[iid].get("input_hash") or "")
        kinds["plain" if proof_level.probe_plain_call_owed(root, iid, hashed) else proof_level.probe_owes_judgment(root, iid, hashed)].append(iid)
    if not owed:
        return rest_door
    parts = []
    if kinds["plain"]:      # B2: a walk with no check owing a judgment: `--judge` refuses; the plain call is the door
        parts.append(f" For {', '.join(kinds['plain'])}: {PLAIN_CALL_NOTE}{PROBE_DOOR}.")
    if kinds["unjudged"]:
        import probe_by_code      # the ONE JUDGE_DOOR (AR-13); lazy as in `build`
        parts.append(f" For {', '.join(kinds['unjudged'])}: the probe failed at the mutated line with a text the factory cannot read, "
                     f"and the code critic judges it (a person's word does not close it): {probe_by_code.JUDGE_DOOR}.")
    if kinds["cannot_judge"]:
        keys = [case for case, _items in probe_judgment_cases(window, root)]
        parts.append(f" For {', '.join(kinds['cannot_judge'])}: the code critic could not judge the probe; if the person accepts the "
                     f"test as not proved, the orchestrator records `{NOT_PROVED_RECORD.replace('<T>', ticket)}` for the case key of that "
                     "test, then `window_record.py` builds the record again."
                     + (" The case keys this window needs: " + ", ".join(keys) + " (one record each)." if keys else ""))
    if kinds[""]:
        parts.append(rest_door)
    return "".join(parts)


def _reviewed_identity(task_root: Path, reviewer_id: str) -> dict:
    """instance id -> `{input_hash, test_code_sha, instance_identity[, instance_identity_why]}` of the test the recorded S5 review
    receipt was bound to, when one exists - each field only when the receipt's instance entry carries it.

    A mechanical fix changes the bytes after the review; `acceptance.mechanical_round` reads
    the hash the review WAS bound to, and the only durable record of it is the review receipt
    this script wrote for that critic dispatch. The same entry says which TEST the review was of
    (`proof_level.same_test` binds a review per test instance). They are COPIED from the immutable
    receipt and never computed here: a review is bound to what its reviewer saw, and measuring the
    current file would bind it to whatever is on disk now (D1).
    """
    receipt = _load(task_root / REVIEW_RECEIPT_DIR / (_safe_name(reviewer_id) + ".json"))
    found = {}
    for entry in receipt.get("instances") or []:
        if isinstance(entry, dict) and entry.get("input_hash"):
            found[str(entry.get("instance_id") or "")] = {
                key: entry[key] for key in ("input_hash", "test_code_sha", "instance_identity",
                                            "instance_identity_why") if entry.get(key)}
    return found


def owed_changes(task_root: Path, scope: list, manifest: dict) -> tuple:
    """(the window's `expectation_changes`, why they could not be measured or "").

    The tests of this scope that changed between a red run and the next green run, from the ONE
    detector (`s5_precheck.expectation_changes`, read-only): the pairs S5 OWES a record for, each as
    `{function, red_attempt, green_attempt, critic_verdict}` - the verdict is the critic's word on the
    manifest record that answers the pair, null when there is no record or it carries none;
    `green_attempt` is null for a test that vanished after its red run. Sorted, so the same story
    always gives the same record. Pairs the detector only LISTS (another stage, another scope) owe
    nothing here and are not copied.

    A pair a person's word passed at the S5 exit (`s5_precheck.word_passed_pairs`, the exit's own
    logic) is copied too, with `passed_by_word: true` added: it stays VISIBLE in the window and
    `acceptance.expectation_change_gaps` raises no gap for it while it has no verdict - the word is
    never asked for again (P13). A pair a word did not pass has no such key.

    A detector that cannot measure - it says so, or it raises - is not a reason to stop the story
    (code reports, it does not stop the factory): the list holds what WAS measured and the second
    value says why the rest was not, and `verdict` prints that as a note, never as a gap."""
    try:
        import s5_precheck
        found = s5_precheck.expectation_changes(task_root, scope, manifest)
        pairs = found["pairs"]
        if not isinstance(pairs, list):
            raise TypeError("its `pairs` is not a list")
        # which pairs a person's word passed: the helper may add a reason to `unmeasured`, so it
        # runs BEFORE the reasons are read
        told = found.get("unmeasured") or []
        found["unmeasured"] = [told] if isinstance(told, str) else list(told)
        s5_precheck.word_passed_pairs(task_root, found, scope)
        reasons = [str(why) for why in found["unmeasured"]]
        rows = []
        for pair in pairs:
            if not isinstance(pair, dict) or not pair.get("owed"):
                continue
            record = pair.get("record") if isinstance(pair.get("record"), dict) else {}
            said = record.get("critic_verdict")
            if isinstance(said, str):
                said = said.strip() or None
            row = {"function": str(pair.get("function") or ""),
                   "red_attempt": str(pair.get("red_attempt") or ""),
                   "green_attempt": str(pair["green_attempt"]) if pair.get("green_attempt") else None,
                   "critic_verdict": said}
            if pair.get("passed_by_word") is True:
                row["passed_by_word"] = True
            rows.append(row)
    except Exception as exc:
        return [], (f"the expectation-change detector failed ({type(exc).__name__}: {exc}); a test "
                    "changed after its red run would not be listed")
    rows.sort(key=lambda row: (row["function"], row["red_attempt"], row["green_attempt"] or ""))
    return rows, "; ".join(reasons)


NON_STRING_ID = "non-string id: "     # the prefix of a quality id that was no string (see `demanded_quality_checks`)
QUALITY_PRODUCERS_FILE = Path(__file__).resolve().parents[1] / "references" / "quality-receipt-producers.json"


def _quality_data() -> tuple:
    """`(producers, why words, readable)` of `references/quality-receipt-producers.json` (FR-13: the closed variety is data).
    Unreadable data -> `({}, {}, False)` and ONE stderr line; the caller then keeps the requirement as recorded."""
    try:
        data = json.loads(QUALITY_PRODUCERS_FILE.read_text(encoding="utf-8-sig"))
        producers, why = data["producers"], data.get("why") or {}
        if not isinstance(producers, dict) or not isinstance(why, dict):
            raise ValueError("`producers` and `why` must be objects")
        return producers, why, True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"window_record: references/quality-receipt-producers.json cannot be read ({type(exc).__name__}); "
              "the quality checks are demanded as recorded", file=sys.stderr)
        return {}, {}, False


def quality_why_words() -> dict:
    """The words of the `quality_not_run` reasons (data), `{}` when the file cannot be read."""
    return _quality_data()[1]


def _s0_checked_names(task_root, project) -> "set | None":
    """The capability names the S0 readiness record holds a result for (any status), or None when the record cannot be read.
    Read the way every consumer reads it: `runtime_paths.readiness(project)` through `hooklib.read_json`; the project is
    `project` or the story's own project (`runtime_paths.project_for_task`, the one that admits the story's artifact root)."""
    import hooklib
    import runtime_paths as RP
    where = project
    if not where and task_root is not None:
        try:
            where = RP.project_for_task(task_root)
        except ValueError:
            where = None
    if not where:
        return None
    doc = hooklib.read_json(RP.readiness(where), None, errors=Exception, kind=dict)
    caps = doc.get("capabilities") if isinstance(doc, dict) else None
    return set(caps) if isinstance(caps, dict) else None


def demanded_quality_checks(recorded, task_root=None, project=None) -> tuple:
    """`(demanded, not_run, why)`: the ONE reader of what a window owes in quality receipts (HF4-10, FR-5).

    `demanded` - the recorded ids a factory script produces a receipt for (`producers` of the data file, matched by the
    exact string) plus every id that is not a string. A non-string id is normalised to ONE string, `NON_STRING_ID` + its
    `json.dumps`, here at the writer; the same reader recognises that prefix when the window is read back, so such an id is
    demanded on both sides and never raises.
    `not_run` - `[{"id", "why"}]`, the other string ids: nothing produces their receipt, so none is demanded, and the report
    says so. Rule QNR: `why` is `checked_at_s0` when the S0 readiness record holds a result under that name (the readiness
    step ran it; the report prints no line), `unknown_s0` when the record cannot be read (printed), else `no_producer`
    (printed). Without `task_root`/`project` the record is not consulted (`not_run` then reads `no_producer`; the
    acceptance readers use `demanded` only). Error direction: only toward demanding - unreadable data demands every recorded
    id, as recorded. A `recorded` that is not a list demands nothing (and says so on stderr)."""
    if recorded is None:
        recorded = []
    if not isinstance(recorded, list):
        print("window_record: required_quality_checks is not a list; no quality check is demanded from it", file=sys.stderr)
        return [], [], quality_why_words()
    producers, why, readable = _quality_data()
    ids = []
    forced = set()      # positions that are owed whatever the data says: a non-string id, or its normalised form read back
    for pos, item in enumerate(recorded):
        if isinstance(item, str):
            ids.append(item)
            if item.startswith(NON_STRING_ID):
                forced.add(pos)
        else:
            print(f"window_record: a quality check id that is not a string ({type(item).__name__}) is demanded as written",
                  file=sys.stderr)
            ids.append(NON_STRING_ID + json.dumps(item, sort_keys=True, default=str))
            forced.add(pos)
    if not readable:
        return ids, [], why
    demanded, loose = [], []
    for pos, name in enumerate(ids):
        if pos in forced or name in producers:
            demanded.append(name)
        elif name not in loose:
            loose.append(name)
    not_run = []
    if loose:
        checked = _s0_checked_names(task_root, project) if (task_root is not None or project) else set()
        for name in loose:
            if checked is None:
                reason = "unknown_s0"
            elif name in checked:
                reason = "checked_at_s0"
            else:
                reason = "no_producer"
            not_run.append({"id": name, "why": reason})
    return demanded, not_run, why


def build(task_root: Path, dispatch_id: str) -> tuple:
    """(window record, notes) — notes are `(instance id, field, sentence)` for what was not
    on disk, so the verdict can name the artifact instead of only the missing key."""
    from controller import Controller

    state = Controller(task_root).state()
    dispatches = state.get("dispatches") or {}
    dispatch = dispatches.get(str(dispatch_id))
    if not isinstance(dispatch, dict):
        raise ValueError(f"this story has no dispatch {dispatch_id!r}; it has "
                         + (", ".join(sorted(dispatches)) or "none")
                         + f". {REPAIR_MARKER}: name one of them.")
    role = str(dispatch.get("role") or "")
    notes: list = []
    if role == "qa-automator":
        author, reviewer = dispatch, _peer(state, dispatch, "qa-code-critic")
    else:
        author, reviewer = _peer(state, dispatch, "qa-automator"), dispatch
    if not author:
        notes.append(("", "author_dispatch_id",
                      "no accepted `qa-automator` dispatch covers this window's scope and "
                      "input hash; the author's window is accepted before the critic's"))
    if not reviewer:
        notes.append(("", "reviewer_dispatch_id",
                      "no `qa-code-critic` dispatch covers this window's scope and input hash"))

    manifest_path = Path(C.artifact(task_root, "automation-manifest.json"))
    manifest = _load(manifest_path)
    scope = [str(case) for case in dispatch.get("scope") or []]
    # Only the note for a case with NO instance (`for case, found in scope_instances.items()` below) reads this set: that
    # judgment is the controller's `_cases_without_instances`. Whether an INSTANCE is handed is `handed_instances` (B-375).
    handed = {row.get("case_id") for row in C.handed_tests(manifest)}
    # The instances (or cases) whose probe gap the person accepted, from their own recorded words (HF1-14).
    pipeline = _load(task_root / "pipeline.json")
    probe_gap_words = C.probe_gap_words(pipeline)
    not_proved_words = C.probe_not_proved_words(pipeline)      # t-1968 N5: the word for a probe the code critic could not judge
    runs = _terminal_runs(task_root)
    reviewed = _reviewed_identity(task_root, str(reviewer.get("id") or ""))
    # Once per build, read-only: the tests of this scope changed after their red run (t-108).
    changes, changes_unmeasured = owed_changes(task_root, scope, manifest)

    scope_instances: dict = {case: [] for case in scope}
    instances: list = []
    in_scope: list = []
    for entry in C.manifest_tests(manifest):
        links = [case for case in C.manifest_test_links(entry) if case in scope_instances]
        if not links:
            continue
        identity = C.test_instance_id(entry)
        for case in links:
            if identity not in scope_instances[case]:
                scope_instances[case].append(identity)
        in_scope.append(identity)
    # Which of those the STAND blocked (t-219, B1): the ONE reader `acceptance.blocked_instances`, asked after
    # `scope_instances` is complete (it counts how many instances a case has) and before any item is built (the
    # outcome decides whether a probe is owed). What it turned down is printed by `verdict`, with its repair.
    refusals: list = []
    blocked = blocked_instances(manifest, [{"instance_id": i} for i in in_scope], scope_instances, task_root,
                                runs, refusals)
    for kind, key, sentence in refusals:
        if kind == "ambiguous" or key not in blocked:  # `ambiguous` is keyed by the CASE, the rest by instance
            notes.append(("" if kind == "ambiguous" else key, "blocked:" + kind, sentence))
    # Which of the rest are written and never run because their side does not exist yet (t-2181 PC-4, C5): the ONE reader
    # `acceptance.pending_instances`, read beside `blocked_instances`, with the story's sides (`contract.story_sides`). A probe
    # is owed by every instance that could run; the excuse is this reader's alone, never the author's word, and an instance
    # on a substituted or real side is not in it - it runs, so its probe is owed exactly as before.
    # A terminal run outranks the excuse (the handed rule above): an instance that did run owes its probe.
    pending = pending_instances(manifest, [{"instance_id": i} for i in in_scope if i not in blocked and i not in runs],
                                scope_instances, C.story_sides(pipeline))
    # Which of the rest are RED by the requirement (HF2-4, F3/F7): the ONE reader `acceptance.red_by_requirement`
    # (AR-13), v-b - the latest terminal run of the instance is `failed` AND a `contradicts_requirement` row of the
    # manifest names it - asked once, after the blocked ones are known (an instance the stand blocked is never red: the
    # order of the classification is handed -> stopped -> red) and before any item is built. The instances it turned
    # down - a run that failed against a row about another instance, partition or Then - come back as notes `red:<kind>`
    # that `verdict` prints with the repair; a green or unrun neighbour gets none.
    red_refusals: list = []
    red = red_by_requirement(manifest, [{"instance_id": i} for i in in_scope if i not in blocked], scope_instances,
                             task_root, runs, red_refusals)
    for kind, key, sentence in red_refusals:
        notes.append((key, "red:" + kind, sentence))
    # Which of the rest the PERSON runs (B-375): the ONE reader `acceptance.handed_instances`. A run outranks the hand-off
    # (the precedence of the item below), so the decision is asked ONLY about instances with no terminal run; a stale
    # `handed_to_person` row beside a run is a note (`handed:ran`, info, like `blocked:stale`) and never a problem line.
    unrun = [{"instance_id": i} for i in in_scope if i not in blocked and i not in runs]
    handed_refusals: list = []
    handed_ok = handed_instances(manifest, unrun, scope_instances, task_root, runs, handed_refusals)
    for kind, key, sentence in handed_refusals:
        notes.append((key, "handed:" + kind, sentence))
    stale_rows: list = []   # asked of the instances that ran: the reader answers only `ran` for them
    handed_instances(manifest, [{"instance_id": i} for i in in_scope if i not in blocked and i in runs],
                     scope_instances, task_root, runs, stale_rows)
    for _kind, key, sentence in stale_rows:
        notes.append((key, "handed:ran", sentence))
    blocked_list: list = []
    for entry in C.manifest_tests(manifest):
        links = [case for case in C.manifest_test_links(entry) if case in scope_instances]
        if not links:
            continue
        identity = C.test_instance_id(entry)
        refs = [r for r in entry.get("obligation_refs") or [] if isinstance(r, dict)]
        # The test this instance holds NOW, from the one reader (`proof_level.instance_identity`): the
        # raw sha256 of the test file, the code sha of those same bytes and, when the story's author
        # run says which function this is, the per-test identity - all from ONE read, so shas of
        # different bytes are never stored side by side. The review and the probe are checked against
        # them (`same_test`). The row's `trace_binding` is what the author CLAIMED; a claim that drifted
        # from the file is exactly what the window must not take on trust.
        measured = proof_level.instance_identity(entry, task_root)
        item = {
            "schema_version": 2, "instance_id": identity,
            "input_hash": measured["input_hash"],
            "obligation_refs": refs,
            "obligation_ids": [str(r.get("obligation_id") or "") for r in refs],
            "obligation_hash": content_hash(refs) if refs else "",
            # the automator's own words, by the names the carrier lists (`REQUIRED_ROW_FIELDS`, window=True)
            **{field: str(entry.get(field) or "") for field in window_text_fields()},
            # A review is bound to what its reviewer saw: copied from the immutable review receipt (raw
            # bytes, code sha and per-test identity as it recorded them), never computed. With no receipt
            # the claim stands as it always did - the raw bytes the row is bound to, and nothing else.
            "review": {"verdict": str(entry.get("critic_verdict") or ""),
                       **(reviewed.get(identity) or {"input_hash": proof_level.claimed_test_sha(entry)})},
        }
        if measured["test_code_sha"]:
            item["test_code_sha"] = measured["test_code_sha"]
        if measured["instance_identity"]:
            item["instance_identity"] = measured["instance_identity"]
        elif measured["why"] in proof_level.MEASUREMENT and measured["input_hash"]:
            # No per-test identity because the MEASUREMENT failed, not because nothing was measured:
            # `same_test` must be able to tell, or a proof that had an identity would be kept by raw
            # equality of a file whose helpers changed.
            item["instance_identity_why"] = measured["why"]
        # The row's novelty, RESOLVED now - the moment the window binds its `input_hash` (t-134 R8). A row
        # that carries the key gives the item the value `proof_level.novelty_of` reads from it: a row-form
        # `unchanged` is re-hashed here, once, and a stale one is stored as `unknown`; the item form
        # (`resolved: true`, neither `measured_on` nor `measured_by`) is what `acceptance` then reads
        # through `proof_required(item, {})`, so a later edit of a measured file can never make the
        # value `unchanged` again inside this window (a window is immutable once built). A legacy row (no
        # key) gets NO key: acceptance keeps today's rule for it. The project root is the one
        # `instance_identity` above reads the test from (`proof_level._project()`), so both measure the
        # same tree; an unresolvable root makes a row-form `unchanged` read `unknown` (FR-41), never raise.
        if "novelty" in entry:
            value, basis = proof_level.novelty_of(entry)
            if value is not None:
                item["novelty"] = {"value": value, "basis": basis, "resolved": True}
        # A field no artifact gave is LEFT OUT, never filled with an empty string:
        # `contract.window_shape_errors` then says "<instance>: <field> is missing" and the
        # verdict names the artifact under it. An invented placeholder would read as a value.
        for field in ("input_hash", "obligation_refs", "obligation_ids", "obligation_hash", *window_text_fields()):
            if not item[field]:
                del item[field]
                if field in ORIGIN:
                    notes.append((identity, field, _origin_text(field)))
        stopped = identity in blocked
        if stopped:
            # A test the stand blocked is reviewed statically: its verdict is `unverified`, and anything
            # else on a test that never ran is a review gap (E5). Said in the review's own note.
            if item["review"]["verdict"] != BLOCKED_REVIEW_VERDICT:
                said = item["review"]["verdict"]
                notes.append((identity, "review",
                              (f"the manifest row's `critic_verdict` is `{said}`" if said
                               else "the manifest row carries no `critic_verdict`")
                              + f", and this instance was blocked by the stand; the verdict of such an instance "
                              f"is `{BLOCKED_REVIEW_VERDICT}` (a static review): the critic records it through "
                              "`manifest_put.py`"))
        elif item["review"]["verdict"] != "approved":
            notes.append((identity, "review", _origin_text("review")))
        if not item["review"]["verdict"]:
            del item["review"]
        run = runs.get(identity)
        if stopped:
            # No outcome of a run is claimed, and no fingerprint is invented: nothing reached a verdict (B2).
            # The run that did happen - a red that stood on the stand's own page - stays cited and is never
            # deleted (E4: code does not judge stand against product; the critic's `unverified` does).
            item["outcome"] = BLOCKED_OUTCOME
            item["execution_fingerprint"] = ""
            item["evidence_refs"] = _run_evidence(task_root, run[1], run[2]) if run else []
            blocked_list.append(_blocked_entry(task_root, identity, links, blocked[identity], run))
        elif run:
            row, block, path = run
            item["outcome"] = C.result_status(row)
            item["execution_fingerprint"] = str(row.get("input_fingerprint")
                                                or block.get("input_fingerprint") or "")
            item["evidence_refs"] = _run_evidence(task_root, block, path)
            # What THIS test was when it ran (HF2-11): the run row's per-test shas, copied, never computed, and only
            # when the row has both - a run that recorded none leaves the key out, because an empty placeholder would
            # read as a value (FR-59). `acceptance.validate_window` compares it with `instance_identity` above.
            identity_of_run = proof_level.run_identity(row)
            if identity_of_run:
                item["run_identity"] = identity_of_run
        elif identity in handed_ok:
            # The person runs this profile; there is no run here and inventing a fingerprint
            # would be the window claiming an execution nobody did (TP2-2536). The
            # field is present and empty on purpose — the controller exempts exactly this
            # outcome from it, and an absent key would be a shape error instead.
            item.update({"outcome": HANDED_OUTCOME, "execution_fingerprint": "", "evidence_refs": []})
        elif identity in pending:
            # The test is written and collected and cannot run: its side does not exist yet (t-2181 PC-4, B2). Same shape as the
            # handed item - the outcome is the excuse's own word, the fingerprint present and empty on purpose (a run nobody
            # made has none), no evidence to cite. `acceptance.validate_window` re-derives the claim by the same reader.
            item.update({"outcome": PENDING_OUTCOME, "execution_fingerprint": "", "evidence_refs": []})
        else:
            item["evidence_refs"] = []
            notes.append((identity, "outcome", _origin_text("outcome")))
            notes.append((identity, "execution_fingerprint", _origin_text("execution_fingerprint")))
        # The row's own `sensitivity_proof.receipt_ref` first (what `probe_by_code.py` and
        # `red_sandbox.py` both publish and delivery reads), the obligation binding as the
        # fallback: the window used to read the binding alone, so a receipt that reached only the
        # row left the window without a probe.
        # A red instance a manifest row explains is judged by S7, not probed (F-20 (a)): the order of the asserts decides
        # what a mutated run of a red test would fail at, so a receipt on it proves nothing and is NOT taken - it stays
        # on disk (FR-18: a measurement of another outcome never closes this window). Position: after handed and stopped
        # (an item that never ran is never red: `red` holds only instances whose latest terminal run FAILED).
        explained = identity in red and item.get("outcome") == "failed"
        ref = {} if (stopped or explained or identity in pending) \
            else _window_receipt_ref(entry, manifest, task_root)  # no probe of a test that never ran
        if explained:
            # The block is written exactly where a probe would otherwise be owed (the shape check's reading or the
            # validator's): a red `unchanged` test owes none and gets none. It carries EVERY row that names the
            # instance, in the manifest's order (N1): the window does not pick the guilty case.
            if proof_level.proof_required(entry, manifest) or item.get("change_disposition") == "new_or_changed":
                item[C.PROBE_NOT_APPLICABLE_KEY] = {"why": C.PROBE_NOT_APPLICABLE_WHY[0],
                                                    "reason": C.PROBE_NOT_APPLICABLE_REASON,
                                                    "rows": [_red_row_record(row) for row in red[identity]]}
        elif ref:
            receipt = _load(task_root / ref["path"])
            item["probe"] = _probe_from_receipt(receipt, ref, item, task_root)
            off_target = off_target_note(identity, item["probe"])
            if off_target:
                notes.append(off_target)       # the door of the gap `acceptance.validate_window` raises for it (N4)
            scoped = _scope_note(identity, item["probe"], ref)
            if scoped:
                notes.append(scoped)           # the door of the `sensitivity:` gap a one-check or a changed-model receipt raises (P6)
            if not any(e.get("path") == ref["path"] for e in item["evidence_refs"]):
                item["evidence_refs"].append({"path": ref["path"], "sha256": ref["sha256"]})
            # The probe's own evidence (the run summary of its mutated run) is not among the
            # instance's evidence, and `acceptance` wants the probe's `evidence_ref` to be: the
            # receipt is the hashed evidence the window can vouch for, so the probe points at it.
            paths = {e.get("path") for e in item["evidence_refs"]}
            if item["probe"].get("evidence_ref") not in paths:
                item["probe"]["evidence_ref"] = ref["path"]
        elif (proof_level.proof_required(entry, manifest)
              and item.get("outcome") not in (HANDED_OUTCOME, BLOCKED_OUTCOME) and identity not in pending):
            # HF1-14 (E13): AFTER the receipt lookup (a proof outranks an accepted gap, E9) and only for an instance
            # that ran green and owes a live check (E6: a word never turns a red or an unrun test into a passed
            # window). Written only when a recorded word names it (F6): without one nothing changes.
            gap = (probe_gap_block(task_root, item, links, probe_gap_words,
                                   C.probe_gap_class_word(pipeline, [identity] + list(links)), not_proved_words)
                   if item.get("outcome") == "passed" else None)
            if gap:
                item["probe_gap"] = gap
                if item.get("review", {}).get("verdict") != BLOCKED_REVIEW_VERDICT:
                    # the review of an instance whose probe never ran is the critic's static word (F5)
                    said = item.get("review", {}).get("verdict")
                    notes[:] = [n for n in notes if not (n[0] == identity and n[1] == "review")]
                    notes.append((identity, "review",
                                  (f"the manifest row's `critic_verdict` is `{said}`" if said
                                   else "the manifest row carries no `critic_verdict`")
                                  + f", and this instance's probe could not run here (a person's word or the factory names it); the "
                                  f"verdict of such an instance is `{BLOCKED_REVIEW_VERDICT}` (a static review): "
                                  "the critic records it through `manifest_put.py`"))
            elif item.get("outcome") == "failed":
                # A red no row explains (HF2-4, A1): the critic's probe closes nothing on it and the person's word
                # `probe gap` is not read for a red (FR-18) - both doors were dead ends. The road is the row.
                notes.append((identity, "probe", ORIGIN["probe"][0] + "; " + RED_ROW_DOOR))
            elif proof_level.probe_plain_call_owed(task_root, identity, str(item.get("input_hash") or "")):
                # fix round D (B2, the first critic's routing note): a walk's aggregate in which no check owes a judgment (rows `--at` did not
                # select, a check with no model yet): `--judge` would refuse; the door is the plain call that walks the rest
                notes.append((identity, "probe", _keys_first(task_root, item) + PLAIN_CALL_NOTE + PROBE_DOOR))
            elif proof_level.probe_owes_judgment(task_root, identity, str(item.get("input_hash") or "")) == "unjudged":
                # t-1968 N2 (R4): the probe ran and failed at its line on a text the tool cannot read; the door is the critic's
                # `--judge`, not a person's word. No new refusal: it is the tail of the same `probe is missing` line
                import probe_by_code      # the ONE JUDGE_DOOR (AR-13); lazy: this module is imported by many that never probe
                notes.append((identity, "probe", _keys_first(task_root, item) + UNJUDGED_NOTE + probe_by_code.JUDGE_DOOR))
            elif proof_level.probe_owes_judgment(task_root, identity, str(item.get("input_hash") or "")) == "cannot_judge":
                # t-1968 N5: the code critic judged and could not tell; the door is the person's own word, not a `probe gap:` one
                notes.append((identity, "probe", _keys_first(task_root, item) + NOT_PROVED_NOTE))
            else:
                notes.append((identity, "probe", _keys_first(task_root, item) + _origin_text("probe") + PROBE_GAP_DOOR))
        if (not item["evidence_refs"] and not stopped and item.get("outcome") not in (HANDED_OUTCOME, PENDING_OUTCOME)):
            # a blocked test that never ran, and one the person runs, have no run to cite
            notes.append((identity, "evidence", _origin_text("evidence_refs")))
        instances.append(item)

    for case, found in scope_instances.items():
        if not found:
            if case in handed or (C.split_case_key(case)[1] or case) in handed:
                notes.append((case, "scope_instances",
                              "carried by the manifest as handed_to_person: the person runs it"))
                continue
            notes.append((case, "scope_instances",
                          "no `tests[]` row of work/automation-manifest.json covers this case"))
    # `required_quality_checks` are recorded at `initialize`; only the ones a factory script produces a receipt for
    # (`references/quality-receipt-producers.json`) are demanded here (FR-5) - the rest go to `quality_not_run`, which the
    # report prints (FR-4/FR-59). The filter stands BEFORE any `str()` of an id: an id that is no string stays demanded.
    required, quality_not_run, _why = demanded_quality_checks(state.get("required_quality_checks"), task_root)
    window = {"schema_version": 2,
              "author_dispatch_id": str(author.get("id") or ""),
              "reviewer_dispatch_id": str(reviewer.get("id") or ""),
              "input_hash": str(dispatch.get("input_hash") or ""),
              "source_revision": str(state.get("source_revision") or ""),
              "scope_instances": scope_instances, "instances": instances,
              "required_quality_checks": required, "quality_receipts": [],
              # ALWAYS written, `[]` when every recorded check is demanded or none was recorded (AR-23)
              "quality_not_run": quality_not_run,
              # ALWAYS written, an empty list when nothing is owed: a window built after this change
              # carries the key, and only a window without it is read as legacy (`acceptance`).
              "expectation_changes": changes,
              # ALWAYS written too, `[]` when the stand blocked nothing (t-219, B2): the instances the stand
              # blocked, each with what stopped it and the fix, so the person at gate B and the next reader
              # of the window read one list. A record without the key (an older build) reads as `[]` (E13).
              "blocked_by_env": blocked_list}
    if changes_unmeasured:
        # next to the list, and NOT a gap: the story goes on and `verdict` says it was not measured
        window["expectation_changes_unmeasured"] = changes_unmeasured
    if role == "qa-automator" and str(dispatch.get("repair_cause") or "") == "mechanical" and reviewer:
        bound = sorted({r["input_hash"] for r in reviewed.values() if r.get("input_hash")})
        window["mechanical_round"] = {
            "author_dispatch_id": str(dispatch.get("id") or ""),
            "reviewer_dispatch_id": str(reviewer.get("id") or ""),
            "reviewed_input_hash": bound[0] if len(bound) == 1 else str(reviewer.get("input_hash") or "")}
    return window, notes


def _explain_parts(line: str, notes: list) -> tuple:
    """`(what was missing, the door)` of a printed error - ("", "") when this script has nothing truer to say
    than the error itself. A note's sentence is one string, `<missing>; <door>`; it is split at its first `; `."""
    kind, _, tail = line.partition(":")
    for identity, field, sentence in notes:
        named = (field in line or field == kind.strip() or field == tail.strip())
        if named and (not identity or identity in line):
            missing, sep, door = sentence.partition("; ")
            return (missing, door) if sep else ("", sentence)
    origin = GAP_ORIGIN.get(kind.strip()) or GAP_ORIGIN.get(line.strip())
    if kind.strip() == "quality":
        # HF4-10: a quality gap exists only for a check a script produces; the door names THAT script (FR-2), from data
        script = _quality_data()[0].get(tail.strip())
        if script:
            origin = (f"no receipt of the quality check `{tail.strip()}` is in the window",
                      f"run `{script}` for it; or record the person's word with "
                      "`waiver.py --stage S5 --block \"not receipted\"`")
    if origin is None:
        for field, entry in ORIGIN.items():
            if field in line:
                origin = entry
                break
    if origin is None:
        return "", ""
    return origin[0], origin[1]


def _explain(line: str, notes: list) -> str:
    """The artifact a printed error came from, and the command that fills it — "" when this
    script has nothing truer to say than the error itself."""
    missing, door = _explain_parts(line, notes)
    return (missing + "; " + door) if (missing and door) else (door or missing)


# The gap kinds a person's recorded word is READ for on the road that completes S5 (`controller.py` accept): the
# `quality` check names `waiver.py --block "not receipted"`, and a pair changed after its red run is passed by
# the pair's own word (`s5_precheck.passed_by_word`; kinds `expectation_change*`, found through `owners` below), and
# (HF1-14) a `probe_gap` line, which `build` writes ONLY when a word of the person names the instance, so the word
# WAS read (`acceptance.probe_gap_named`). `probe_gap_unrecorded` is not here: no word names it.
# Every OTHER line of a window verdict is read by nothing a person's word reaches - the controller reads a word
# for the critic's receipts and for a missing window record, never for a gap of the window - so a word recorded
# against one is printed "recorded, not read by this window" (`_unread_words`). One name, so a reader added later
# is one line here (Q7 B', t-299).
WORD_READ_KINDS = ("quality", PROBE_GAP_KIND)
NO_DOOR = "repair the artifact the line names; no recorded word is read for it"


def _unread_words(task_root: Path, unread: list, info: list) -> None:
    """One info line per (word, door) for every S5 `stage_overrides` word whose `match` is whole words (`contract.names_whole`) of a line
    in `unread` - `[(line, its door)]`, the problem lines no reader passes - saying so and naming that line's own
    door (the repair its line already names; `NO_DOOR` when the line names none).

    REPORTING ONLY (S9): it reads `pipeline.json`, appends to `info` and never changes a problem line or the
    exit code, so a person's word is never dropped in silence and never passes a gap nobody reads it for (S8).
    The matching is `waiver.split_overridden`'s own - whole words, `*` matches everything, a revoked word is
    history - used here only to ask "would this word have matched this line?". The words are printed whole (a
    person's words are carried in full, FR-8), whitespace folded. A record that cannot be read says nothing."""
    try:
        from waiver import split_overridden
        pipeline = _load(task_root / "pipeline.json")
        seen = set()
        for line, line_door in unread:
            _blocking, passed = split_overridden([line], pipeline, "S5")
            for hit in passed:
                words = " ".join(str(hit.get("decision") or "").split())
                door = line_door or NO_DOOR
                if (words, door) not in seen:
                    seen.add((words, door))
                    info.append(f"recorded, not read by this window: {words} — {door}")
    except Exception:
        return


def _comment_only(window: dict, info: list) -> None:
    """One line per review or probe that still stands only because the change since it was made left
    the CODE of the test the same (`same_test` says `instance_code` or `file_code`, D-0017): the
    window is fine, and the reader is told which proof it rests on rather than left to assume raw
    equality (FR-41). A proof kept by equal bytes, or by the same test after another test's edit, says
    nothing. Read through the one predicate, never a second rule."""
    for item in window.get("instances") or []:
        if not isinstance(item, dict):
            continue
        now = proof_level.proof_identity(item)
        parts = [("review", item.get("review"))]
        if proof_level.proof_required(item, {}) and item.get("outcome") not in (HANDED_OUTCOME, BLOCKED_OUTCOME):
            parts.append(("probe", item.get("probe")))
        for name, proof in parts:
            how = proof_level.same_test(now, proof_level.proof_identity(proof)) if isinstance(proof, dict) else ""
            if proof_level.held_words(how):  # the words follow the `same_test` answer (FB-10, R8)
                info.append(f"{item.get('instance_id')}: the {name} holds; {proof_level.held_words(how)}")


def _run_freshness_unknown(window: dict, info: list) -> None:
    """One line per instance that RAN and whose run freshness could not be measured (HF2-11): not a gap - the
    story goes on and today's reading of the run stands - and not silence either, because "unknown" read as "fresh"
    is the error this check exists for (FR-41, FR-59). The state comes from `acceptance.run_freshness_of`, the same
    call `validate_window` makes. A handed or blocked instance ran nothing here and is not asked."""
    for item in window.get("instances") or []:
        if not isinstance(item, dict) or item.get("outcome") not in ("passed", "failed"):
            continue
        state, why = run_freshness_of(item)
        if state == "unknown":
            # The instance goes LAST: a line that starts with `<iid>:` is a proof note (`_comment_only`), and the readers
            # of `info` (test_probe_binding.py) pick those by that start.
            info.append(f"run freshness not measured: {why} ({item.get('instance_id')})")


def _reason_detail_notes(window: dict, info: list) -> None:
    """One line per probe whose reason matched on the failure's first line only (B-380): the lines of the failure that were
    not compared, from the record's own `probe.reason_detail` through `reporters.reason_detail_line`. Not a problem and
    never a gap; an older record without the block says nothing (FR-41: absent is not recorded, not "matched whole")."""
    for item in window.get("instances") or []:
        if isinstance(item, dict) and isinstance(item.get("probe"), dict):
            line = reporters.reason_detail_line(item["probe"], item.get("instance_id"))
            if line:
                info.append(line)


def verdict(task_root: Path, window: dict, notes: list, info: list | None = None) -> list:
    """Every structural error and every semantic gap, at once, each with its artifact.

    `info`, when given, receives the notes that are NOT problems: a review or a probe that holds with the test's
    code unchanged (a comment-only change or an added test, `_comment_only`), a run whose freshness was not measured (`_run_freshness_unknown`). The
    return - the problem lines - is unchanged."""
    if info is not None:
        try:
            _comment_only(window, info)
        except proof_level.LevelsUnavailable:
            pass  # said below, once, with the file and the door
        _run_freshness_unknown(window, info)
        _reason_detail_notes(window, info)
        _unknown_target_notes(window, info)
        _probe_scope_notes(window, info)
        if "expectation_changes_unmeasured" in window:
            # Not a problem and not a gap: the detector could not measure, the story goes on, and the
            # reader is told what was NOT looked at instead of assuming nothing changed (FR-41).
            why = str(window["expectation_changes_unmeasured"] or "").strip() or "no reason was recorded"
            info.append("expectation changes " + (change_word("not_measured", why=why)
                                                  or "not measured: " + why))
        listed = window.get("expectation_changes")
        for item in listed if isinstance(listed, list) else []:
            if isinstance(item, dict) and item.get("passed_by_word") is True \
                    and not str(item.get("critic_verdict") or "").strip():
                # visible, never silently dropped: the pair stays in the list and is said here too
                info.append(f"{item.get('function') or '?'}: "
                            + (change_word("not_recorded_passed_by_word") or "not recorded, passed by a person's word")
                            + " - no verdict is owed for it")
    shape = C.window_shape_errors(window)
    lines = [f"{e} — {_explain(e, notes)}".rstrip(" —") for e in shape]
    doors = {line: _explain_parts(e, notes)[1] for line, e in zip(lines, shape)}   # line -> its own door
    try:
        gaps = validate_window(window, task_root)
    except proof_level.LevelsUnavailable as exc:
        # The plugin's own file is gone; that is not a shape problem of this record, and the
        # message already names the door.
        gaps = []
        lines.append(str(exc))
    except ValueError as exc:
        gaps = []
        lines.append(f"{exc} — the record always carries an explicit list, even an empty one")
    owners = dict(expectation_change_gaps(window))  # gap -> its kind, from the one function that made it
    read = set()          # the lines a person's recorded word is read for (S7 of t-299: `_unread_words` skips them)
    for gap in gaps:
        if gap in owners:
            # By the gap's own kind, never by a search of the line: a function named `test_review_x`
            # must not be explained as a missing review.
            missing, command = change_origin(owners[gap])
            lines.append(f"{gap} — {missing}; {command}")
            read.add(lines[-1])
            continue
        line = f"{gap} — {_explain(gap, notes)}".rstrip(" —")
        kind, _, identity = gap.partition(":")
        door = _explain_parts(gap, notes)[1]
        if kind == "sensitivity":
            # The byte reason, when there is one (FR-41): the probe is bound to other bytes and the
            # test's code (or its per-test identity) is not the same as when it was measured.
            item = next((i for i in window.get("instances") or [] if i.get("instance_id") == identity), {})
            bound, now = str((item.get("probe") or {}).get("input_hash") or ""), str(item.get("input_hash") or "")
            if bound and now and bound != now:
                line += (f" (the probe is bound to sha256 {bound}, the test now holds {now}, and its code "
                         "differs or was not measured: a probe of the current bytes is due)")
        if kind == "mechanical_green":
            # What exactly is missing for the author's green run to count (FR-41), from the one check.
            item = next((i for i in window.get("instances") or [] if i.get("instance_id") == identity), {})
            why = green_on_current_bytes_why(item, window, task_root)[1]
            if why:
                line += f" ({why})"
        if kind == "stale_run":
            # The `{why}` of the origin sentence: what the one predicate said, asked of the same item.
            item = next((i for i in window.get("instances") or [] if i.get("instance_id") == identity), {})
            line = line.replace("{why}", run_freshness_of(item)[1])
        lines.append(line)
        doors[line] = door
        if kind in WORD_READ_KINDS:
            read.add(line)
    # What `acceptance.blocked_instances` turned down, said once each with its repair (t-219, E1/E2/E7): an
    # instance whose blocked_by_env row has no remedy (or a remedy that is not one), or whose row names no
    # instance on a case with several, is NOT blocked, and the gap above ("product:...") alone would send the
    # critic to the product. A stale row (a passed run on the current bytes, E3) blocks nothing and breaks
    # nothing: it is a note, and `s5_precheck` names the repair.
    # The same for what `red_by_requirement` turned down (HF2-4, F7): a red run no `contradicts_requirement` row explains
    # (`red:<kind>` notes), each with its one road.
    # B-375: the same for `handed:<kind>` (`acceptance.handed_instances`): `partial` is a problem with its repair; `ran` - a
    # handed_to_person row left beside a run, whose outcome stands - is information, like `blocked:stale`.
    for _identity, field, sentence in notes:
        if not field.startswith(("blocked:", "red:", "handed:")):
            continue
        if field in ("blocked:stale", "handed:ran"):
            if info is not None:
                info.append(sentence)
        else:
            lines.append(sentence)
            doors[sentence] = sentence       # the sentence says what to repair and with which command
    if info is not None:
        _unread_words(task_root, [(line, doors.get(line, "")) for line in lines if line not in read], info)
    return lines


def receipt_dict(window: dict) -> dict:
    """The review receipt a window is receipted as: pure, nothing read and nothing written.

    `write_review_receipt` writes exactly this, and `coverage_contract.witnessed_binding` rebuilds it from
    the accepted window to read a `review_receipt_ref` that names the receipt: ONE definition of the
    receipt, so the writer and the reader cannot drift (t-238: the reader asked a receipt to equal the
    window, and every binding published through `--review-receipt` read "not witnessed")."""
    receipt = {"schema_version": 2, "receipt_kind": "s5_review_window", "immutable": True,
               "reviewer_dispatch_id": window.get("reviewer_dispatch_id"),
               "author_dispatch_id": window.get("author_dispatch_id"),
               "input_hash": window.get("input_hash"),
               "scope_instances": window.get("scope_instances"),
               "required_quality_checks": window.get("required_quality_checks"),
               "quality_receipts": window.get("quality_receipts"),
               "instances": [dict(item, assertion_refs=[item["assertion_id"]] if item.get("assertion_id") else [])
                             for item in window.get("instances") or []]}
    # `quality_not_run` is deliberately NOT here: it depends on the S0 readiness record at the time of the build, and an
    # immutable receipt must not collide when the record changes between two builds of the same window; the report reads it
    # from the window files.
    receipt["receipt_hash"] = content_hash(receipt)
    return receipt


def write_review_receipt(task_root: Path, window: dict, reviewer_id: str) -> dict:
    """The immutable S5 review receipt, and its task-relative ref.

    `references/artifact-contract-automation.md` describes the shape: the accepted window's
    instances with their obligations, dispositions, evidence and probe. It is written once —
    a second call with different content is a collision, not an update, exactly as a
    sensitivity receipt is.
    """
    directory = task_root / REVIEW_RECEIPT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (_safe_name(reviewer_id) + ".json")
    receipt = receipt_dict(window)
    if path.is_file() and _load(path) != receipt:
        same = _per_test_difference(_load(path), receipt)
        if same == "copy":
            # The same window again: once the receipt exists, a review copies what it recorded (the
            # per-test fields of its own instance), so the second build differs from the first receipt
            # by exactly that copy. The old file is the receipt, and it is never rewritten.
            return {"path": path.relative_to(task_root).as_posix(), "sha256": _digest(path)}
        if same == "legacy":
            # The same window, receipted before instances carried a per-test identity: the fields this
            # receipt would add are exactly what the old file could not have had, so it is no
            # collision, and the old file - immutable - is never rewritten. It binds raw bytes, and
            # the review of a test that still has them stays valid the way it always was.
            return {"path": path.relative_to(task_root).as_posix(), "sha256": _digest(path),
                    "note": "the review receipt predates per-test binding: it binds raw bytes"}
        raise ValueError(f"immutable review receipt collision at {path.relative_to(task_root).as_posix()}: "
                         "this window was already receipted with different content; a changed "
                         "window is a new critic dispatch, not a rewritten receipt. "
                         f"{REPAIR_MARKER}: dispatch the critic again over the changed window.")
    atomic_json(path, receipt)
    return {"path": path.relative_to(task_root).as_posix(), "sha256": _digest(path)}


# What per-test binding (t-043 C) adds to an instance of a window, and to the review and the probe in it.
_PER_TEST_FIELDS = ("test_code_sha", "instance_identity", "instance_identity_why")


def _per_test_difference(found: dict, receipt: dict) -> str:
    """Is the receipt already on disk the same receipt as `receipt`, apart from what per-test binding adds?

    "copy": it equals `receipt` once the per-test fields the REVIEW of each instance copies from the
    receipt are taken out of the new one - the second build of a window that was receipted by the first;
    "legacy": it equals `receipt` once every per-test field is taken out of the new one - written before
    those fields existed; "": anything else, a real collision. The hash is recomputed over what is left,
    the way it was written.

    B-380: the same comparisons are tried once more with `probe.reason_detail` taken out of the NEW receipt's probes - a
    receipt written by 0.10.8 has no such field, and the review receipt is immutable, so the field must not make a rebuild
    of an in-flight story a collision. The word returned is the reduction's own; anything else that differs still raises."""
    if not isinstance(found, dict) or not found:
        return ""

    def reduced(nested_keys: tuple, item_level: bool, drop_detail: bool = False) -> dict:
        old = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        instances = []
        for item in old.get("instances") or []:
            if not isinstance(item, dict):
                instances.append(item)
                continue
            kept = ({key: value for key, value in item.items() if key not in _PER_TEST_FIELDS}
                    if item_level else dict(item))
            for nested in nested_keys:
                if isinstance(kept.get(nested), dict):
                    kept[nested] = {key: value for key, value in kept[nested].items() if key not in _PER_TEST_FIELDS}
            if drop_detail and isinstance(kept.get("probe"), dict):
                kept["probe"] = {key: value for key, value in kept["probe"].items() if key != "reason_detail"}
            instances.append(kept)
        old["instances"] = instances
        old["receipt_hash"] = content_hash(old)
        return old
    for drop_detail in (False, True):
        if found == reduced(("review",), False, drop_detail):
            return "copy"
        if found == reduced(("review", "probe"), True, drop_detail):
            return "legacy"
    return ""


def publish_review_receipt(task_root: Path, task: str, window: dict, ref: dict) -> str:
    """Put `review_receipt_ref` on every obligation binding this window reaches — through
    `manifest_put.py` as a subprocess, the way `red_sandbox.probe` publishes the sensitivity
    proof. Nothing writes `automation-manifest.json` directly (TP2-2104)."""
    reached = []
    for item in window.get("instances") or []:
        for oid in item.get("obligation_ids") or []:
            if oid and oid not in reached:
                reached.append(oid)
    if not reached:
        return "no obligation ids in the window: nothing to bind the review receipt to"
    # The fragment is scratch, not an artifact: it never lands in the story's own folder,
    # where a guard and every later reader would treat it as one.
    scratch = Path(tempfile.mkdtemp(prefix="qa-review-receipt-"))
    fragment = scratch / "manifest-fragment.json"
    atomic_json(fragment, {"obligation_bindings": [{"obligation_id": oid, "review_receipt_ref": ref["path"]}
                                                   for oid in reached]})
    try:
        put = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve().parent / "manifest_put.py"),
             "--task", task, "--fragment", str(fragment)],
            cwd=str(task_root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    tail = (put.stdout or put.stderr or "").strip().splitlines()
    from manifest_put import outcome
    put_kind, move = outcome(put.returncode, task)
    if put_kind == "committed":
        return "manifest_put.py: " + (tail[0] if tail else "review_receipt_ref published on "
                                      + ", ".join(reached))
    said = (put.stderr or put.stdout or "").strip()[-500:]
    if put_kind == "stale":     # exit 4: the receipt IS in the journal, only the manifest's projection failed
        return (f"manifest_put.py committed the review receipt but the manifest's projection is stale - run "
                f"`{move}`: {said}")
    return "manifest_put.py refused the review receipt: " + said


def _handed_empty_cases(task_root: Path, window: dict) -> set:
    """The cases of the window's scope that list no instance and that the manifest carries as `handed_to_person`.
    The rule is the controller's own (`Controller._cases_without_instances`, EXACT scope keys - the same reader
    `story_step._handed_no_instance` goes through and `finish`/the S5 completion judge by), so this record never
    promises a pair that `finish` then refuses (t-827 FX-2). Anything unreadable is `set()`: nothing is accepted on a
    guess."""
    try:
        from controller import Controller
        found = Controller(task_root)._cases_without_instances()
        return {case for case, ids in (window.get("scope_instances") or {}).items()
                if not ids and found.get(case) == HANDED_OUTCOME}
    except Exception:
        return set()


def probe_gap_segments(window: dict, problems: list) -> list:
    """One segment per instance whose probe gap is named (a `probe_gap:` line of `problems`):
    `<iid> (<case>[, <case>]): probe <verdict>, <why>; their words: "<words>"`. The words are printed whole
    (a person's words are carried in full, FR-8); the instance is read from the item, never cut out of the line. The factory names no
    gap of its own (t-1968 N2): every gap here is a person's word. A gap named
    by the CLASS decision (`named_by` `class:...`, GW1-43) adds `; decision of <date>, applied to this test`: said where applied."""
    scope = window.get("scope_instances") if isinstance(window.get("scope_instances"), dict) else {}
    out = []
    for item in window.get("instances") or []:
        gap = item.get("probe_gap") if isinstance(item, dict) else None
        identity = str(item.get("instance_id") or "") if isinstance(item, dict) else ""
        line = f"{PROBE_GAP_KIND}:{identity}"
        if not isinstance(gap, dict) or not any(p == line or p.startswith(line + " — ") for p in problems):
            continue
        cases = ", ".join(str(c) for c, ids in scope.items() if isinstance(ids, list) and identity in ids)
        segment = f"{identity} ({cases}): probe {gap.get('verdict')}, {gap.get('why')}; their words: \"{gap.get('words')}\""
        if str(gap.get("named_by") or "").startswith("class:"):
            # GW1-43: the word was said about a class of tests; the person reads WHICH test it was applied to, and when it was said
            said = str(gap.get("at") or "")[:10]
            segment += (f"; decision of {said}, applied to this test" if said else "; decision, applied to this test")
        out.append(segment)
    return out


def _red_cases(item: dict) -> list:
    """The cases of the manifest rows an item records in its `probe_not_applicable` block, in the block's order (the
    manifest's, N1), without repeats; `[]` for an item without the block (a red `unchanged` test owes none)."""
    block = item.get(C.PROBE_NOT_APPLICABLE_KEY) if isinstance(item, dict) else None
    rows = block.get("rows") if isinstance(block, dict) else None
    return list(dict.fromkeys(str(r.get("case")) for r in rows if isinstance(r, dict) and r.get("case"))) \
        if isinstance(rows, list) else []


def _red_segments(window: dict, problems: list) -> list:
    """One segment per instance whose gap is `contradicts_requirement:<iid>` in `problems`: `<iid> (<cases of its
    rows>)`, the cases from the item's own block; the bare id when the item records none. The instance is read from the
    item, never cut out of the line."""
    out = []
    for item in window.get("instances") or []:
        identity = str(item.get("instance_id") or "") if isinstance(item, dict) else ""
        line = f"{CONTRADICTS_REQUIREMENT}:{identity}"
        if not identity or not any(p == line or p.startswith(line + " — ") for p in problems):
            continue
        cases = _red_cases(item)
        out.append(f"{identity} ({', '.join(cases)})" if cases else identity)
    return out


def _two_case_red_notes(window: dict) -> list:
    """A `note:` for every item red for the rows of two cases or more: not a problem (the window records both rows and
    closes), and not this script's to refuse - the S5 precheck is the one detector that asks the automator to keep one
    (3a2). Said here so the reader of the print is not left to find the second case in the record."""
    notes = []
    for item in window.get("instances") or []:
        cases = _red_cases(item)
        if len(cases) >= 2:
            notes.append(f"{item.get('instance_id')} is red for the rows of " + ", ".join(cases[:-1]) + f" and {cases[-1]}"
                         "; the S5 check asks to keep one")
    return notes


# Kinds acceptance.validate_window emits for an INSTANCE (acceptance.py: mechanical_green 892, PROBE_GAP_UNRECORDED_KIND
# 919, sensitivity 931, semantic_sensitivity 944, probe_level 951, probe_mutation_kind 953, probe_evidence 955).
# Record-shape kinds (malformed_instance, obligation_*, assertion_identity, defect_location, change_*) are left out on
# purpose: a rejected review does not explain a malformed record.
SENT_BACK_KINDS = ("review", "sensitivity", "semantic_sensitivity", "probe_level", "probe_mutation_kind",
                   "probe_evidence", PROBE_GAP_UNRECORDED_KIND, "mechanical_green", "product", "evidence",
                   "stale_run", "stale_review")


def _sent_back_lines(window: dict, problems: list) -> list:
    """The gap lines that belong to an instance whose review row says `rejected`: the critic sent that test back
    to its author, so it is not expected to be proved yet. Read structurally (the gap's kind before the first colon,
    the instance identity after it, the verdict from the window's own instances) - never by a search of the text."""
    rejected = {str(i.get("instance_id")) for i in window.get("instances") or []
                if isinstance(i, dict) and isinstance(i.get("review"), dict) and i["review"].get("verdict") == "rejected"}
    found = []
    for line in problems:
        # the ONE shape error that is a sent-back cause: a rejected instance has no probe yet (Lead, t-1603 fix round);
        # every other shape-error line stays a fall-through. The line may carry an " — explanation" tail.
        if any(line == f"{iid}: {C.PROBE_MISSING_ERROR}" or line.startswith(f"{iid}: {C.PROBE_MISSING_ERROR} — ")
               for iid in rejected):
            found.append(line)
            continue
        kind, _, rest = line.partition(":")
        if kind in SENT_BACK_KINDS and any(rest == iid or rest.startswith(iid + " ") for iid in rejected):
            found.append(line)
    return found


def run(task: str, dispatch_id: str, out: str = "", review_receipt: bool = False) -> int:
    require_project("window_record")
    task_root = artifacts_dir(task)
    if not task_root.is_dir():
        print(f"window_record: no story artifacts at {task_root} — name the ticket the "
              f"controller was initialized with. {REPAIR_MARKER}.", file=sys.stderr)
        return EXIT_BAD_ARGS
    window, notes = build(task_root, dispatch_id)
    path = Path(out) if out else task_root / WINDOW_DIR / (_safe_name(dispatch_id) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, window)
    shown = path.relative_to(task_root).as_posix() if path.is_relative_to(task_root) else str(path)
    print(f"window record: {shown} — {len(window['instances'])} instance(s), scope "
          + (", ".join(sorted(window["scope_instances"])) or "none"))
    info: list = []
    problems = verdict(task_root, window, notes, info)
    info.extend(_two_case_red_notes(window))
    for line in info:  # not problems: what a proof of this window rests on, said whether or not it is acceptable
        print("note: " + line)
    # t-219 (B4, Q7): when EVERY gap is an instance the stand blocked, the critic's work is finished - the window
    # is acceptable AS UNRESOLVED. Exit 0, not 1: with 1 the driver prints the marker note that sent the cmp2
    # critic round the loop eight times. Any other gap, the blocked lines among them, keeps today's exit 1.
    def receipt() -> None:
        ref = write_review_receipt(task_root, window, window.get("reviewer_dispatch_id") or dispatch_id)
        print("review receipt: " + ref["path"])
        if ref.get("note"):
            print("note: " + ref["note"])
        print(publish_review_receipt(task_root, task, window, ref))
    # t-721 (3.2): the person runs it - an instance handed to them, or a case with NO instance that the manifest
    # carries as `handed_to_person` (its `empty_scope` gap is covered only when EVERY case of the scope is such a
    # case). Such a window is as finished as one the stand blocked: `finish` derives the same kind of pair.
    handed_empty = _handed_empty_cases(task_root, window)
    scope_cases = set(window.get("scope_instances") or {})
    covered = bool(handed_empty) and scope_cases <= handed_empty

    def derivable(line: str) -> bool:
        return (line.startswith((BLOCKED_OUTCOME + ":", HANDED_OUTCOME + ":", PROBE_GAP_KIND + ":",
                                 CONTRADICTS_REQUIREMENT + ":"))
                or (covered and line.startswith("empty_scope")))
    if problems and all(derivable(line) for line in problems):
        listed = window.get("blocked_by_env") or []
        # HF2-4: a red the requirement contradicts is an OUTCOME the window carries, not a defect of it: S7 triages it.
        # The cases are those of the manifest rows the item records, in the manifest's order (N1).
        red_segments = _red_segments(window, problems)
        if red_segments:
            print(f"acceptable as unresolved: {len(red_segments)} red test(s) the requirement contradicts - "
                  "S7 triages them: " + "; ".join(red_segments))
        # O3 (P20, FR-10): a red that RAN is parked here too, and the line says so - `(ran red: <reason>)` after
        # the stand - so nobody reads "blocked" and takes the instance for one that never reached a verdict.
        if any(line.startswith(BLOCKED_OUTCOME + ":") for line in problems):
            print(f"acceptable as unresolved: {len(listed)} instance(s) blocked by the stand - "
                  + "; ".join(f"{b.get('instance_id')}: {(b.get('remedy') or {}).get('where')} on {b.get('stand')}"
                              + (f" ({red})" if (red := ran_red(b.get("last_run"))) else "")
                              for b in listed))
        accepted = probe_gap_segments(window, problems)
        if accepted:
            print(f"acceptable as unresolved: {len(accepted)} probe gap(s) named - " + "; ".join(accepted))
        runs = sorted(handed_empty) + [line.partition(":")[2].split(" ")[0] for line in problems
                                       if line.startswith(HANDED_OUTCOME + ":")]
        if runs:
            print(f"acceptable as unresolved: {len(runs)} instance(s) or case(s) the person runs - " + ", ".join(runs))
        if review_receipt:
            receipt()
        print(f"finish with: story_step.py finish --task {task} --dispatch-id {dispatch_id} --digest \"<digest>\" "
              "- it derives the `unresolved` pair from this record, nothing to type")
        return 0
    sent_back = _sent_back_lines(window, problems)
    if sent_back and all(derivable(line) or line in sent_back for line in problems):
        # t-1603: the critic's own word `rejected` sends the window back to its author. The receipt records the
        # review (finish needs it even for a send-back); the window is NOT acceptable: this branch never returns 0.
        rejected_ids = sorted({line.partition(":")[2].split(" ")[0] for line in sent_back} - {""})
        print("sent back to its author: the review rejected " + ", ".join(rejected_ids)
              + " - the receipt records the review; finish with --not-complete and the author's round follows")
        if review_receipt:
            receipt()
        for line in problems:
            print("  - " + line)
        print(f"{REPAIR_MARKER}. Where a person's word passes a gap, the line above says how.")
        return EXIT_REFUSED
    if problems:
        print("this window is NOT acceptable yet. Every gap at once, with the artifact it "
              "came from — repair the artifact, never this record:")
        for line in problems:
            print("  - " + line)
        # Every line above names the artifact its gap came from, so the work is a role's own
        # (P4b): on TP1-13797 a refusal that said as much in prose still reached the person,
        # because the driver routes on this marker and not on a wording.
        # No blanket promise that a person's word passes the window (Q7 B', t-299): on the rehearsal
        # (cmp2r, 02.10) the word `review is missing` was recorded, the line still said it passes, and
        # nothing read it. Each line above names its own door; where a word really passes a gap, that
        # line says how, and a word nothing reads is printed above as "recorded, not read by this window".
        print(f"{REPAIR_MARKER}. Where a person's word passes a gap, the line above says how.")
        return EXIT_REFUSED
    if review_receipt:
        receipt()
    print("the window is acceptable: no structural error, no semantic gap.")
    print(f"accept it with: controller.py --task-root {task_root} --operation accept "
          f"--input <completion.json> --window {shown}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", required=True, help="the story's ticket id")
    ap.add_argument("--dispatch", required=True,
                    help="the S5 dispatch whose acceptance carries the window (the critic's, "
                         "or the author's own on a mechanical round)")
    ap.add_argument("--out", help="write the record here instead of work/windows/<dispatch>.json")
    ap.add_argument("--review-receipt", action="store_true",
                    help="also write the immutable S5 review receipt and publish its path as "
                         "review_receipt_ref on the manifest's obligation bindings")
    args = ap.parse_args()
    try:
        return run(args.task, args.dispatch, args.out or "", args.review_receipt)
    except (ValueError, OSError) as exc:
        # A missing artifact is a finding with an owner. A traceback names a line of this
        # file, which is nobody's repair (TP2-2553).
        print(f"window_record: {exc}", file=sys.stderr)
        return EXIT_BAD_ARGS


if __name__ == "__main__":
    C.force_utf8()
    sys.exit(main())
