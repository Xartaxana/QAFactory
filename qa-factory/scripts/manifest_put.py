"""Merge a window's results into automation-manifest.json, instead of rewriting it.

S5 splits large work into windows, and windows run one after another **because they write
the same file**. That rule lived in the orchestrator's phase file and in nothing else, so
on TP2-2104 the second window's `Write` replaced the first window's manifest whole.
The loss was noticed and the first window was reconstructed by hand from the journal, the
surviving evidence logs and `git diff` — a repair that proves the point: the manifest is the
one artifact every S5 guard, the ledger, the traceability check and the delivery aggregator
read, and it is the one nothing protected.

This script is the only sanctioned way to add to it. It merges by identity and never
truncates:

  tests[]                 by INSTANCE id (`<function>[<param>]`) — the row with that id is
                          replaced; another instance of the same case is kept, because a case
                          is a relationship and several tests may prove it, and one test may
                          prove several cases (`covers[]`). Re-sending a case's fragment
                          therefore does NOT clear that case's other rows: an instance you
                          renamed or dropped has to be sent as the unresolved row it became,
                          or it survives forever. A 0.7.7 id with a `TC-…::` prefix still
                          matches its row — it is one of the instance's aliases, and a row left
                          standing in the old spelling is retracted into the new one. A row's
                          `case_version_links[]` is the case's CURRENT pin: a link replaces the
                          older link of the same case, other cases' links are kept.
  unresolved[]            by case identity — `<area>/TC-NNN` when the writer named an area,
                          the bare number when it did not (a bare row still matches either
                          area, so records written by 0.7.x keep being found). A field the
                          patch does not carry survives, so a later row that adds the
                          `remedy` (the fix a stand gap found: kind/where/change/restart)
                          supersedes the prose-only row without retyping its `detail`, and a
                          row rewritten to `handed_to_person` at a gate keeps the remedy the
                          person answered about. A re-sent `contradicts_requirement` row REPLACES
                          its slice - `instance_ids` / `instance_id` / `partitions` / `partition`, as
                          one group - when the patch names any of them, and its `thens` when the patch
                          carries `thens`; the two groups are independent, so a patch that re-sends the
                          instances keeps the Thens, and a group the patch leaves empty stays as it was
                          (a patch never widens a row; to widen it, retract it and send it again).
                          Two rows of ONE case with different reasons in one fragment are refused
                          before the commit: the merge would keep the later one and lose the other
  retracted_unresolved[]  drops the `unresolved[]` row of those cases (a bare case id finds the row of
                          every area) - the one way a row leaves that list while no green `tests[]`
                          entry takes its case: a partition row a green run does not take with it, or a
                          row whose Thens the author records one by one (`blocked_by_check`). The keys
                          stay on the manifest as history; `run` prints the slice and the `thens` of
                          each row it dropped. A key that names no row, or a row an earlier revision
                          already dropped, is refused; so is a fragment that sends the row of a case and
                          retracts it. `[]` retracts nothing
  provisional[]           by `id` (`P-<n>`, t-2181 PC-3): what a test ASSUMES rather than observed. A field the patch
                          omits survives, so a status or an `evidence` is one more small fragment. `home_hash` is built
                          HERE, before the commit, from the line that carries the marker `qa-provisional: P-n` in the
                          row's `home.file` (wherever the line is; `home.line_hint` is a hint only): a hash a role sends is
                          dropped, a patch that carries no `home` keeps the stored hash, and a marker that is not found
                          leaves the row with no hash and is printed. The baseline is taken only while the row is open (stored
                          open or absent AND open after the patch): once a row settles it keeps the hash it had, and the
                          tool stamps `evidence.home_hash_after` (the marked line now; a role-sent value is dropped).
                          `tests[].provisional` (`[P-n]`) merges with the other fields of the test row. A non-list
                          `provisional`, a row that is no object, an id that is not `P-<n>` or repeats, and a bad
                          `tests[].provisional` are refused before the commit. `retracted_provisional: ["P-n"]` is the door
                          out: the row stays with `status: retracted`; an id that names no row is refused
  self_fixes[], runs[]    appended; a line another role wrote is never edited
  obligation_bindings[]   by obligation id, and the id is the PLAN's
                          (`coverage_obligations[].obligation_id`, verbatim): a fragment
                          naming any other id is refused, because the projection joins by
                          exact equality and an id nothing joins is a silent gap.
                          `retracted_obligations[]` drops a binding whose id is being
                          replaced — the one way a row leaves this map
  retracted_instances[]   drops those rows from `tests[]` by instance id (any spelling the row
                          answers to) — the one way a single test row leaves the manifest when
                          the case's other rows are good, e.g. a partition that was renamed.
                          One fragment cannot both send and retract the same id, nor send a Then row
                          bound to it. It takes the `then_bindings` rows of the retired spelling with
                          it when no remaining row wears that spelling (`run` prints them), and a
                          later send of the retracted name with no case links (`covers`,
                          `case_version_links`, ...) is refused before the commit: a row that proves
                          no case is a ghost. Sending the name back with its links is a return, not a ghost
  expectation_changes[]   by (the functions, `red_attempt`, `green_attempt`): the record of a
                          test that changed between its red run and the next green run (or was
                          renamed or deleted after it — `green_attempt: null`). The author
                          writes `then_refs`, `what_changed`, `reason`; the code critic adds
                          `critic_verdict` and `critic_note`; a field the patch does not carry
                          survives, except that a verdict which differs from the old one takes
                          the old note away (it explained the old verdict), and `could_not_judge`
                          is refused without a note of its own. One row may name several functions (`functions`) that share
                          the same pair of runs; a patch naming some of them, with the same two
                          attempts, lands on that one record (the list of functions is not
                          shrunk) — two such records, or none, refuse it. The critic's verdict
                          judged the author's words as they were: a patch that changes
                          `then_refs`, `what_changed` or `reason` of a record that carries
                          `critic_verdict` drops the verdict and its note (and says so), unless
                          it carries a verdict of its own. A row nothing reads any more stays
                          as history — `s5_precheck.py` finds the pairs and joins the rows to them
  everything else         set when the fragment carries it (probe, run_witness, head, ...)

  manifest_put.py --task QA-1 --fragment window2.json
  manifest_put.py --task QA-1 --fragment -            # the fragment on stdin
  manifest_put.py --task QA-1 --fragment '{"tests": [...]}'   # the JSON itself, when it starts with {
  manifest_put.py --task QA-1 --recover               # replay the journal into the manifest (no fragment)
  manifest_put.py --selftest

A refusal of the merge is raised BEFORE the fragment is committed; a committed fragment the merge
cannot take (journals written before that, or a failure nobody foresaw) is skipped and named in the
manifest's `unprojected_events`, never fatal, and `--recover` replays the journal.

A case may move between `tests[]` and `unresolved[]` — that is a decision, and the mover
wins. What cannot happen here is a case leaving the manifest because somebody else's write
did not know about it.
"""
import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import project_root, read_json, story_root  # noqa: E402
import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
from person_words import door  # noqa: E402
from role_cli import (REPAIR_MARKER, command_from_argv, epilog, refuse,  # noqa: E402
                      run_guarded)

EXIT_BAD_ARGS = 2
EXIT_BAD_FRAGMENT = 3
# The event IS in the journal and only the projection failed: not a fragment to repair and not
# one to send again, so it has its own code (the door is `--recover`).
EXIT_COMMITTED_STALE = 4

MANIFEST_EVENTS = ("manifest_seed", "manifest_patch")
# The manifest's own stale marker. It shared `projection-stale.json` with the controller's
# projection, so `controller.py --operation recover` removed it without rebuilding the manifest
# (TP2-2406 S5-4, 19.10.2026). Same precedent: `environment-projection-stale.json`.
MANIFEST_STALE_MARKER = "manifest-projection-stale.json"

BY_CASE = ("unresolved",)
BY_INSTANCE = ("tests",)
# The key only `manifest_from_tests.py` writes on a row: a patch carrying it is the writer's re-run.
WRITER_MARK = "generated_from"
APPEND_ONLY = ("self_fixes", "runs")
# Merged by the record's own key — (sorted functions, red_attempt, green_attempt) — not by a
# case or an instance: one change of a test is identified by WHICH test and WHICH two runs.
# `design/state-exits.md` has a row for it and `test_state_exits.py` walks this tuple.
BY_RECORD = ("expectation_changes",)
# The helpers a story made new (TQ1-7): merged by `(file, name)`. Two writers, one row: the scaffold (`file`, `name`,
# `novelty`) is `manifest_from_tests.py`'s, the four role fields are the role's, sent by `--fragment`. A writer row is the
# one that carries `novelty`; it replaces the row and takes with it the rows of the files it read whose function is gone.
# A role row updates only the role fields of a row that stands. `design/state-exits.md` has a row for it.
BY_HELPER = ("introduced_helpers",)
HELPER_ROLE_FIELDS = ("purpose", "searched", "similar_found", "keep")
HELPER_SCAFFOLD_FIELDS = ("file", "name", "novelty")
# The assumptions registry (t-2181 PC-3): merged by the row's `id`; `retracted_provisional` is its door out. Both keys are the
# merge's own, so the trailing "a scalar the fragment carries wins" loop must not copy them (`SCALAR_EXEMPT`).
# `design/state-exits.md` has a row for it and `test_state_exits.py` walks this tuple.
BY_ID = ("provisional",)
RETRACT_PROVISIONAL = "retracted_provisional"
VERDICTS_LIST = "expectation_change_verdicts"  # in handoffs/vocabulary.yaml (FR-13)
# `runs[]` is a log — the same launch recorded twice is two facts about one launch only if
# the role meant it, so only `self_fixes[]` is de-duplicated (self_fixes[1] and [2] of
# TP1-15045 were byte-identical, which read as two repairs of the same line).
DEDUPED = ("self_fixes",)
# Keys the trailing "a scalar the fragment carries wins" loop must not copy verbatim: each is
# handled above by a rule of its own, and `retracted_obligations` is a manifest-level history,
# not something a fragment sets; `retracted_unresolved` is the same kind (a history the retraction appends to).
SCALAR_EXEMPT = {"expected_revision", "obligation_bindings", "retracted_obligations",
                 "retracted_instances", "retracted_unresolved", "then_bindings", "retract", RETRACT_PROVISIONAL,
                 *BY_RECORD, *BY_HELPER, *BY_ID}
# `retract` (RN1-22, LOCAL-1 run 3): the fragment's own sign "replace these top-level keys whole / take the Thens of a named
# unit out". A list of key names, never stored. The three keys below have a door of their own and are refused here.
RETRACT_KEY = "retract"
RETRACT_DOORS = {"tests": "retracted_instances", "unresolved": "retracted_unresolved",
                 "obligation_bindings": "retracted_obligations"}


def _case(entry) -> str:
    """The case identity of a row: `<area>/TC-NNN` when the writer named an area, else the
    bare number it has always been (`contract.case_key`)."""
    if not isinstance(entry, dict):
        return ""
    return C.case_key(str(entry.get("case") or "").strip(), str(entry.get("area") or "").strip())


def _same_case(key: str, other: str) -> bool:
    """Do two keys name one case? A bare id matches any area, so a row written by 0.7.x is
    still the row a fragment written today patches."""
    return bool(key) and bool(other) and C.case_matches(key, other)


def _matches_any(key: str, keys) -> bool:
    return any(_same_case(key, other) for other in keys or ())


def _match_key(key: str, pool) -> str:
    """The pool key that names the same case as `key`, or ''.

    Exact first, so two areas never trade rows; a bare id then matches the one area that
    holds it, and NEVER two — with `speakers/TC-001` and `speaker-detail/TC-001` both in the
    fragment, an old bare row is ambiguous and is kept as it is rather than merged into a
    coin-flip (FB-2428-1: the coin-flip is how two approved entries were lost)."""
    if not key:
        return ""
    if key in pool:
        return key
    found = [other for other in pool if _same_case(other, key)]
    return found[0] if len(found) == 1 else ""


def _instance(entry) -> str:
    return C.test_instance_id(entry) if isinstance(entry, dict) else ""


def _identity(entry) -> tuple:
    """Every spelling one instance answers to: the canonical id, the 0.7.7 case-prefixed one
    and the 0.7.x selector hash, so a fragment written now REPLACES the row an older manifest
    holds for that test instead of landing beside it."""
    return tuple(C.instance_id_aliases(entry)) if isinstance(entry, dict) else ()


def _spellings(entry) -> set:
    """Every spelling ONE `tests[]` row answers to: `_identity` and the canonical id (B-1, critic t-1276: the one place the
    set is built - `_worn`, the `held_before` of `_merge` and both sides of `is_ghost_row` ask it)."""
    return {s for s in (*_identity(entry), _instance(entry)) if s}


def _links(entry) -> list:
    """The cases one instance proves — `covers` / `case_version_links`, else its own `case`,
    each as a full key so two areas holding the same numbers stay two sets of cases."""
    return C.manifest_test_keys(entry) if isinstance(entry, dict) else []


LINK_FIELDS = ("covers", "case_links", "case_version_links", "cases")


def _different_files(one, other) -> bool:
    left, right = str((one or {}).get("file") or ""), str((other or {}).get("file") or "")
    return bool(left) and bool(right) and left != right


def _current_spelling(old, patch, merged) -> tuple:
    """One instance keeps ONE spelling, and it is the current one. -> (row, retracted id).

    `TC-012::test_x[eu]` is what 0.7.7 wrote of the test that is `test_x[eu]` today. Whichever
    side carried the explicit id used to win the merge, so a story upgraded mid-flight kept
    writing the old spelling — and where the row had been written in both, both rows stood and
    the S5 exit gate reported seven structural findings about instances nobody had written
    twice (live TP1-15045, 22.09). Only a case-prefixed id is retired: an imported `ti_…`
    identity names receipts on disk and is left exactly where it is."""
    current = _instance(merged)
    if C.INSTANCE_SEP not in current:
        return merged, ""
    prefer = next((i for i in (_instance(patch), _instance(old))
                   if i and C.INSTANCE_SEP not in i), "")
    if not prefer:
        return merged, ""
    for key in ("instance_id", "test_instance_id"):
        merged.pop(key, None)
    if _instance(merged) != prefer:
        merged["instance_id"] = prefer
    return merged, current


def _retract_aliases(entries) -> tuple:
    """Collapse rows that are two spellings of ONE instance. -> (rows, retracted ids).

    A story started on 0.7.6 and continued on 0.7.8 carries rows whose id is
    `TC-012::test_x[eu]` beside the same test written today as `test_x[eu]`. Readers have
    always known those name one instance (`contract.instance_id_aliases`); only the writer did
    not, so both rows stood and the S5 exit gate reported seven structural findings about
    instances nobody had written twice (live run of TP1-15045, 22.09). Upgrading the plugin
    mid-story is normal for the pilot, so the reading rule is applied to writing: the current
    spelling survives, carrying every case link of the row it retracts."""
    kept, seen, retracted = [], [], []
    for entry in entries:
        aliases = set(_identity(entry))
        # Two rows that name DIFFERENT test files are two tests whatever their ids say — the
        # collision `_refuse_colliding_ids` exists for, never a spelling to collapse.
        hit = next((i for i, known in enumerate(seen)
                    if known & aliases and not _different_files(kept[i], entry)), -1) if aliases else -1
        if hit < 0:
            kept.append(entry)
            seen.append(aliases)
            continue
        first, second = kept[hit], entry
        live, legacy = second, first  # the later write wins, unless it is the older spelling
        if C.INSTANCE_SEP in _instance(second) and C.INSTANCE_SEP not in _instance(first):
            live, legacy = first, second
        merged, retired = _current_spelling(legacy, live, _merge_entry(legacy, live))
        for key in LINK_FIELDS:
            if key == "case_version_links" and all(
                    isinstance(row.get(key) or [], list) for row in (legacy, live)):
                # a pin is the case's current version: the stale one of the retired spelling
                # must not come back beside the live one (same rule as `_merge_entry`)
                union = _replace_links(legacy.get(key) or [], live.get(key) or [])
            else:
                union = list(legacy.get(key) or [])
                for value in live.get(key) or []:
                    if value not in union:
                        union.append(value)
            if union:
                merged[key] = union
        retracted.append(retired or _instance(legacy))
        kept[hit] = merged
        seen[hit] = aliases | set(_identity(merged)) | seen[hit]
    return kept, [rid for rid in retracted if rid]


def _partition_scoped(entry) -> bool:
    """An `unresolved[]` row that names partitions speaks about a SLICE of the case; a row
    without them speaks about the whole case. Only the whole-case row competes with tests[]."""
    if not isinstance(entry, dict):
        return False
    # `instance_ids` (t-219): the row of a case carries the list of its blocked instances; a row that names
    # instances is about a SLICE of the case exactly like one that names partitions, and must never drop
    # the tests[] rows of the case (`_whole_case`). The keys are `contract.UNRESOLVED_SLICE_KEYS` (HF2-3, AR-13):
    # one home for what a row's slice is; `thens` is not one of them (a row that names only Thens is the whole case's).
    return any(entry.get(key) for key in C.UNRESOLVED_SLICE_KEYS)


def _blocked_row(entry) -> bool:
    """Is this `unresolved[]` row one the stand blocked (`reason: blocked_by_env`)?"""
    return isinstance(entry, dict) and str(entry.get("reason") or "") == "blocked_by_env"


def _then_row(entry) -> bool:
    """Is this `unresolved[]` row about particular Thens of a case that ran (`contract.then_scoped_row`, the one predicate)?"""
    return C.then_scoped_row(entry)


NOT_RAN_STATUSES = ("blocked_by_env", "not_run")   # + `manifest_from_tests.PENDING`: the test has not produced a result
RED_STATUSES = ("red", "failed", "error")          # `manifest_from_tests` writes `red`; `contract.RESULT_STATUS` the others


def _ran_rows(case: str, incoming_tests, stored_tests) -> list:
    """The `tests[]` rows that PROVE `case` ran: the fragment's own rows (each read OVER the stored row of its identity, so a
    patch that names only the instance and a verdict keeps the stored links and status), and the stored ones whose identity
    no incoming row overlaps (the patch replaces them), that link the case and whose status is not `pending_run`, `blocked_by_env` or
    `not_run`. NO status counts as ran (M-2): a hand-written row without one is a test that was run - as `_merge` reads
    `status or "green"` - and treating it as not run is how the Then rows of CART-1 vanished. Pure."""
    from manifest_from_tests import PENDING      # inside: `manifest_from_tests` imports this module
    not_ran = (PENDING, *NOT_RAN_STATUSES)
    incoming = [e for e in incoming_tests or [] if isinstance(e, dict)]
    stored = [e for e in stored_tests or [] if isinstance(e, dict)]
    taken = {i for e in incoming for i in _identity(e)}

    def over(row):   # a patch is read over the stored row of its identity: what it leaves out (links, status) stays
        ids = set(_identity(row))
        return {**next((s for s in stored if ids.intersection(_identity(s))), {}), **row}
    rest = [e for e in stored if not taken.intersection(_identity(e))]
    return [e for e in (*map(over, incoming), *rest)
            if _matches_any(case, _links(e)) and str(e.get("status") or "").strip() not in not_ran]


def _explicit_green(case: str, incoming_tests) -> bool:
    """Does a fragment's `tests[]` row say `status: green` for `case`? No status and `""` are no word at all (O2)."""
    return any(str(e.get("status") or "").strip() == "green" and _matches_any(case, _links(e))
               for e in incoming_tests or [] if isinstance(e, dict))


def _case_has_red(case: str, incoming_tests, stored_tests) -> bool:
    return any(str(e.get("status") or "").strip() in RED_STATUSES for e in _ran_rows(case, incoming_tests, stored_tests))


def _with_naming(row: dict, names: list) -> dict:
    """A copy of `row` that names exactly `names` in `instance_ids` (normalised: `instance_id` goes)."""
    out = {key: value for key, value in row.items() if key not in ("instance_id", "instance_ids")}
    if names:
        out["instance_ids"] = list(names)
    return out


def _union_blocked(first: dict, second: dict) -> dict:
    """Two rows of ONE case inside one fragment: the later wins (today's rule), except that two `blocked_by_env`
    rows keep BOTH rows' instances (O1). The fragment `unresolved: [{TC_4, instance_id: t[a]}, {TC_4, instance_id:
    t[b]}]` is the automator saying two tests of TC_4 are blocked; keeping the last row alone left t[a] a plain
    failure with no row. The union is in the rows' own order, without repeats, normalised to `instance_ids`.
    A row that names nothing adds nothing (it never widens the other's naming); when neither names an instance
    the later row stands unchanged. The allowed error is the narrower naming: an instance left out reads as
    a failure and its refusal says so."""
    if not (_blocked_row(first) and _blocked_row(second)):
        return second
    import acceptance as AC
    names = list(dict.fromkeys(AC.blocked_row_names(first) + AC.blocked_row_names(second)))
    return _with_naming(second, names) if names else second


def _replace_blocked_naming(patch: dict, merged: dict) -> dict:
    """ACROSS fragments, a `blocked_by_env` patch that names instances REPLACES the old row's naming - both keys,
    `instance_id` and `instance_ids` - and carries it as `instance_ids` (O1). `_merge_entry` is a plain update,
    so an old `instance_id` survived beside a new `instance_ids` and the two read as a union by accident.
    Replace, not union, is the allowed error: a union would keep marking blocked a test that a later send no
    longer names (a real red among them). A patch that names none (a remedy fix, a detail) keeps the old naming."""
    if not _blocked_row(merged):
        return merged
    import acceptance as AC
    names = AC.blocked_row_names(patch)
    return _with_naming(merged, names) if names else merged


def _replace_contradicts_slice(patch: dict, merged: dict, old: dict) -> dict:
    """ACROSS fragments, a re-sent `contradicts_requirement` row REPLACES the old row's slice and its Thens (F15, HF2-3).
    `_merge_entry` is a plain update, so an old `partitions: [P-msteams]` survived beside a new `instance_ids: [x]`
    and the row kept speaking about a slice the author had just corrected. Two groups, each decided on its own:
    the SLICE keys (`contract.UNRESOLVED_SLICE_KEYS`: instances and partitions together) become exactly the
    non-empty ones the patch carries, and `thens` (`UNRESOLVED_THENS_KEY`) becomes the patch's. A group the patch
    does not carry - absent, `[]`, `""` or None - is put back as the OLD row had it, so a patch with only a `detail`
    (or one that re-sends the instances) never widens or wipes the other group. The allowed error is the narrower
    row: a patch never widens a row, and to widen it the author retracts the row and sends it again
    (`retracted_unresolved`). `old` is the row before the update: the update has already overwritten what the
    patch carries empty, and only the old row knows what to put back. Other reasons are returned as they are."""
    import acceptance as AC
    if str(merged.get("reason") or "") != AC.CONTRADICTS_REQUIREMENT:
        return merged
    out = dict(merged)
    for keys in (C.UNRESOLVED_SLICE_KEYS, (C.UNRESOLVED_THENS_KEY,)):
        carried = {key: patch[key] for key in keys if patch.get(key)}
        wanted = carried or {key: old[key] for key in keys if key in old}
        for key in keys:
            if key in wanted:
                out[key] = wanted[key]  # an existing key keeps its place, so a `detail`-only patch changes no byte
            else:
                out.pop(key, None)
    return out


def _drop_blocked_of_green(merged: dict, incoming_tests: list, summary: dict) -> None:
    """A green `tests[]` entry takes the `blocked_by_env` row of ITS instance with it (t-219, B8; FR-40: the
    way out of a blocked state is the stand coming back, and the proof is a green run sent through here).

    Which rows are the instance's is `acceptance.blocked_instances`'s to say (`strict=False`: the row's remedy
    decides nothing here) - the rows that NAME the instance (`instance_ids` / `instance_id`) and the rows that
    name none but whose case has exactly this one instance (the cmp2 rows carry a partition and no instance
    id). A row naming several instances loses only the one that went green and is dropped when its list is
    empty; any other matched row is dropped whole. EVERY such row of the instance goes, not the first one the
    reader finds (O4): the reader answers one row per instance, so the walk repeats until it finds none - an
    instance that covers TC_3 and TC_4 has a row for each, and a green run leaves neither behind (a row left
    over would read "blocked-but-green" on the next send). Allowed error: leave a row (a partition row on a
    case with two instances is never guessed at, E7); `s5_precheck` then names the stale row. Rows are
    replaced, never edited in place - `merged` shares them with the manifest the caller passed in."""
    import acceptance as AC
    # EXPLICITLY green: a fragment with no `status` is a review or a result patch (the critic's `unverified`
    # verdict on a blocked instance arrives exactly so) and says nothing about a run. Reading the missing key
    # as green - as the whole-case drop above does - would drop the blocked row the moment the critic reviews it.
    greens = [_instance(e) for e in incoming_tests if str(e.get("status") or "") == "green"]
    greens = [g for g in greens if g]
    rows = [r for r in C.manifest_unresolved(merged) if str(r.get("reason") or "") == AC.BLOCKED_OUTCOME]
    if not greens or not rows:
        return
    scope: dict = {}
    for entry in C.manifest_tests(merged):
        iid = _instance(entry)
        for case in C.manifest_test_links(entry):
            if iid and iid not in scope.setdefault(case, []):
                scope[case].append(iid)
    tests = C.manifest_tests(merged)
    # Every pass trims or drops at least one matched row, so the walk ends; the bound is only a guard.
    for _pass in range(len(C.manifest_unresolved(merged)) + 1):
        matched = AC.blocked_instances(merged, [{"instance_id": g} for g in greens], scope, strict=False)
        if not matched:
            return
        changed: dict = {}  # id(original row) -> the row without the instance, or None when nothing is left
        for iid, row in matched.items():
            current = changed.get(id(row), row)
            if current is None:
                continue
            entry = next((t for t in tests if iid in C.instance_id_aliases(t)), {})
            aliases = set(C.instance_id_aliases(entry)) | {iid}
            if not AC.blocked_row_instances(current):
                changed[id(row)] = None
                continue
            trimmed = dict(current)
            left = [n for n in current.get("instance_ids") or [] if n not in aliases]
            if left:
                trimmed["instance_ids"] = left
            else:
                trimmed.pop("instance_ids", None)
            if str(current.get("instance_id") or "").strip() in aliases:
                trimmed.pop("instance_id", None)
            changed[id(row)] = trimmed if AC.blocked_row_instances(trimmed) else None
        out = []
        for row in merged.get("unresolved") or []:
            if id(row) not in changed:
                out.append(row)
            elif changed[id(row)] is None:
                summary["moved"] += 1  # the case is back in tests[]: the stale blocked row goes
            else:
                out.append(changed[id(row)])
                summary["replaced"] += 1
        merged["unresolved"] = out


def _whole_case(entries, cases: set) -> set:
    return {_case(e) for e in entries or []
            if isinstance(e, dict) and _case(e) in cases and not _partition_scoped(e)}


def _moved_out(entry, unresolved_cases: set) -> bool:
    """A test row leaves `tests[]` only when EVERY case it proves has moved to unresolved[].

    The drop used to read the entry's `case` field alone, so a consolidated instance proving
    TC-003/004/005 vanished the moment TC-003 went unresolved, taking the evidence for the
    other two cases with it."""
    links = _links(entry)
    return bool(links) and all(_matches_any(case, unresolved_cases) for case in links)


def _refuse_colliding_ids(entries) -> None:
    """Two rows of ONE fragment that resolve to one id but name different test files.

    Since 0.7.7 an id is `<function>[<param>]` with no case prefix, so two cases whose tests
    share a function name in different files collapse onto one identity — and a silent merge
    would drop a window's work, the loss this whole script exists to prevent."""
    by_id: dict = {}
    for entry in entries or []:
        iid = _instance(entry)
        seen = by_id.get(iid)
        if iid and seen is not None and str(seen.get("file") or "") != str(entry.get("file") or ""):
            raise ValueError(
                f"two tests[] entries resolve to the instance id {iid!r} but name different "
                f"files ({seen.get('file')!r}, {entry.get('file')!r}) — one id is one test. "
                "Give the id the parameter that tells them apart, or name the function "
                "distinctly in the test code; do not let one row overwrite the other")
        if iid:
            by_id[iid] = entry


# The keys of a row-form `novelty` block that name WHAT was measured and BY WHOM. The item form of a
# window (`{"value", "basis", "resolved": true}`, P5-G) carries neither, and a row that held it would
# read `unchanged` without one hash being compared - so the two forms never meet on a `tests[]` row.
NOVELTY_ROW_KEYS = ("measured_on", "measured_by")


def novelty_row_problems(fragment) -> list:
    """One sentence per `tests[]` row of the fragment whose `novelty` is not a row-form block: not an
    object, carrying `resolved` (any value), or lacking `measured_on` / `measured_by`. Pure.

    Only `manifest_from_tests.py` writes `novelty` on a row, and it always writes the whole row form.
    `proof_level.novelty_of` honours the item form (`resolved: true`, neither key) without re-hashing
    anything, because a window ITEM is built from a row already measured; a role fragment with that
    shape on a ROW made a required test read `unchanged` (t-187, F-B; critic of B-207). A row-form
    block that is complete is accepted as it always was: what it says is trusted (the F-2 debt line
    stays) - this check is about the form, not the value. A row without the key is not looked at."""
    problems = []
    rows = fragment.get("tests") if isinstance(fragment, dict) else None
    for at, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or "novelty" not in row:
            continue
        block = row["novelty"]
        bad = []
        if not isinstance(block, dict):
            bad.append("is not an object")
        else:
            if "resolved" in block:
                bad.append("carries `resolved` (the form of a window item)")
            missing = [f"`{key}`" for key in NOVELTY_ROW_KEYS if key not in block]
            if missing:
                bad.append("lacks " + " and ".join(missing))
        if bad:
            name = str(row.get("instance_id") or row.get("test") or f"tests[{at}]")
            problems.append(f"the `novelty` of {name} " + " and ".join(bad))
    return problems


# What the code critic records on a `tests[]` row after it opened the run log of the test's last run (TQ1-18): the base of a
# before/after comparison answered `refused` or `working`, in the run named by `run` (the attempt id of that run's block). The two
# words are ONE tuple; the ledger reads only `refused` (`ledger.BASE_REFUSED`, pinned to this tuple by `test_ledger.py`): a word outside
# it is never a verdict (FR-41).
BASE_OUTCOMES = ("refused", "working")


def base_outcome_row_problems(fragment) -> list:
    """One sentence per `tests[]` row of the fragment whose `base_outcome` is not `{"outcome": refused|working, "run": <non-empty
    run id>}`. Pure; a row without the key is not looked at. The record counts only while `run` is the row's CURRENT run
    (`ledger.test_state`), so a value with no run could never be current and is refused here, not stored dead."""
    problems = []
    rows = fragment.get("tests") if isinstance(fragment, dict) else None
    for at, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or "base_outcome" not in row:
            continue
        block, bad = row["base_outcome"], []
        if not isinstance(block, dict):
            bad.append("is not an object")
        else:
            if block.get("outcome") not in BASE_OUTCOMES:
                bad.append(f"has `outcome` {str(block.get('outcome'))[:30]!r}, which is not one of " + ", ".join(BASE_OUTCOMES))
            if not str(block.get("run") or "").strip():
                bad.append("names no `run`")
        if bad:
            name = str(row.get("instance_id") or row.get("test") or f"tests[{at}]")
            problems.append(f"the `base_outcome` of {name} " + " and ".join(bad))
    return problems


def obligation_hash_problems(fragment, stored_tests=None) -> list:
    """One sentence per `tests[]` row of the fragment that SENDS an `obligation_hash` the code cannot vouch for. Pure.

    The hash is `content_hash(obligation_refs)`, built by the code (`window_record` builds the same one for the window,
    `manifest_from_tests` writes the refs): a role that types it either copies a stale one or invents it, and a
    hash that binds nothing is read downstream as a proof (AR-14: the code writes what the code computes). The refs it
    must bind are the row's own `obligation_refs` in the patch (a list, empty included - the merge takes the patch's
    value), else those of the stored row of the same instance (`stored_tests`, the way `_current_records` reads
    the manifest). A hash with no refs to check is refused ("cannot be checked"), a hash that is not
    `content_hash(refs)` is refused with the one the code builds. A row without an `obligation_hash` (absent, `null`
    or empty) is not looked at: leaving it out is the door."""
    from event_store import content_hash
    problems = []
    rows = fragment.get("tests") if isinstance(fragment, dict) else None
    stored = [t for t in (stored_tests if isinstance(stored_tests, list) else []) if isinstance(t, dict)]
    for at, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or row.get("obligation_hash") in (None, ""):
            continue
        sent = row["obligation_hash"]
        refs = row.get("obligation_refs")
        if not isinstance(refs, list):
            spellings = _spellings(row)
            refs = next((t.get("obligation_refs") for t in stored if spellings & _spellings(t)), None)
        refs = [r for r in refs if isinstance(r, dict)] if isinstance(refs, list) else []
        if not refs:
            problems.append(f"tests[{at}].obligation_hash {sent} cannot be checked: the row names no obligation_refs; "
                            "leave it out, the code builds it")
        elif sent != content_hash(refs):
            problems.append(f"tests[{at}].obligation_hash {sent} is not the hash of its obligation_refs "
                            f"({content_hash(refs)}); leave it out, the code builds it")
    return problems


def _helper_id(row) -> tuple:
    """`(file, name)` of an `introduced_helpers[]` row, the pair the rows are merged by."""
    return (str(row.get("file") or "").strip(), str(row.get("name") or "").strip()) if isinstance(row, dict) else ("", "")


def helper_row_problems(current, fragment) -> list:
    """One sentence per `introduced_helpers[]` row of a fragment that cannot be taken, [] when none is. Pure.

    A row has `file` and `name`, the four role fields (strings) and, when the WRITER sent it, `novelty`
    (`new` / `changed` / `unknown`). Any other key is refused with the fields named. A row that carries no `novelty` is a
    role's: it fills the role fields of a row that stands (`current`) or that the same fragment brings; a row for a
    (file, name) that nobody wrote is refused with the door - the scaffold is `manifest_from_tests.py`'s, never the role's,
    so the role cannot invent a helper row that the history never made. The refusal is here and not in `merge`: merge
    replays every event already committed."""
    if not isinstance(fragment, dict) or "introduced_helpers" not in fragment:
        return []
    rows = fragment["introduced_helpers"]
    fields = ", ".join((*HELPER_SCAFFOLD_FIELDS, *HELPER_ROLE_FIELDS))
    if not isinstance(rows, list):
        return [f"`introduced_helpers` is a list of rows with the fields {fields}"]
    standing = {_helper_id(r) for r in ((current or {}).get("introduced_helpers") or [])} \
        if isinstance((current or {}).get("introduced_helpers"), list) else set()
    written = {_helper_id(r) for r in rows if isinstance(r, dict) and "novelty" in r}
    problems = []
    for at, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"introduced_helpers[{at}] is not an object (the fields are: {fields})")
            continue
        file, name = _helper_id(row)
        label = f"introduced_helpers[{at}] ({file}::{name})" if file and name else f"introduced_helpers[{at}]"
        extra = sorted(set(row) - set(HELPER_SCAFFOLD_FIELDS) - set(HELPER_ROLE_FIELDS))
        if extra:
            problems.append(f"{label} carries {', '.join(extra)}, which is not a field of the row (the fields are: {fields})")
        if not file or not name:
            problems.append(f"{label} needs `file` and `name` (the pair that names the helper)")
        bad = [f for f in HELPER_ROLE_FIELDS if f in row and not isinstance(row[f], str)]
        if bad:
            problems.append(f"{label}: {', '.join(bad)} must be text")
        if "novelty" in row and row["novelty"] not in ("new", "changed", "unknown"):
            problems.append(f"{label}: `novelty` is one of new, changed, unknown - and it is written by "
                            "`manifest_from_tests.py`, not by a role")
        elif "novelty" not in row and file and name and (file, name) not in standing and (file, name) not in written:
            problems.append(f"{label} names a helper the manifest holds no row for: the rows are written by "
                            "`manifest_from_tests.py --task <T> --dispatch <id> --file <your test file>` (it lists every "
                            "new helper of your files); run it, then send only your four fields "
                            "(purpose, searched, similar_found, keep) for the rows it wrote")
    return problems


def _merge_helpers(merged: dict, fragment: dict, summary: dict) -> None:
    """`introduced_helpers[]` by `(file, name)` (see `BY_HELPER`). A writer row (it carries `novelty`) replaces the row;
    the rows of a file the writer read - a file with a writer row, or with a writer-marked `tests[]` row of the same
    fragment - that it did not send again are dropped (the function is gone). A role row (no `novelty`) changes the
    role fields of a row that stands and creates nothing. A row of another file is never touched."""
    key = BY_HELPER[0]
    incoming = (fragment or {}).get(key)
    if key not in (fragment or {}) or not isinstance(incoming, list):
        return
    patches: dict = {}
    writer_files: set = set()
    for row in incoming:
        pair = _helper_id(row)
        if not pair[0] or not pair[1]:
            continue
        patches[pair] = {**patches.get(pair, {}), **row, "file": pair[0], "name": pair[1]}
        if "novelty" in row:
            writer_files.add(pair[0])
    for entry in (fragment or {}).get("tests") or []:
        if isinstance(entry, dict) and WRITER_MARK in entry and entry.get("file"):
            writer_files.add(str(entry["file"]))
    out, taken = [], set()
    for row in [r for r in (merged.get(key) or []) if isinstance(r, dict)]:
        pair = _helper_id(row)
        if pair in patches:
            taken.add(pair)
            patch = patches[pair]
            if "novelty" in patch:      # the writer's empty role field is "it knows nothing", never a wipe of the role's words
                patch = {k: v for k, v in patch.items() if not (k in HELPER_ROLE_FIELDS and v == "")}
            out.append({**row, **patch})
            summary["replaced"] += 1
        elif pair[0] in writer_files:
            continue                                   # the writer read this file and the function is not there now
        else:
            out.append(row)
            summary["kept"] += 1
    for pair, patch in patches.items():
        if pair not in taken and "novelty" in patch:
            out.append(patch)
            summary["added"] += 1
    merged[key] = out


def provisional_row_problems(current, fragment) -> list:
    """One sentence per defect of the provisional keys of a fragment, [] when none is. Pure.

    The refusals of the registry, asked by `_refuse_unmergeable` under the lock before the commit (never in `merge`, which
    replays every event ever committed and must not raise): `provisional` is a list of rows; a row is an object whose `id` is
    `P-<n>` and appears once in the fragment; `tests[].provisional` is a list of `P-<n>`; `retracted_provisional` is a list of
    ids and each names a row the manifest (`current`) or this same fragment holds. The reader (`contract.manifest_provisional`)
    stays tolerant of what is already stored."""
    if not isinstance(fragment, dict):
        return []
    out, rows = [], fragment.get(BY_ID[0])
    held = {C.provisional_id(r) for r in ((current or {}).get(BY_ID[0]) or []) if isinstance(r, dict)} \
        if isinstance((current or {}).get(BY_ID[0]), list) else set()
    if BY_ID[0] in fragment and not isinstance(rows, list):
        out.append(f"`provisional` is a list of rows ({{id: \"P-<n>\", kind, what, status, home}}); it was sent as "
                   f"{type(rows).__name__}")
    seen = set()
    for at, row in enumerate(rows if isinstance(rows, list) else []):
        pid = C.provisional_id(row)
        if not isinstance(row, dict):
            out.append(f"provisional[{at}] is not an object (a row is {{id: \"P-<n>\", kind, what, status, home}})")
        elif not C.PROVISIONAL_ID_RE.match(pid):
            out.append(f"provisional[{at}] has the id {pid!r}, which is not of the form P-<n>")
        elif pid in seen:
            out.append(f"provisional[{at}] repeats the id {pid}: send one row per id")
        else:
            seen.add(pid)
    for entry in fragment.get("tests") or []:
        value = entry.get("provisional") if isinstance(entry, dict) else None
        if value is None:
            continue
        label = f"tests[] {entry.get('instance_id') or '(no instance_id)'}: `provisional`"
        if not isinstance(value, list):
            out.append(f"{label} is a list of ids (e.g. [\"P-1\"]); it was sent as {type(value).__name__}")
        else:
            out.extend(f"{label} holds {item!r}, which is not of the form P-<n>" for item in value
                       if not (isinstance(item, str) and C.PROVISIONAL_ID_RE.match(item.strip())))
    if RETRACT_PROVISIONAL in fragment:
        asked = fragment[RETRACT_PROVISIONAL]
        if not isinstance(asked, list):
            out.append(f"{RETRACT_PROVISIONAL} is a list of ids, e.g. [\"P-1\"]; it was sent as " + type(asked).__name__)
        else:
            unknown = [i for i in dict.fromkeys(str(x).strip() for x in asked if str(x).strip()) if i not in held | seen]
            if unknown:
                out.append(f"{RETRACT_PROVISIONAL} names no provisional[] row this manifest holds: " + ", ".join(unknown)
                           + " - the ids are the `id` of the rows already sent through `manifest_put.py --fragment`")
    return out


def _open_or_absent(row) -> bool:
    return str((row or {}).get("status") or "open").strip() == "open"


def _merge_provisional(merged: dict, fragment: dict, summary: dict) -> None:
    """`provisional[]` by `id` (see `BY_ID`), then the door `retracted_provisional`. Never raises (replay): what a fragment
    may not send is refused earlier by `provisional_row_problems`.

    A patch of a standing id lays its fields over the row (a field it omits survives, `home` and `evidence` are replaced as
    wholes); a row with a new id is appended; a row with no usable id (only an old journal holds one) is appended untouched
    and `contract.manifest_provisional` skips and names it. The baseline `home_hash` is taken from a patch ONLY when the
    stored row is absent or open AND the row after the patch is open (E-P1): a row that settles, or has settled, keeps the
    hash it was baselined with, so the settling check can tell an edited line from a moved one. The key stays absent from a
    manifest no fragment ever sent it to (a story with every side real carries none), and an empty list SENT is the declared
    empty outcome. A retraction keeps the row as history with `status: retracted`."""
    key = BY_ID[0]
    incoming = (fragment or {}).get(key)
    if isinstance(incoming, list):
        rows = [r for r in (merged.get(key) or []) if isinstance(r, dict)]
        at = {}
        for i, row in enumerate(rows):
            at.setdefault(C.provisional_id(row), i)
        for patch in (p for p in incoming if isinstance(p, dict)):
            pid = C.provisional_id(patch)
            stored = rows[at[pid]] if pid and pid in at else None
            row = {**(stored or {}), **patch}
            if not (_open_or_absent(stored) and _open_or_absent(row)):
                if stored and "home_hash" in stored:
                    row["home_hash"] = stored["home_hash"]
                else:
                    row.pop("home_hash", None)
            if stored is not None:
                rows[at[pid]] = row
                summary["replaced"] += 1
            else:
                rows.append(row)
                if pid:
                    at[pid] = len(rows) - 1
                summary["added"] += 1
        merged[key] = rows
    asked_raw = (fragment or {}).get(RETRACT_PROVISIONAL)
    if not isinstance(asked_raw, list):
        return
    asked = set(str(i).strip() for i in asked_raw if str(i).strip())
    out = []
    for row in [r for r in (merged.get(key) or []) if isinstance(r, dict)]:
        if C.provisional_id(row) in asked and row.get("status") != "retracted":
            out.append({**row, "status": "retracted"})
            summary["retracted_provisional"] = summary.get("retracted_provisional", 0) + 1
        else:
            out.append(row)
    if key in merged or out:
        merged[key] = out


def stamp_provisional(fragment, project) -> tuple:
    """(the fragment with its `provisional[]` rows stamped, [sentences to print]). Pure; the fragment it is given is not edited.

    `home_hash` is built by the code, never typed by a role (AR-14): for a row that carries a `home.file` it is the hash of the
    marked line found by its marker (`contract.marked_line_hash`), so the same line one row lower gives the same hash; a
    marker that is not found leaves the row with an empty hash and a sentence naming the file and the marker (a message,
    never a raise - the row itself is still the role's record). A row that carries no `home` has any `home_hash` it brought
    removed. This is a candidate stamp only: whether `_merge_provisional` TAKES it (the baseline is kept once the row settles)
    is decided there, under the lock, against the stored row. A row that moves to a `settled_*` status and carries a
    `home.file` also gets `evidence.home_hash_after`, the hash of the marked line NOW, by the same function; a value a role
    sent there is dropped, and a row that is not settling keeps none."""
    rows = fragment.get(BY_ID[0]) if isinstance(fragment, dict) else None
    if not isinstance(rows, list):
        said = [f"`{BY_ID[0]}` was sent as {type(rows).__name__}, not a list of rows: nothing of it was merged"]             if isinstance(fragment, dict) and rows is not None else []
        return fragment, said
    out, said = [], []
    for row in rows:
        if not isinstance(row, dict):
            out.append(row)
            continue
        row = dict(row)
        pid = C.provisional_id(row)
        home = row.get("home")
        file = str(home.get("file") or "").strip() if isinstance(home, dict) else ""
        if file:
            digest, why = C.marked_line_hash(project, file, pid)
            row["home_hash"] = digest
            if why:
                said.append(f"provisional {pid or '(no id)'}: no home_hash was recorded - {why}. Put the comment "
                            "`qa-provisional: <id>` on the line of the locator, contract or mock in its home file and send the "
                            "row again")
        else:
            row.pop("home_hash", None)
        if isinstance(row.get("evidence"), dict) and "home_hash_after" in row["evidence"]:
            row["evidence"] = {k: v for k, v in row["evidence"].items() if k != "home_hash_after"}
        if file and str(row.get("status") or "").startswith("settled_"):
            row["evidence"] = {**(row.get("evidence") if isinstance(row.get("evidence"), dict) else {}),
                               "home_hash_after": C.marked_line_hash(project, file, pid)[0]}
        out.append(row)
    return {**fragment, BY_ID[0]: out}, said


def _record_retractions(merged: dict, summary: dict, retracted: list) -> None:
    """A dropped row is a fact about the manifest, not a detail of one merge: the ids the
    revision retired are kept on the manifest itself, the way a move is counted in the
    summary, so the next reader can see what happened to a row it remembers."""
    retracted = [rid for rid in retracted if rid]
    if not retracted:
        return
    summary["retracted"] = summary.get("retracted", 0) + len(retracted)
    history = [rid for rid in merged.get("retracted_instances") or [] if rid]
    merged["retracted_instances"] = history + [rid for rid in retracted if rid not in history]


def _retract_obligations(merged: dict, fragment: dict, summary: dict) -> None:
    """`retracted_obligations: ["OB-1"]` drops those rows from `obligation_bindings[]`.

    The map had no way to lose a row: it merges by id and keeps everything it ever saw. That
    was fine while an id was only ever the plan's — but TP2-2553 wrote nine bindings
    under `OB-1..OB-9`, and renaming them to the ids the plan actually names would otherwise
    leave both spellings standing, one of them joining nothing. A retraction is recorded on the
    manifest (`retracted_obligations[]`) the way a retracted instance id is, so the next reader
    sees what happened to a row it remembers."""
    asked = [str(i) for i in (fragment or {}).get("retracted_obligations") or [] if i]
    if not asked:
        return
    bound = {str(b.get("obligation_id") or "") for b in (fragment or {}).get("obligation_bindings") or []
             if isinstance(b, dict)}
    clash = sorted(set(asked) & bound)
    if clash:
        raise ValueError(
            "one fragment cannot both bind and retract an obligation: " + ", ".join(clash)
            + " — send the binding under its new id and retract the old spelling, not the same id twice")
    rows = [b for b in merged.get("obligation_bindings") or []
            if str((b or {}).get("obligation_id") or "") not in set(asked)]
    gone = len(merged.get("obligation_bindings") or []) - len(rows)
    merged["obligation_bindings"] = rows
    history = [i for i in merged.get("retracted_obligations") or [] if i]
    merged["retracted_obligations"] = history + [i for i in asked if i not in history]
    if gone:
        summary["retracted"] = summary.get("retracted", 0) + gone


def _retract_instances(merged: dict, fragment: dict, summary: dict, held_before=()) -> None:
    """`retracted_instances: ["test_x[case0]"]` drops those rows from `tests[]`.

    `tests[]` had no way to lose ONE row. A row leaves only when every case it proves has moved
    to `unresolved[]` (`_moved_out`), and an `unresolved[]` row that names a partition is a
    slice that by design does not compete with `tests[]` - so a stale instance of a case whose
    other instances are good survives forever. Live TP1-13797, 27.09: seven rows written
    before the automator gave each partition an explicit id stood beside the new ones, and
    `run_suite` refuses a case's whole request when one requested id is not found, so TC-002
    and TC-003 could not be run at all. The role had a real need and no door; this is the door,
    and it is the same shape as `retracted_obligations[]`: the retraction is recorded on the
    manifest so the next reader sees what happened to a row it remembers.

    Matching is by every spelling the row answers to (`_identity`), so retracting the id an
    older manifest holds finds the row whatever spelling it was written in.

    `held_before`: every id the rows of the manifest answered to BEFORE this merge (`merge`
    computes it from `current`). A fragment that sends a test under its new spelling AND retracts
    the old one is the normal way to rename: the new row lands on the old one by alias
    (`_current_spelling` replaces the row), so by the time this runs no row answers to
    the old id - and the retraction is satisfied, not a role's wrong id. That is the 2406 shape.
    The 0.7.7 shape is different and NOT handled by this rule: a row `{"instance_id":
    "TC-012::test_x[eu]", "case": "TC-012"}` with a fragment that sends `test_x[eu]` and retracts
    `TC-012::test_x[eu]` still answers the prefixed id through `case` and is DROPPED, rows `[]`
    (the critic's probe P1); the drop rule (a row whose `_instance` is among the ids this fragment
    sent is never dropped) is queued, not implemented. The id is recorded in
    `retracted_instances` once, nothing is dropped, and `summary["retracted_instances"]` does not
    count it. TP2-2406 S5-4, 19.10.2026, journal seq 115: this function raised "names no
    row" over exactly that rename, AFTER the event was committed, and the manifest never moved
    past revision 5. An id the manifest never held still raises (a role's wrong id), and so does
    one an EARLIER revision already dropped (it is not in `held_before`: "already gone")."""
    asked = [str(i).strip() for i in (fragment or {}).get("retracted_instances") or [] if str(i).strip()]
    if not asked:
        return
    wanted = set(asked)
    sent = {alias for entry in (fragment or {}).get("tests") or []
            for alias in _identity(entry) if alias}
    clash = sorted(wanted & sent)
    if clash:
        raise ValueError(
            "one fragment cannot both send and retract a test instance: " + ", ".join(clash)
            + " - send the row under its new id and retract the old spelling, not the same id twice")
    rows, gone = [], 0
    for entry in merged.get("tests") or []:
        if wanted & set(_identity(entry)) or _instance(entry) in wanted:
            gone += 1
            continue
        rows.append(entry)
    if not gone and not wanted & set(held_before):
        raise ValueError(
            "retracted_instances names no row this manifest holds: " + ", ".join(sorted(wanted))
            + " - `manifest_view.py --task <T>` prints the instance ids it carries, and a row"
              " that is already gone is not retracted again")
    merged["tests"] = rows
    history = [i for i in merged.get("retracted_instances") or [] if i]
    merged["retracted_instances"] = history + [i for i in asked if i not in history]
    if gone:  # a retraction the merge itself already satisfied dropped nothing: the count stays as it was
        summary["retracted_instances"] = summary.get("retracted_instances", 0) + gone


def _retract_unresolved(merged: dict, fragment: dict, summary: dict, held_before=()) -> None:
    """`retracted_unresolved: ["TC-004"]` drops the `unresolved[]` row of that case (HF2-3, FA-8, FB-5).

    The list had one way out - a green `tests[]` entry for the case - and that way does not take a row that names a
    slice (`_partition_scoped`): on 12586 a `contradicts_requirement` row of TC-004 (or a stale partition row of TC-005)
    stood after the author had recorded the Thens behind the red one by one, and nothing in the factory could remove it.
    The key is read by `_same_case`: a bare id finds the row of every area (all of them are dropped, and `run` names
    each), an area-qualified key finds that area's row and a bare row. EVERY row of the case goes, and it goes whole -
    including a slice another instance still needs; that is loud, not silent: `run` prints the slice and `thens` of
    each dropped row, and a red instance left without its row is refused by the window (`product:`, F7) instead of read
    as passing. The keys are appended to the manifest's `retracted_unresolved` history, `summary` counts the rows.

    Refused (raised here, so `validate` catches it before the commit - no committed event carries the key yet):
      * a fragment that sends an `unresolved[]` row of the case and retracts it (send the new row, or retract the old one);
      * a key that names no row and that no earlier revision retracted, or that an earlier revision already retracted
        ("already gone"; the door is `manifest_view.py --task <T>`);
      * a value that is no list of strings. `[]` retracts nothing.
    `held_before`: the cases the `unresolved[]` rows of the manifest held BEFORE this merge. A fragment whose own green
    test already moved the case out (`merge`'s drop) satisfied the retraction: it is recorded, nothing is counted, and it
    is not a wrong key (the rename rule of `_retract_instances`)."""
    asked_raw = (fragment or {}).get("retracted_unresolved")
    if not asked_raw:
        return
    if not isinstance(asked_raw, list):
        raise ValueError("retracted_unresolved is a list of case keys, e.g. [\"TC-004\"]; it was sent as "
                         + type(asked_raw).__name__)
    asked = list(dict.fromkeys(str(k).strip() for k in asked_raw if str(k).strip()))
    sent = {_case(e) for e in (fragment or {}).get("unresolved") or [] if isinstance(e, dict) and _case(e)}
    for key in asked:
        if _matches_any(key, sent):
            raise ValueError(
                f"one fragment cannot both send and retract the unresolved row of {key} - send the new row, "
                "or retract the old one")
    history = [k for k in merged.get("retracted_unresolved") or [] if k]
    gone, unknown, finished = 0, [], []
    standing = list(merged.get("unresolved") or [])
    for key in asked:
        hit = [r for r in standing if isinstance(r, dict) and _same_case(key, _case(r))]
        standing = [r for r in standing if not any(r is h for h in hit)]
        gone += len(hit)
        if not hit and not _matches_any(key, held_before):
            (finished if _matches_any(key, history) else unknown).append(key)
    if unknown or finished:
        said = []
        if unknown:
            said.append("retracted_unresolved names no unresolved[] row this manifest holds: " + ", ".join(unknown)
                        + " - `manifest_view.py --task <T>` prints the cases it carries")
        if finished:
            said.append("retracted_unresolved: " + ", ".join(finished) + " is already gone - an earlier revision "
                        "retracted that row, and a row that is already gone is not retracted again")
        raise ValueError("; ".join(said))
    merged["unresolved"] = standing
    merged["retracted_unresolved"] = history + [k for k in asked if k not in history]
    if gone:
        summary["retracted_unresolved"] = summary.get("retracted_unresolved", 0) + gone


def unknown_obligation_refusal(task_root, fragment: dict) -> str:
    """The refusal a fragment earns when its `obligation_bindings[]` name an obligation the
    plan does not, else "".

    TP2-2553: the plan spelled every obligation `TS-1-O1` and every fragment the
    automator wrote spelled it `OB-1`. `merge()` asks only for a stable id, and
    `coverage_contract.coverage_projection` joins by exact equality — so twelve green instances
    produced `unique_instances: 0` and nine false coverage gaps, and nothing said so until
    delivery, two windows later. An obligation id is the plan's or it is nothing. A plan with no
    schema-2 obligations names none, and refuses none."""
    ids = [str(b.get("obligation_id") or "")
           for b in (fragment or {}).get("obligation_bindings") or []
           if isinstance(b, dict) and b.get("obligation_id")]
    unknown = C.unknown_obligation_ids(ids, task_root)
    if not unknown:
        return ""
    known = C.plan_obligation_ids(task_root)
    return (f"obligation ids not in the plan: {', '.join(unknown)} — the plan names "
            f"{', '.join(known)} (work/test-plan.json)")


def _passed_by_word(task_root, refusal: str) -> bool:
    """A person's recorded word passes this refusal, read at the source — the same
    `stage_overrides[]` that `s5_precheck.passed_by_word` reads, so one
    `waiver.py --stage S5 --block "obligation-id"` covers both the exit check and this writer
    instead of the person having to answer the same question twice."""
    try:
        from waiver import split_overridden
        pipeline = json.loads((Path(task_root) / "pipeline.json").read_text(encoding="utf-8"))
    except Exception:
        return False
    blocking, _ = split_overridden([f"obligation-id: {refusal}"], pipeline, "S5")
    return not blocking


def _key(value, ordered: bool = False) -> str:
    """The value as one canonical string, to compare by. `ordered=True` keeps the dict order (a comparison of
    two files that must also agree on the order their keys were written in)."""
    return json.dumps(value, ensure_ascii=False, sort_keys=not ordered, separators=(",", ":"), default=str)


# --- expectation_changes[]: the record of a test that changed after its red run ---------------

def _record_functions(record) -> list:
    """Every function one record names (`functions`, and `function` as its one-element form).
    The reader is `s5_precheck.record_functions`; this is the same rule for a writer that must
    not import the detector's whole module to merge a row."""
    if not isinstance(record, dict):
        return []
    names = [str(n) for n in record["functions"]] if isinstance(record.get("functions"), list) else []
    if isinstance(record.get("function"), str) and record["function"] not in names:
        names.append(record["function"])
    return names


def _record_key(record) -> tuple:
    """(sorted functions, red_attempt, green_attempt) — `green_attempt` is None for a red whose
    test was renamed, moved or deleted, so it never had a green."""
    green = record.get("green_attempt") if isinstance(record, dict) else None
    red = record.get("red_attempt") if isinstance(record, dict) else None
    return (tuple(sorted(set(_record_functions(record)))), str(red or ""), str(green) if green else None)


AUTHOR_FIELDS = ("then_refs", "what_changed", "reason")  # the author's words about a change
CRITIC_FIELDS = ("critic_verdict", "critic_note")
# The verdict whose note is not optional: `could_not_judge` leaves the window unresolved, and the
# conductor's record of it (`unresolved` + a reason) takes its reason from the critic's note.
NOTE_REQUIRED_VERDICTS = ("could_not_judge",)
LISTED_KEYS = 6  # how many existing record keys a refusal lists before "and N more"


def _same_runs(one: tuple, other: tuple) -> bool:
    return one[1] == other[1] and one[2] == other[2]


def _hosts(key: tuple, keys) -> list:
    """The keys of the records that hold EVERY function of `key` and more, for the same red and
    green attempt. A critic who judges one test of a record that names three writes
    `function: a` against `functions: [a, b, c]`; that is the record meant, not a new one."""
    wanted = set(key[0])
    if not wanted:
        return []
    return [k for k in keys if _same_runs(k, key) and wanted < set(k[0])]


def _key_text(key: tuple) -> str:
    return (f"functions {json.dumps(list(key[0]), ensure_ascii=False)}, red_attempt "
            f"{json.dumps(key[1])}, green_attempt {json.dumps(key[2])}")


def _listed(keys) -> str:
    keys = list(keys)
    if not keys:
        return "the manifest holds no expectation_changes[] record yet"
    # `; ` between the keys: a key's own text holds commas (`functions [...], red_attempt ..., green_attempt ...`)
    return DV.named([_key_text(k) for k in keys], LISTED_KEYS, where="the manifest's expectation_changes[]", sep="; ")


def _problems_text(task_root: Path, name: str, problems: list) -> str:
    """The problems of a refused fragment in ONE line: all of them, `; `-joined, up to the ceiling of the one-line
    renderer; past it the count that is left and the file that holds the whole list, `state/findings/manifest-put-<name>.txt`
    under the story folder (written by this very call). The automator repairs every problem in one turn, not six."""
    return DV.joined(problems, noun="problem", full_path=task_root / "state" / "findings" / f"manifest-put-{name}.txt")


def then_remainder_problems(task_root: Path, fragment: dict) -> list:
    """Why the Then-level hand-off rows of a fragment are malformed, one sentence per row ([] when none is). Only rows
    the contract classes as a Then left with its owner are judged: a case with a whole-case `unresolved[]` row (in the
    fragment or already in the manifest) keeps its per-clause echo rows as they are (`contract.then_remainder_rows`).
    A manifest that cannot be read adds nothing to the whole-case list, which can only make this check stricter."""
    rows = fragment.get("then_bindings") if isinstance(fragment, dict) else None
    if not isinstance(rows, list) or not rows:
        return []
    try:
        stored = json.loads(C.artifact(Path(task_root), "automation-manifest.json").read_text(encoding="utf-8"))
        stored = stored.get("unresolved") if isinstance(stored, dict) else None
    except Exception:
        stored = None
    own = fragment.get("unresolved")
    pooled = [u for u in (stored if isinstance(stored, list) else []) + (own if isinstance(own, list) else [])
              if isinstance(u, dict)]
    out = []
    for row in C.then_remainder_rows({"unresolved": pooled, "then_bindings": rows}):
        errors = C.then_remainder_errors(row)
        if errors:
            out.append(f"then_bindings row {row.get('case')} Then {row.get('then')!r} is a Then left with its owner "
                       "and is malformed: " + "; ".join(errors))
    return out


def unresolved_reason_conflicts(fragment) -> list:
    """Why a fragment's `unresolved[]` holds two rows of ONE case with DIFFERENT reasons, one sentence per case ([] when
    none does) (HF2-3, F4). `merge` keeps one row per case inside a fragment - the later wins, and two `blocked_by_env`
    rows are united - so `[{TC-5, contradicts_requirement}, {TC-5, blocked_by_env}]` silently lost the requirement row
    (the stand row won). A reason is a statement about the case; two of them cannot both stand, and the author is told to
    choose. The case is the key `merge` groups by (`_case`), so the refusal protects exactly the collision `merge` would
    resolve by "later wins". The same reason twice is NOT a conflict (the later wins, as always; two `blocked_by_env`
    rows unite). A row with no reason counts as the reason `(none)`: it differs from a named one, so the fragment is
    refused rather than guessed at. Called by `run` BEFORE the commit and never by `merge`: `merge` replays journals
    already committed, and an old event with two reasons must still fold as it did (`fold` never reports it)."""
    rows = fragment.get("unresolved") if isinstance(fragment, dict) else None
    reasons: dict = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and _case(row):
            seen = reasons.setdefault(_case(row), [])
            reason = str(row.get("reason") or "").strip() or "(none)"
            if reason not in seen:
                seen.append(reason)
    return [f"unresolved[] holds rows of {case} with different reasons ({' and '.join(seen)}) in one fragment, and a "
            "case keeps one row per fragment - the later row would win and the other reason would be lost; send one row "
            "per case: the stand row OR the requirement row; `retracted_unresolved` drops the old one"
            for case, seen in reasons.items() if len(seen) > 1]


def retracted_unresolved_lines(before: dict, fragment: dict) -> list:
    """What `run` prints about a retraction, from the manifest as it stood BEFORE the send: one line per dropped row with
    its case, its reason and its slice and `thens` (a row another instance still needs goes whole, and the line is the
    place a person sees that), or a line saying no row stood when the fragment's own green test had moved the case. []
    when the fragment retracts nothing."""
    asked = (fragment or {}).get("retracted_unresolved")
    out = []
    for key in dict.fromkeys(str(k).strip() for k in (asked if isinstance(asked, list) else []) if str(k).strip()):
        rows = [r for r in (before or {}).get("unresolved") or [] if isinstance(r, dict) and _same_case(key, _case(r))]
        if not rows:
            out.append(f"unresolved row of {key} retracted: no row of it stood before this send")
        for row in rows:
            named = [f"{k} {json.dumps(row[k])}" for k in (*C.UNRESOLVED_SLICE_KEYS, C.UNRESOLVED_THENS_KEY) if row.get(k)]
            out.append(f"unresolved row of {_case(row)} retracted: reason {row.get('reason') or '(none)'}, "
                       + (", ".join(named) if named else "no slice (the whole case)"))
    return out


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _verdicts() -> list:
    """The critic's verdict words, from `handoffs/vocabulary.yaml`; [] when that file cannot be
    read, and then the word is not checked here (a half-installed tree writes what it was sent)."""
    try:
        import handoff
        return handoff.allowed(VERDICTS_LIST)
    except Exception:
        return []


def expectation_change_problems(incoming, existing=None) -> list:
    """Why a fragment's `expectation_changes` is malformed — one FR-1 sentence per problem, each
    naming the field, what it expected and how to write it. [] when it is well formed, and for
    an absent key or an empty list (a no-op).

    A NEW row (one whose key no earlier row, in the manifest or in this fragment, has) must carry
    the author's three fields; a row that patches an existing one may carry any subset, which is
    how the critic adds a verdict without retyping the author's reason. Nothing here judges what
    the words say: presence and shape only (FR-12)."""
    if incoming is None:
        return []
    if not isinstance(incoming, list):
        return ["`expectation_changes` must be a list of objects, one per changed test "
                "(or per set of tests that share one pair of runs)"]
    known: list = []
    known_rows: dict = {}  # key -> the record, the first one of a key (the merge's own rule)
    for row in existing or []:
        if isinstance(row, dict) and _record_key(row) not in known:
            known.append(_record_key(row))
            known_rows[_record_key(row)] = row
    out: list = []
    for i, row in enumerate(incoming):
        at = f"expectation_changes[{i}]"
        if not isinstance(row, dict):
            out.append(f"{at} is not an object: write {{\"function\": <key>, \"red_attempt\": ..., "
                       "\"green_attempt\": ..., \"then_refs\": [{\"case\": ..., \"then\": <number>}], "
                       "\"what_changed\": ..., \"reason\": ...}")
            continue
        bad = len(out)
        if "function" in row and not _text(row["function"]):
            out.append(f"{at}.`function` must be a non-empty string (the key `s5_precheck.py` "
                       "prints in its finding)")
        if "functions" in row and (not isinstance(row["functions"], list) or not row["functions"]
                                   or not all(_text(n) for n in row["functions"])):
            out.append(f"{at}.`functions` must be a non-empty list of strings (the keys "
                       "`s5_precheck.py` prints in its findings)")
        if "function" not in row and "functions" not in row:
            out.append(f"{at} is missing `function` (a string) or `functions` (a list of strings): "
                       "copy the key from the `changed-after-red` finding of s5_precheck.py")
        if not _text(row.get("red_attempt")):
            out.append(f"{at}.`red_attempt` must be a non-empty string: the run attempt in which the "
                       "test went red, as the finding prints it")
        if "green_attempt" not in row:
            out.append(f"{at} is missing `green_attempt`: the attempt in which it passed, as the "
                       "finding prints it (null when the test was renamed, moved or deleted)")
        elif row["green_attempt"] is not None and not _text(row["green_attempt"]):
            out.append(f"{at}.`green_attempt` must be a non-empty string, or null when the test was "
                       "renamed, moved or deleted after its red run")
        if len(out) > bad:
            continue  # a row that names no function or run cannot be told from a new one
        key = _record_key(row)
        hosts = [] if key in known else _hosts(key, known)
        if key not in known and len(hosts) != 1 \
                and any(f in row for f in CRITIC_FIELDS) and not any(f in row for f in AUTHOR_FIELDS):
            # a verdict that joins no record: say which key was asked and which exist, instead of
            # three complaints about author fields the critic has no business writing
            out.append(
                f"{at} is a verdict for a record that cannot be told: the key ({_key_text(key)}) "
                + (f"is inside {len(hosts)} records, and a patch must pick ONE" if hosts
                   else "matches no record, and a patch with no author fields can only add to one")
                + f". Existing records: {_listed(known)}. Write the `function`/`functions`, "
                "`red_attempt` and `green_attempt` of ONE of them (or some of its functions)")
            continue
        new = key not in known and len(hosts) != 1
        if new:
            known.append(key)
        if "then_refs" in row or new:
            refs = row.get("then_refs")
            if not isinstance(refs, list) or not refs or not all(isinstance(r, dict) for r in refs):
                out.append(f"{at}.`then_refs` must be a non-empty list of objects "
                           "{\"case\": \"TC-001\", \"then\": 2}: the Then clause(s) the changed value "
                           "belongs to")
            else:
                for j, ref in enumerate(refs):
                    if not _text(ref.get("case")):
                        out.append(f"{at}.then_refs[{j}].`case` must be a non-empty string, "
                                   "the case id")
                    then = ref.get("then")
                    if isinstance(then, bool) or not isinstance(then, int):
                        out.append(f"{at}.then_refs[{j}].`then` must be an integer, the number of "
                                   f"the Then clause in the case file (got {then!r})")
        for field, hint in (("what_changed", "what you changed in the test, before -> after"),
                            ("reason", "why the approved case allows it")):
            if (field in row or new) and not _text(row.get(field)):
                out.append(f"{at}.`{field}` must be a non-empty string: {hint}")
        if "critic_verdict" in row:
            allowed = _verdicts()
            if not _text(row["critic_verdict"]) or (allowed and row["critic_verdict"] not in allowed):
                out.append(f"{at}.`critic_verdict` must be one of {allowed} "
                           f"(got {row['critic_verdict']!r})")
        if "critic_note" in row and not isinstance(row["critic_note"], str):
            out.append(f"{at}.`critic_note` must be a string: what the critic read")
        elif ("critic_verdict" in row or "critic_note" in row):
            # the note IS the reason the window is then recorded unresolved (R14a): a verdict that
            # says "I could not tell" and not why leaves the conductor with nothing to write. It is
            # the MERGED record that must carry it: a patch that blanks the note of a recorded
            # `could_not_judge` would otherwise leave exactly that (t-149, critic).
            verdict, note = _merged_critic_fields(row, known_rows)
            if verdict in NOTE_REQUIRED_VERDICTS and not _text(note):
                out.append(f"{at}.`critic_note` is required with `critic_verdict: {verdict}`: "
                           "write what you could not tell and why: the conductor records the window as "
                           "unresolved with the reason")
    return out


def _merged_critic_fields(row: dict, records: dict) -> tuple:
    """`(critic_verdict, critic_note)` the record will hold after `_merge_expectation_changes` takes
    `row`: the patch's own fields over the record it lands on (its own key, or the ONE record that
    holds its functions), a changed verdict without a note of its own taking the old note away, and
    changed author words taking the verdict and its note away. A row that lands on no record stands
    alone."""
    key = _record_key(row)
    hosts = [] if key in records else _hosts(key, list(records))
    old = records.get(key) or (records[hosts[0]] if len(hosts) == 1 else {})
    verdict = row["critic_verdict"] if "critic_verdict" in row else old.get("critic_verdict")
    if "critic_note" in row:
        note = row["critic_note"]
    elif "critic_verdict" in row and old.get("critic_verdict") and row["critic_verdict"] != old.get("critic_verdict"):
        note = None
    else:
        note = old.get("critic_note")
    if old.get("critic_verdict") and "critic_verdict" not in row \
            and any(f in row and row[f] != old.get(f) for f in AUTHOR_FIELDS):
        verdict, note = None, None
    return verdict, note


def _merge_expectation_changes(merged: dict, fragment: dict, summary: dict) -> None:
    """Merge the fragment's records by `_record_key`; fields a patch omits survive. An empty
    list is a no-op — not even the key is created. Never raises: this runs inside the projection
    of every event ever committed, and a projection that raises poisons the story
    (`event_store.commit`); the refusal of a malformed row is `expectation_change_problems`,
    before the commit."""
    incoming = [row for row in (fragment or {}).get("expectation_changes") or [] if isinstance(row, dict)] \
        if isinstance((fragment or {}).get("expectation_changes"), list) else []
    if not incoming:
        return
    rows = [row for row in merged.get("expectation_changes") or []] \
        if isinstance(merged.get("expectation_changes"), list) else []
    index: dict = {}
    for at, row in enumerate(rows):
        if isinstance(row, dict):
            index.setdefault(_record_key(row), at)
    for patch in incoming:
        key = _record_key(patch)
        hosts = [] if key in index else _hosts(key, list(index))
        if key in index or len(hosts) == 1:
            # the record's own key, or — a critic judging some of a record's functions — the ONE
            # record that holds them all. The record keeps its whole list of functions.
            target = index[key] if key in index else index[hosts[0]]
            old = rows[target]
            fields = patch if key in index else {k: v for k, v in patch.items()
                                                 if k not in ("function", "functions")}
            new = {**old, **fields}
            # A verdict judged the author's words as they were: when those words change, the
            # verdict and its note go, unless the same patch carries its own verdict.
            if old.get("critic_verdict") and "critic_verdict" not in fields \
                    and any(f in fields and fields[f] != old.get(f) for f in AUTHOR_FIELDS):
                new.pop("critic_verdict", None)
                new.pop("critic_note", None)
                summary.setdefault("verdicts_dropped", []).append(", ".join(_record_functions(old)))
            elif old.get("critic_verdict") and "critic_verdict" in fields and "critic_note" not in fields \
                    and fields["critic_verdict"] != old.get("critic_verdict"):
                # a note explained the OLD verdict; left beside the new one it would say something
                # the critic no longer says (t-149, F4)
                new.pop("critic_note", None)
            summary["duplicate" if new == old else "replaced"] = \
                summary.get("duplicate" if new == old else "replaced", 0) + 1
            rows[target] = new
        else:
            index[key] = len(rows)
            rows.append(dict(patch))
            summary["added"] += 1
    merged["expectation_changes"] = rows


def _merge_entry(old: dict, patch: dict) -> dict:
    """A review/result patch changes only the fields it owns; it cannot erase identity."""
    result = dict(old or {})
    result.update(patch or {})
    # Links are a many-to-many relationship. A patch may add links but must use an
    # explicit replacement field to remove them.
    for key in ("case_links", "cases"):
        if key in old and key in patch and key not in patch.get("replace_fields", []):
            combined = list(old.get(key) or [])
            for value in patch.get(key) or []:
                if value not in combined:
                    combined.append(value)
            result[key] = combined
    # A CaseVersion is the case's CURRENT pin, not a history of versions: a repair that
    # re-pins a case must not leave the stale version beside the new one, or the delivery stage
    # keeps reading the old pin and asks for the same repair again (a legacy story looped on
    # this for thirteen dispatches). Applied whenever the patch carries the field, so replaying
    # a journal written by the accumulating code heals the story at its next write.
    key = "case_version_links"
    if key in patch and key not in patch.get("replace_fields", []):
        incoming, standing = patch.get(key), (old or {}).get(key) or []
        if isinstance(incoming, list) and isinstance(standing, list):
            result[key] = _replace_links(standing, incoming)
    return result


def _link_key(link) -> tuple:
    """(area, case id) of a `case_version_links[]` entry; ('', '') when it names no case.
    Only `contract` knows how a case key is spelled, so the entry is read through it."""
    if not isinstance(link, dict):
        return "", ""
    return C.split_case_key(C.case_link_key(link))


def _replaces(incoming, standing) -> bool:
    """Does the `incoming` link supersede the `standing` one? The rule is NOT `case_matches`:
    that one is symmetric, and here a bare id must not wipe the area's own link.
      - a bare incoming id replaces BARE links of that id only;
      - an area-qualified incoming link replaces the links of the SAME area and the bare ones
        (a record written by 0.7.x names no area, and this is the pin that supersedes it);
      - a link of another area, a link with no case key, and a non-dict entry are never replaced."""
    area, case = _link_key(incoming)
    old_area, old_case = _link_key(standing)
    if not case or case != old_case:
        return False
    return area == old_area or (bool(area) and not old_area)


def _replace_links(standing: list, incoming: list) -> list:
    """The standing links minus every case an incoming link supersedes, then the incoming links
    in their own order. Folded link by link, so two incoming links for one case leave the last,
    and merging the same patch again changes nothing. Incoming `[]` removes nothing; an entry
    that names no case (or is not a dict) accumulates once, as every link did before."""
    out = list(standing)
    for link in incoming:
        if _link_key(link)[1]:
            out = [other for other in out if not _replaces(link, other)]
            out.append(link)
        elif link not in out:
            out.append(link)
    return out


def _writer_tests(incoming_tests) -> bool:
    """Is this the writer's re-run? Only `manifest_from_tests.py` writes `generated_from` on a row (`WRITER_MARK`), so a
    fragment whose `tests[]` carries it is the writer's, and one without `tests[]` (only `qa_unresolved` rows) is not."""
    return any(WRITER_MARK in e for e in incoming_tests)


def _in_unit(row: dict, sent: dict) -> bool:
    """Does `row` stand in the unit `sent` names? The unit is (case, `instance_id`): a bare id matches any area
    (`_same_case`) and a null `instance_id` is the unit of its own, not a wildcard."""
    return (_same_case(_case(row), _case(sent))
            and str(row.get("instance_id") or "").strip() == str(sent.get("instance_id") or "").strip())


def _twin(row: dict, rows, taken=()) -> int:
    """The index in `rows` of the unclaimed row that says the same Then of the same unit as `row`, -1 when none does. A
    `then` that reads as none (`contract.then_number` 0) is the twin of nothing: the row is replaced or removed, never paired
    by a guess."""
    number = C.then_number(row.get("then"))
    return next((i for i, other in enumerate(rows)
                 if i not in taken and isinstance(other, dict) and number and C.then_number(other.get("then")) == number
                 and _in_unit(row, other)), -1)


def _then_words(row: dict) -> str:
    """`<case> Then <n> on <instance|none>`: a `then_bindings` row in the words `run` prints for one taken out. The Then is
    read through `contract.then_number`; one that reads as none is `?`."""
    return (f"{_case(row) or '?'} Then {C.then_number(row.get('then')) or '?'} on "
            f"{str(row.get('instance_id') or '').strip() or 'none'}")


def _retract_names(fragment) -> list:
    """The key names the fragment's `retract` lists, in order, with repeats. Pure; never raises: `merge` replays every event ever
    committed, so a `retract` that is no list, or a member that is no string, names nothing here (`retract_problems` refuses it in `run`)."""
    names = (fragment or {}).get(RETRACT_KEY) if isinstance(fragment, dict) else None
    return [name for name in names if isinstance(name, str)] if isinstance(names, list) else []


def _retract_keys(fragment) -> set:
    """The set of the key names the fragment's `retract` lists (`_retract_names`)."""
    return set(_retract_names(fragment))


def retract_problems(fragment) -> list:
    """What is wrong with the fragment's `retract`, one sentence each ([] when it is absent, `[]`, or well formed). `run`
    refuses on it BEFORE the commit; `merge` ignores an invalid one (an old journal never raises). A retract of `tests`,
    `unresolved` or `obligation_bindings` is refused with the door each has already: those keys are never replaced whole."""
    if not isinstance(fragment, dict) or RETRACT_KEY not in fragment:
        return []
    names = fragment[RETRACT_KEY]
    if not isinstance(names, list):
        return [f"`retract` must be a list of top-level key names, e.g. [\"then_bindings\"]; this one is {type(names).__name__}"]
    out = []
    for name in names:
        if not isinstance(name, str):
            out.append(f"`retract` member {_key(name)} is not a key name: write the name as a string, e.g. \"then_bindings\"")
        elif name in RETRACT_DOORS:
            out.append(f"`retract` names `{name}`, which is never replaced whole: take its rows out with "
                       f"`{RETRACT_DOORS[name]}` instead")
    return out


def retract_idle_lines(fragment) -> list:
    """One line per key `retract` names that the fragment does not send: nothing was replaced, so nothing changed (a retract
    never deletes what it did not replace). [] when none. Pure."""
    sent = fragment if isinstance(fragment, dict) else {}
    return [f"retract names {name}, which this fragment does not send: nothing changed"
            for name in dict.fromkeys(_retract_names(sent)) if name not in sent and name not in RETRACT_DOORS]


ACCUMULATE_UNITS = {"deviations": "test"}      # a list's unit key when its rows carry no `id`: a re-sent row of the same unit replaces the old one


def _accumulate(stored: list, incoming: list, unit_key: str = "") -> list:
    """A top-level list no family names, merged with the fragment's (RN1-22, FK-6): an incoming dict with a non-empty `id` (or,
    for a list in `ACCUMULATE_UNITS`, a non-empty unit key - `deviations` rows are `{test, from, planned, reason}`) replaces the
    stored row with that identity, in place; any other row is added unless an equal one (`_key`) already stands. A corrected
    `reason` for the same `test` therefore stands ALONE, not beside the old one (t-1748 Q3).
    LOCAL-1 run 3: `deviations` and `plan_remarks` of an earlier window were lost to a whole-list replace. Pure."""
    out = list(stored)
    for row in incoming:
        field = "id" if isinstance(row, dict) and row.get("id") else unit_key
        rid = row.get(field) if isinstance(row, dict) and field else None
        if rid:
            at = next((i for i, other in enumerate(out) if isinstance(other, dict) and other.get(field) == rid), -1)
            if at >= 0:
                out[at] = row
                continue
        if all(_key(row) != _key(other) for other in out):
            out.append(row)
    return out


def _merge_then_bindings(existing, incoming: list, writer: bool, retract: bool = False, tests=(), unresolved=()) -> tuple:
    """(the `then_bindings` array after the fragment, the rows it took out, the rows it kept though it named their unit),
    t-085 5a-K1 (FA-16 (b), FB-1 (b)); RN1-22 (LOCAL-1 run 3, 03.11.2026) limits both paths.

    The writer (`manifest_from_tests.py`, `writer`) sends the array of the cases it wrote about, so its array replaces what
    it WROTE ABOUT and nothing else: the old rows in its scope - bound to any spelling of an instance in its `tests[]`
    (`tests`), or of a case in its own `then_bindings` or `unresolved[]` rows (`unresolved`) - are replaced by the incoming
    rows (a test that moved from TC-007 to TC-008 leaves no covered TC-007 row on it behind), and every other old row stays,
    before the incoming ones. A hand fragment whose `tests[]` row was COPIED with `generated_from` (the role's) takes this
    path too; before the scope it replaced the whole array and 26 of 29 rows were lost. A hand fragment (a role's, or the
    conductor's) is merged BY UNIT, the unit being (case, `instance_id`) with a null `instance_id` a unit of its own: the
    rows of a unit the fragment names are replaced by the rows it sends (a row of the same Then stands where it stood), and
    the rows of every unit it does not name stay - a blocked-row patch for TC-005 on one test must not take the covered
    rows of TC-005 on another. A Then of a named unit the fragment did NOT send stays too (returned third, `run` prints it)
    unless the fragment's `retract` names `then_bindings` (`retract`): then it goes, as it did before. The error direction
    is to keep: removal happens only by an explicit sign. The rows taken out are returned for `run` to print (P21: no row is
    lost silently). An empty `incoming` names no unit and takes nothing out from a hand fragment. Pure; never raises: it
    runs inside the projection of every event ever committed, and a row that is no object is kept."""
    old = list(existing) if isinstance(existing, list) else []
    if writer:
        worn = {spelling for test in tests if isinstance(test, dict) for spelling in _spellings(test)}
        cases = [case for case in (*(_case(row) for row in incoming), *(_case(row) for row in unresolved or ())) if case]

        def mine(row) -> bool:
            return isinstance(row, dict) and (str(row.get("instance_id") or "").strip() in worn
                                              or _matches_any(_case(row), cases))
        return ([row for row in old if not mine(row)] + list(incoming),
                [row for row in old if mine(row) and _twin(row, incoming) < 0], [])
    sent = [row for row in incoming if isinstance(row, dict)]
    taken: set = set()
    out, removed, kept = [], [], []
    for row in old:
        if not isinstance(row, dict) or not any(_in_unit(row, s) for s in sent):
            out.append(row)
            continue
        twin = _twin(row, incoming, taken)
        if twin >= 0:
            taken.add(twin)
            out.append(incoming[twin])      # the sent row stands where the old one stood
        elif retract:
            removed.append(row)
        else:
            out.append(row)
            kept.append(row)
    return out + [row for i, row in enumerate(incoming) if i not in taken], removed, kept


def _worn(manifest: dict) -> set:
    """Every spelling any `tests[]` row of `manifest` answers to (`_identity`, and the canonical id)."""
    return {alias for entry in (manifest or {}).get("tests") or [] if isinstance(entry, dict)
            for alias in _spellings(entry)}


def _dropped_spellings(before: dict, spellings) -> set:
    """`spellings` and, for each `tests[]` row of `before` (the manifest as it stood before this merge) that answers to one
    of them, EVERY spelling that row answered to (`_spellings`: its canonical id, the 0.7.7 case-prefixed ids, the bare id,
    the selector hash). The Lead's decision on HF3-2 (critic t-1276, Q2): a Then row bound to ANY alias of a dropped row goes
    with it, not only to the spelling that was named. `_retire_then_rows` still keeps every spelling a surviving row answers to."""
    named = {str(s).strip() for s in spellings or () if str(s).strip()}
    out = set(named)
    for entry in (before or {}).get("tests") or []:
        if isinstance(entry, dict) and _spellings(entry) & named:
            out |= _spellings(entry)
    return out


def _retire_then_rows(merged: dict, spellings, summary: dict) -> list:
    """Take out of `merged["then_bindings"]` the rows bound to a spelling this merge retired, and return them.

    A retracted instance used to leave its Then rows behind (TP2-2406, seq 115, 26.10.2026): the two rows on the
    old spelling stood beside the two on the new one, a later send of the old name landed as a ghost `tests[]` row, and
    that ghost made the old spelling look covered, so `s5_precheck` never named the rows bound to nothing (`unlinked-`).
    A spelling is retired when this fragment asked for its retraction or when this merge removed it (`_current_spelling`,
    `_retract_aliases`) - not "first written into the history", so the door that retracts an id again also takes its
    rows. It takes rows only while NO `tests[]` row of the merged manifest still answers to the spelling: the
    0.7.7 spelling of a row that lives on in the current one keeps its Thens. Position: BEFORE this fragment's own
    `then_bindings` merge, so a row the fragment sends stands (`run` refuses a fragment that sends a Then to an id it
    also retracts; a replay of an older journal keeps such a row). Pure; never raises: it runs inside the projection of
    every event ever committed, and a `then_bindings` that is no array is left as it is."""
    gone = {str(s).strip() for s in spellings or () if str(s).strip()} - _worn(merged)
    rows = merged.get("then_bindings")
    if not gone or not isinstance(rows, list):
        return []
    kept, taken = [], []
    for row in rows:
        (taken if isinstance(row, dict) and str(row.get("instance_id") or "").strip() in gone else kept).append(row)
    if taken:
        merged["then_bindings"] = kept
        summary["then_rows_retired"] = summary.get("then_rows_retired", 0) + len(taken)
    return taken


def _then_merge(existing, fragment: dict) -> tuple:
    """`_merge_then_bindings` over a fragment that sends a `then_bindings` array: the one place the writer/hand decision, the
    `retract` sign and the writer's scope are read off the fragment (`_merge` and the print's fallback both ask it)."""
    tests = [e for e in (fragment or {}).get("tests") or [] if isinstance(e, dict)]
    unresolved = [e for e in (fragment or {}).get("unresolved") or [] if isinstance(e, dict)]
    return _merge_then_bindings(existing, fragment["then_bindings"], _writer_tests(tests),
                                "then_bindings" in _retract_keys(fragment), tests, unresolved)


def _then_trail(before: dict, fragment: dict) -> dict:
    """The `trail` of the merge `run` is about to print from: `then_retired`, `then_taken`, `then_kept`. The same merge the
    projection runs, so a line and the file cannot disagree. A merge that raises here (a `before` older than the commit that
    just landed) falls back to the array alone: the print is information, never a reason to fail."""
    trail: dict = {}
    try:
        _merge(copy.deepcopy(before or {}), fragment, trail)
    except Exception:
        trail = {}
        if isinstance((fragment or {}).get("then_bindings"), list):
            _, trail["then_taken"], trail["then_kept"] = _then_merge((before or {}).get("then_bindings"), fragment)
    return trail


def removed_then_lines(before: dict, fragment: dict) -> list:
    """What `run` prints about the `then_bindings` rows this send took out of the manifest as it stood BEFORE it: one
    `<case> Then <n> on <instance|none>` per row ([] when it takes nothing out) - the rows bound to a spelling the send
    retracted (`_retire_then_rows`) and the rows of a unit its `then_bindings` replaced under `retract` or inside the
    writer's scope (`_merge_then_bindings`)."""
    trail = _then_trail(before, fragment)
    return [_then_words(row) for row in (*trail.get("then_retired", ()), *trail.get("then_taken", ()))]


def kept_then_lines(before: dict, fragment: dict) -> list:
    """What `run` prints about the Thens of a unit the fragment named but did not send, which STAY (RN1-22, FK-1 a): one
    line per row, the door to take it out in the words. [] when none. The same trail as `removed_then_lines`."""
    return [f"kept {_then_words(row)} (not in this fragment; to take it out send \"{RETRACT_KEY}\": [\"then_bindings\"] "
            "with the unit's full rows)" for row in _then_trail(before, fragment).get("then_kept", ())]


def moved_out_lines(before: dict, fragment: dict) -> list:
    """What `run` prints about the `tests[]` rows this send moved out of the manifest because their case became wholly
    unresolved (EP1-39): one line per row, from the `trail` of the same merge the projection runs (so the print and the file
    cannot disagree; the lines add up to the `moved` of `tests[]`). [] when it moves none. The line says WHY and the door
    (name the instances) - the loss used to be silent. A merge that raises here falls back to [] (information, never a failure)."""
    trail: dict = {}
    try:
        _merge(copy.deepcopy(before or {}), fragment, trail)
    except Exception:
        return []
    return [f"moved out of tests[]: {row['instance_id']} (case {row['case']} is now wholly unresolved because the row names "
            "no instance_ids/partitions; if it is about particular Thens, name the instances: instance_ids: [...])"
            for row in trail.get("moved_out", ())]


def critic_approval_problems(fragment, stored_tests) -> list:
    """`tests[]` rows of a fragment that turn a stored `critic_verdict: unverified` into `approved` with no `critic_note`
    (F-11 a): one sentence per row, [] when none does. An `unverified` verdict is a receipt that lacks a probe - a tooling
    gap; the flip with nothing said turns the gap into an approval. A non-empty `critic_note` passes: whether it is
    lawful is not judged here. Called by `run` before the commit, never by `merge` (old journals replay as they were)."""
    rows = fragment.get("tests") if isinstance(fragment, dict) else None
    out = []
    for i, row in enumerate(rows if isinstance(rows, list) else []):
        if not isinstance(row, dict) or row.get("critic_verdict") != "approved" or _text(row.get("critic_note")):
            continue
        ids = set(_identity(row))
        if any(isinstance(s, dict) and s.get("critic_verdict") == "unverified" and ids.intersection(_identity(s))
               for s in stored_tests or []):
            out.append(f"tests[{i}] approves over a stored unverified verdict with no critic_note: say what changed (a "
                       "probe result, a re-read); a receipt that lacks a probe is a tooling gap, not an approval")
    return out


def _changed_assertion_ids(fragment, stored_tests) -> list:
    """`(index, row, id)` of the `tests[]` rows of the fragment that SEND an `assertion_id` the stored row of the same instance
    does not already hold (a row with no stored twin is new, so its id is changed too). A row that re-sends its stored id, or
    carries none, is not listed: an old manifest is not broken by an unrelated edit of another field of its row."""
    rows = fragment.get("tests") if isinstance(fragment, dict) else None
    stored = [t for t in (stored_tests if isinstance(stored_tests, list) else []) if isinstance(t, dict)]
    out = []
    for at, row in enumerate(rows if isinstance(rows, list) else []):
        sent = row.get("assertion_id") if isinstance(row, dict) else None
        if not isinstance(sent, str) or not sent.strip():
            continue
        spellings = _spellings(row)
        if any(spellings & _spellings(t) and str(t.get("assertion_id") or "").strip() == sent.strip() for t in stored):
            continue
        out.append((at, row, sent.strip()))
    return out


def assertion_line_problems(fragment, stored_tests, project) -> tuple:
    """`(problems, notes)` for the `assertion_id` of every `tests[]` row this fragment writes or changes (TR2-1, AR-13/AR-29).

    A DATA cross-reference of an id to the file it names, not a judgment of the test: the id `<file>:<line>` must stand on a
    line that holds a check by the ONE reader of "what is a check on this line", `probe_by_code.check_on_line` (a check counts
    when it starts on the line or its statement spans it; a line that calls a helper is not refused). A line with no check is a
    problem naming the line and the nearest check below (the door), or that none follows. An UNKNOWN is never a refusal and
    never a silent pass (FR-59): an id not of the `<file>:<line>` form, a file outside the project root or unreadable, a
    suffix with no reader entry, a file that does not parse, a line that calls a helper whose check this file does not hold
    -> one note per such id, which `run` prints as one line. Pure over its arguments plus the read of the named files.
    `probe_by_code` is imported only when a changed id exists: the cost is paid only then."""
    changed = _changed_assertion_ids(fragment, stored_tests)
    if not changed:
        return [], []
    import probe_by_code as PBC
    root = Path(project).resolve()
    problems, notes = [], []
    for at, row, sent in changed:
        shown = f"tests[{at}].assertion_id {sent}"
        parsed = PBC._ASSERTION_ID.match(sent)
        if not parsed:
            notes.append(f"{shown} is not of the form <file>:<line>")
            continue
        name, line = parsed.group("file").replace("\\", "/"), int(parsed.group("line"))
        try:
            path = (root / name).resolve()
            path.relative_to(root)
        except (ValueError, OSError):
            notes.append(f"{shown} names a file outside the project root")
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            notes.append(f"{shown} names a file that cannot be read ({type(exc).__name__})")
            continue
        try:
            entry = PBC._reader_entry(PBC.parse_node(f"{name}::x", root))
            facts = PBC.check_on_line(data, name, entry, line)
        except (ValueError, RecursionError) as exc:       # a Refusal of the reader: no entry for the suffix, not UTF-8, no parse
            notes.append(f"{shown} names a file the reader cannot read ({str(exc).split('.')[0][:120]})")
            continue
        if facts["found"] is not None:
            continue
        if facts["calls_helper"]:
            notes.append(f"{shown} is a line that calls `{facts['calls_helper']}(`: the check it holds is not in this file")
            continue
        below = facts["nearest_below"]
        door = (f"the nearest check below it starts at line {below['line']}: the id is `{name}:{below['line']}` when that is "
                "the Then's check" if below else f"this test has no check below line {line}")
        problems.append(f"{shown}: line {line} of {name} holds no check (none starts or spans there), and the id is the line "
                        f"where the Then's check starts; {door}")
    return problems, notes


def merge(current: dict, fragment: dict) -> tuple:
    """(merged manifest, summary counts). Pure: the caller owns the file."""
    return _merge(current, fragment, {})


def _merge(current: dict, fragment: dict, trail: dict) -> tuple:
    """`merge`, and into `trail` the rows it took out of `then_bindings` - `then_retired` (bound to a retired spelling)
    and `then_taken` (a unit the fragment's array replaced) - for `removed_then_lines`: one computation, so the printed
    line cannot disagree with the projection."""
    merged = dict(current or {})
    spent: list = []        # the spellings THIS merge retired by itself: `_current_spelling` and `_retract_aliases`
    summary = {"replaced": 0, "added": 0, "kept": 0, "appended": 0, "moved": 0}

    # the drop loop used to run over `unresolved[]` only, while its own comment claimed
    # both. So a green `tests[]` entry never cleared the case's `unresolved[]` row, and on
    # TP1-15045 TC-013 was "not run" and green at the same time. Both directions are
    # computed here, once, from the fragment — a row about a named PARTITION is not a
    # statement about the whole case and survives either way.
    incoming_unresolved = [e for e in (fragment or {}).get("unresolved") or [] if isinstance(e, dict)]
    incoming_tests = [e for e in (fragment or {}).get("tests") or [] if isinstance(e, dict)]
    _refuse_colliding_ids(incoming_tests)
    unresolved_cases = {_case(e) for e in incoming_unresolved if _case(e)}
    # A test entry moves a case out of `unresolved[]` only when it says the case now runs —
    # EVERY case it covers, not only the one its `case` field spells: one consolidated test
    # green for TC-003/004/005 leaves no unresolved row behind for the other two.
    drop_from_unresolved = {case for e in incoming_tests
                            if str(e.get("status") or "green") == "green"
                            for case in _links(e)}
    # A row naming only Thens of a case that RAN speaks about those Thens, not the case: the test rows that ran stay
    # (EP1-39, AR-27). A case with no ran row, or a row that is not the Then row, is wholly unresolved as before.
    stored_tests = [e for e in (current or {}).get("tests") or [] if isinstance(e, dict)]
    drop_from_tests = _whole_case(
        [e for e in incoming_unresolved
         if not (_then_row(e) and _ran_rows(_case(e), incoming_tests, stored_tests))], unresolved_cases)

    for key in BY_CASE:
        existing = [e for e in (merged.get(key) or []) if isinstance(e, dict)]
        incoming = [e for e in ((fragment or {}).get(key) or []) if isinstance(e, dict)]
        if (not incoming and key not in (fragment or {}) and not drop_from_unresolved
                and not (fragment or {}).get("retracted_unresolved")):
            continue
        incoming_here: dict = {}
        for e in incoming:
            if _case(e):
                incoming_here[_case(e)] = _union_blocked(incoming_here[_case(e)], e) if _case(e) in incoming_here else e
        out = []
        for entry in existing:
            cid = _case(entry)
            match = _match_key(cid, incoming_here)
            if match:
                patch = incoming_here.pop(match)
                row = _replace_blocked_naming(patch, _merge_entry(entry, patch))
                out.append(_replace_contradicts_slice(patch, row, entry))
                summary["replaced"] += 1
            elif (cid and _matches_any(cid, drop_from_unresolved) and not _partition_scoped(entry)
                    and not (_blocked_row(entry) and not _explicit_green(cid, incoming_tests))
                    and not (_then_row(entry) and (not _explicit_green(cid, incoming_tests)
                                                   or _case_has_red(cid, incoming_tests, stored_tests)))):
                # (a Then row (`_then_row`) goes the same way, EP1-39 M-1: only an explicit `green` takes it, and not
                # while any row of the case is red - a green instance beside a red one proves one Then, not the case.)
                # (a `blocked_by_env` row is exempt, O2, from a patch with NO explicit `status` - the critic's
                # `unverified` verdict, a result patch - which reads as green HERE and must not take the row of
                # its case with it; `status: ""` is no status either. An EXPLICIT `status: green` covering the
                # case still drops the whole-case row, as before O2 (F1, critic t-243: the exemption had also
                # kept it on a case of two or more instances whose tests all went green - the allowed error
                # is "not blocked", never a stale row beside a green case).)
                summary["moved"] += 1  # this case is now in tests[] — drop the stale copy here
            else:
                out.append(entry)
                summary["kept"] += 1
        for entry in incoming:
            if _case(entry) in incoming_here:
                out.append(incoming_here.pop(_case(entry)))
                summary["added"] += 1
            elif not _case(entry):
                out.append(entry)
                summary["added"] += 1
        merged[key] = out
        # AFTER the merge of the rows: a green `tests[]` entry of the fragment may already have moved the case out.
        _retract_unresolved(merged, fragment, summary,
                            [_case(e) for e in (current or {}).get(key) or [] if isinstance(e, dict)])

    # A case is a relationship, not an identity: several parameterized tests can prove
    # it.  Merge tests by TestInstance ID and retain all existing links/fields.
    for key in BY_INSTANCE:
        existing = [e for e in (merged.get(key) or []) if isinstance(e, dict)]
        incoming = [e for e in ((fragment or {}).get(key) or []) if isinstance(e, dict)]
        if not incoming and key not in (fragment or {}) and not drop_from_tests:
            # A row already standing in two spellings is repaired whatever this fragment is
            # about: the manifest it was written into predates the rule, and every later read
            # of it — the exit gate, the ledger, the delivery check — counts the ghost.
            repaired, collapsed = _retract_aliases(existing) if existing else ([], [])
            if collapsed:
                merged[key] = repaired
                _record_retractions(merged, summary, collapsed)
                spent.extend(collapsed)
            continue
        patches = {}
        for entry in incoming:
            for iid in _identity(entry):
                patches.setdefault(iid, entry)
        taken, retired = set(), []
        out = []
        for entry in existing:
            match = next((i for i in _identity(entry) if i in patches), "")
            if match:
                patch = patches[match]
                taken.add(id(patch))
                row, dropped = _current_spelling(entry, patch, _merge_entry(entry, patch))
                if WRITER_MARK in patch and "novelty" not in patch:
                    # The writer (`manifest_from_tests.py`) re-ran and, by V2, stored no novelty
                    # for this row (a base that is not a recorded S0 base and a test that is not
                    # new or changed): the block an earlier run stored is now stale, and the
                    # shallow update above would keep it. Only a patch that carries the writer's
                    # own `generated_from` does this: a role's patch has none and never touches a
                    # measured block.
                    row.pop("novelty", None)
                out.append(row)
                if dropped:
                    retired.append(dropped)
                summary["replaced"] += 1
            elif _moved_out(entry, drop_from_tests):
                summary["moved"] += 1  # every case this instance proved moved to unresolved[]
                if key == "tests":
                    trail.setdefault("moved_out", []).append(
                        {"instance_id": _instance(entry), "case": ", ".join(_links(entry))})
            else:
                out.append(entry)
                summary["kept"] += 1
        for entry in incoming:
            if id(entry) in taken:
                continue
            out.append(entry)
            summary["added"] += 1
        out, collapsed = _retract_aliases(out)
        _record_retractions(merged, summary, retired + [r for r in collapsed if r not in retired])
        spent.extend(retired + collapsed)
        merged[key] = out

    # AFTER tests[] holds the green row: the stand-came-back door (t-219, B8) reads the merged manifest.
    _drop_blocked_of_green(merged, incoming_tests, summary)

    for key in APPEND_ONLY:
        incoming = [e for e in ((fragment or {}).get(key) or []) if e is not None]
        if not incoming:
            continue
        rows = list(merged.get(key) or [])
        if key in DEDUPED:
            seen = {_key(row) for row in rows}
            fresh = []
            for row in incoming:
                token = _key(row)
                if token in seen:
                    summary["duplicate"] = summary.get("duplicate", 0) + 1
                    continue
                seen.add(token)
                fresh.append(row)
            incoming = fresh
        merged[key] = rows + incoming
        summary["appended"] += len(incoming)

    if "obligation_bindings" in fragment:
        incoming = fragment["obligation_bindings"]
        if not isinstance(incoming, list) or any(not isinstance(b, dict) or not b.get("obligation_id") for b in incoming):
            raise ValueError("obligation bindings require stable obligation IDs")
        if len({b["obligation_id"] for b in incoming}) != len(incoming):
            raise ValueError("duplicate obligation binding in one fragment")
        by_id = {b["obligation_id"]: b for b in merged.get("obligation_bindings", [])}
        for binding in incoming:
            by_id[binding["obligation_id"]] = dict(by_id.get(binding["obligation_id"], {}), **binding)
        merged["obligation_bindings"] = list(by_id.values())
    _retract_obligations(merged, fragment, summary)
    held_before = _worn(current)
    _retract_instances(merged, fragment, summary, held_before)
    # A retracted instance takes its Then rows with it (HF3-2). BEFORE the merge of this fragment's own `then_bindings`
    # below: the invariant of the position is that a row the fragment sends stays (an old journal that sent a Then to an
    # id it also retracted replays unchanged - `run` refuses that pair on a new write, `merge` never raises on it).
    asked = (fragment or {}).get("retracted_instances")
    trail["then_retired"] = _retire_then_rows(
        merged, _dropped_spellings(current, [*spent, *(asked if isinstance(asked, list) else ())]), summary)
    _merge_expectation_changes(merged, fragment, summary)
    _merge_helpers(merged, fragment, summary)
    _merge_provisional(merged, fragment, summary)
    if "then_bindings" in (fragment or {}):
        rows = fragment["then_bindings"]
        if isinstance(rows, list):
            merged["then_bindings"], trail["then_taken"], trail["then_kept"] = _then_merge(merged.get("then_bindings"), fragment)
        else:
            merged["then_bindings"] = rows      # not an array: carried as it always was, never raised (old journals replay)
    retracted_keys = _retract_keys(fragment)
    for key, value in (fragment or {}).items():
        if key in BY_CASE or key in BY_INSTANCE or key in APPEND_ONLY or key in SCALAR_EXEMPT:
            continue
        # Two lists are accumulated, not replaced (RN1-22, FK-6 a); a key `retract` names, or any other type pair, is the
        # fragment's value whole - the merge invents no type, and a replace happens only by the explicit sign.
        if key not in retracted_keys and isinstance(value, list) and isinstance(merged.get(key), list):
            merged[key] = _accumulate(merged[key], value, ACCUMULATE_UNITS.get(key, ""))
        else:
            merged[key] = value

    return merged, summary


def _fold_step(manifest: dict, kind: str, payload) -> dict:
    """The manifest after ONE `manifest_seed` / `manifest_patch` event (its `kind` and `payload`); raises what the
    merge raises, or ValueError for a payload that carries no object to take. Writes nothing."""
    if kind == "manifest_seed":
        seed = payload.get("manifest") if isinstance(payload, dict) else None
        if not isinstance(seed, dict):
            raise ValueError("the manifest_seed payload carries no `manifest` object")
        return seed
    fragment = payload.get("fragment") if isinstance(payload, dict) else None
    if not isinstance(fragment, dict):
        raise ValueError("the manifest_patch payload carries no `fragment` object")
    merged, _ = merge(manifest, fragment)
    merged["revision"] = manifest.get("revision", 0) + 1
    return merged


def fold(events) -> dict:
    """The manifest the journal's `manifest_seed` / `manifest_patch` events add up to. Writes nothing.

    The ONE fold: `run` validates a new fragment against it before the commit, the projection
    written after the commit is built from it, and `--recover` replays it, so the three can never
    disagree about what the journal means.

    An event whose merge raises is skipped and NAMED, never fatal: the manifest carries
    `unprojected_events: [{sequence, idempotency_key, error}]` (the list is replaced on every fold,
    omitted when empty) and `revision` counts the merged events only. TP2-2406 S5-4,
    19.10.2026: the merge of journal seq 115 raised inside the projection, after the event was
    committed, and every later `manifest_put` replayed that event and raised again - the manifest
    stayed at revision 5 while seq 117 sat in the journal. A journal already holding such an event
    (2406's) must still move, and the gap is on the manifest for the role and the gate to read
    (FR-41, FR-59), not silent. A payload that is no object, or carries no `fragment` / `manifest`
    object, is unprojected with that error. Pre-commit refusal (`run`'s `validate`) is for new
    writes; this tolerance is for journals written before it and for any raise it cannot foresee."""
    manifest: dict = {}
    unprojected = []
    for event in events:
        kind = event.get("type") if isinstance(event, dict) else None
        if kind not in MANIFEST_EVENTS:
            continue
        try:
            manifest = _fold_step(manifest, kind, event.get("payload"))
        except Exception as exc:
            unprojected.append({"sequence": event.get("sequence"),
                                "idempotency_key": event.get("idempotency_key"),
                                "error": f"{type(exc).__name__}: {exc}"})
    manifest = {key: value for key, value in manifest.items() if key != "unprojected_events"}
    if unprojected:
        manifest["unprojected_events"] = unprojected
    return manifest


class _MigrationConflict(ValueError):
    """The legacy `automation-manifest.json` and its archived copy hold different content.

    A class of its own so the callers tell it by TYPE (FR-12) and name the door that fits: the
    replay hits the same conflict again, so "replay" alone is the wrong first move."""

    FILES = ("`automation-manifest.json` (the legacy manifest) and `state/migration/automation-manifest.json` "
             "(its archived copy)")

    def __init__(self):
        super().__init__("manifest migration conflict: " + self.FILES + " hold different content")


_FILES_DECISION = ("a role cannot tell which of the two files is right: tell the orchestrator, who asks the person "
                   "which one holds the manifest and sets the other one aside")


def recover_command(task: str) -> str:
    """The command that rebuilds the manifest's projection from the journal - the ONE spelling of the door that
    `run`, `recover` and every caller of this script name."""
    return f"manifest_put.py --task {task} --recover"


def outcome(code: int, task: str) -> tuple:
    """How a caller reads this script's exit code: `(kind, move)`, the ONE reader for every caller that runs it.

      0 -> ("committed", "")  the rows are in the journal and in the manifest;
      4 -> ("stale", <recover_command>)  EXIT_COMMITTED_STALE: the rows ARE in the journal, only the manifest's
           projection failed. Not a refusal and not to be sent again: the move is the replay (AR-25, FR-42);
      anything else -> ("refused", "")  the call's fault (exit 3 and 2): the fragment is NOT in the journal -
           correct it and send it again.
    An exit code this script does not define is read as a refusal, as every caller read every non-zero code
    before this reader existed."""
    if code == 0:
        return "committed", ""
    if code == EXIT_COMMITTED_STALE:
        return "stale", recover_command(task)
    return "refused", ""


def _stale_door(task: str, cause) -> str:
    """The move that fits a projection that failed: the replay, preceded by the files' decision when the
    failure is the migration conflict (the replay would stop on it again)."""
    replay = f"replay with {recover_command(task)}"
    if isinstance(cause, _MigrationConflict):
        return f"{_MigrationConflict.FILES} hold different content - {_FILES_DECISION}; then {replay}"
    return replay


def _cause_words(exc) -> str:
    """`Type: message` of what made an operation fail: the original of a chained refusal, else the refusal."""
    cause = getattr(exc, "__cause__", None) or exc
    return f"{type(cause).__name__}: {cause}"


def _write_projection(path: Path, manifest: dict) -> None:
    """Publish the folded manifest. The legacy block is unchanged: the original is kept as a
    migration receipt, never as a competing live alias."""
    from event_store import atomic_json
    legacy = path.parent.parent / "automation-manifest.json"
    if legacy.exists():
        archive = path.parent.parent / "state/migration/automation-manifest.json"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists() and archive.read_bytes() != legacy.read_bytes():
            raise _MigrationConflict()
        if not archive.exists():
            legacy.replace(archive)
        else:
            legacy.unlink()
    atomic_json(path, manifest)


def _projection_is_current(path: Path, manifest: dict) -> bool:
    """True when the file at `path` already holds exactly `manifest` (read, never written) and no legacy
    manifest waits to be archived: replaying the journal would change nothing, so `--recover` writes nothing
    and says so. An absent, unreadable or different file is not current - the replay rebuilds it (the error
    direction is the safe one: a doubt is a rewrite, never a skipped repair). "Different" is judged by the
    canonical text WITH the key order (`_key(..., ordered=True)`), not by Python equality: `1 == 1.0 == True`
    and a reordered file are equal values, and a file a hand edit or a foreign writer changed that way is a
    doubt (AR-28). Read through the package's one JSON reader (SIBLING_MAP axis 16)."""
    if (path.parent.parent / "automation-manifest.json").exists():
        return False
    standing = read_json(path, None, kind=dict)
    return standing is not None and _key(standing, ordered=True) == _key(manifest, ordered=True)


def projector(path: Path):
    """The `project(events)` step of the manifest's store: fold, then write. Returns the manifest."""
    def project(events):
        manifest = fold(events)
        _write_projection(path, manifest)
        return manifest
    return project


class _MergeRefused(ValueError):
    """A fragment the merge refuses, raised BEFORE the commit so the journal never holds it."""


def _unprojected_text(manifest: dict) -> str:
    """`seq a (error); seq b (error)` for the committed events the fold could not merge, else ''."""
    return "; ".join(f"seq {row.get('sequence')} ({row.get('error')})"
                     for row in manifest.get("unprojected_events") or [] if isinstance(row, dict))


def _unprojected_door(task: str) -> str:
    """What the role does about the entries of `unprojected_events[]`: the ONE sentence `run` and `--recover`
    both print. Code cannot tell whether the corrected content was already sent (it is a LATER event; the entry
    is the earlier one that cannot merge and stays listed as the journal's record), so the sentence is true in
    both worlds: the entry asks nothing once its content is in the manifest, and before that it names the
    move (FR-41: a trail, not a standing demand)."""
    return ("An entry stays listed as the journal's record of an event that could not be merged; it is never "
            "dropped, and it asks nothing more of you once its content is in the manifest. If that content is not "
            "in the manifest yet, correct what the entry's error names and send it with "
            f"`manifest_put.py --task {task} --fragment <file>`; then check the rows with "
            f"`manifest_view.py --task {task}`.")


def is_ghost_row(entry, manifest) -> bool:
    """Is this `tests[]` row a ghost of a retracted instance? THE one predicate, asked by the refusal of a new write
    (`ghost_row_problems`) and by the precheck's `ghost-` finding on a projection written before the rule.

    A ghost is a row that (a) shares no spelling (`_identity`, `_instance`) with any OTHER row of `manifest["tests"]`,
    (b) answers to a spelling listed in `manifest["retracted_instances"]`, and (c) carries none of `LINK_FIELDS`. It is what
    a send of the retracted name with a status or a file and no case links makes of the id (TP2-2406, seq 117): a
    row that proves no case, yet makes the old spelling look covered. "Other" is by object identity, so a row that stands in
    the manifest is asked as it stands and a row of a fragment (not yet in it) is asked as it would land; a row another row
    shares a spelling with is a patch or the live twin of that row, never a ghost, whatever it carries. The error direction
    is `not a ghost`: a row that is no object, has no id, or whose manifest lists no retraction is never named. Pure."""
    if not isinstance(entry, dict) or not isinstance(manifest, dict):
        return False
    retracted = manifest.get("retracted_instances")
    own = _spellings(entry)
    if not own or not isinstance(retracted, list) or not own & {str(r).strip() for r in retracted if r}:
        return False
    if any(entry.get(key) for key in LINK_FIELDS):
        return False
    return not any(other is not entry and isinstance(other, dict)
                   and own & _spellings(other)
                   for other in manifest.get("tests") or [])


def ghost_row_problems(folded: dict, fragment: dict, task: str) -> list:
    """What a fragment may not do to the instances it retracts or has retracted: one text per refusal, [] when none.

    (1) send a Then row bound to an id it retracts in the same fragment (the Then would bind to nothing); (2) send a
    `tests[]` row that is a ghost (`is_ghost_row`) of an instance the manifest retracted earlier. Both are NEW-WRITE
    refusals, raised by `_refuse_unmergeable` under the lock and never by `merge`: an old journal that holds either
    must keep folding (`merge` is pure and replays every event ever committed). The doors: the current spelling, or the
    whole row with its case links (FR-1, FR-57) - a legitimate return of the name is not refused."""
    out = []
    asked = fragment.get("retracted_instances")
    asked = {str(i).strip() for i in asked if str(i).strip()} if isinstance(asked, list) else set()
    rows = fragment.get("then_bindings")
    bound = sorted({str(r.get("instance_id") or "").strip() for r in rows if isinstance(r, dict)} & asked) \
        if isinstance(rows, list) else []
    if bound:
        out.append("one fragment cannot both bind a Then to and retract an instance: " + ", ".join(bound)
                   + " - send the Then row under the instance's new id and retract the old spelling, not the same id twice")
    for entry in fragment.get("tests") or []:
        if is_ghost_row(entry, folded):
            out.append(f"tests[] row `{_instance(entry) or next(iter(_identity(entry)))}` changes a test this manifest "
                       f"retracted (`retracted_instances`); send the change under the test's current spelling "
                       f"(`manifest_view.py --task {task}` lists them), or, to bring the test back, send its whole row "
                       f"with `covers` and `case_version_links`")
    return out


def _refuse_unmergeable(folded: dict, fragment: dict, task: str) -> None:
    """EVERY refusal of the merge, against the manifest the journal adds up to (`folded`), before the event
    exists. Raises `_MergeRefused`; writes nothing (`fold` and `merge` are pure). `expected_revision` is read
    against the folded revision (merged events only), which is the number the role sees in the file."""
    expected = fragment.get("expected_revision")
    revision = folded.get("revision", 0)
    if expected is not None and expected != revision:
        raise _MergeRefused(
            f"manifest revision conflict: the fragment expects revision {expected!r} and the manifest "
            f"(merged events only) is at revision {revision}. Read the revision in the file "
            f"(`manifest_view.py --task {task}`) and send the fragment again with that number as "
            "`expected_revision`, or without the key")
    try:
        merge(folded, fragment)
    except ValueError as exc:
        raise _MergeRefused(str(exc)) from exc
    except Exception as exc:  # a malformed fragment that is no ValueError: still refused, never committed
        raise _MergeRefused(f"{type(exc).__name__}: {exc}") from exc
    # After the merge's own refusals (their words win), against the same `folded` and under the same lock (HF3-2): the
    # ghost of a retracted instance is a property of the manifest as it stands, so it is asked HERE and not in `run`, which
    # reads the manifest without the lock - and not in `merge`, which replays old journals.
    problems = (ghost_row_problems(folded, fragment, task) + helper_row_problems(folded, fragment)
                + provisional_row_problems(folded, fragment))
    if problems:
        raise _MergeRefused("; ".join(problems))


def _seed_from_legacy(task: str, store, events: list, path: Path, fragment: dict, project) -> int:
    """A story whose journal holds no manifest event yet but whose manifest file exists (the legacy root-level
    one, or `work/`): that file becomes the journal's first manifest event, the seed, before the fragment.
    Returns 0 when the journal is ready for the fragment, else the exit code of the refusal.

    Invariant (the position of the check): the fragment is checked against the SEED's fold BEFORE the seed is
    committed. A seed commit projects (`_write_projection` writes `work/automation-manifest.json` and moves a
    legacy file into `state/migration/`), so a refusal after it would leave a journal line and moved files
    behind a text that says nothing was written (FR-41). Here `_MergeRefused` propagates with nothing written -
    no event, no manifest, no move; `validate` under the lock stays the second check, for a concurrent writer."""
    if any(e["type"] in MANIFEST_EVENTS for e in events):
        return 0
    old_path = C.artifact(path.parent.parent, "automation-manifest.json")
    if not old_path.exists():
        return 0
    old = json.loads(old_path.read_text(encoding="utf-8"))
    _refuse_unmergeable(fold([{"sequence": len(events) + 1, "type": "manifest_seed", "payload": {"manifest": old}}]),
                        fragment, task)
    from event_store import ProjectionStale
    try:
        store.commit("manifest_seed", {"manifest": old}, "manifest:legacy-seed", len(events), project=project)
    except ProjectionStale as stale:
        # Told apart from the fragment's by WHICH commit raised, never by the text. The journal holds the seed
        # and NOT the fragment: the role must send the fragment again, after the projection is repaired (FR-1, FR-41).
        print("manifest_put: your fragment was NOT committed. The legacy manifest was copied into the "
              "journal as its first event (the seed) and that event is in, but its projection failed "
              f"({_cause_words(stale)}). Repair that first - {_stale_door(task, stale.__cause__)} - and "
              f"then send the fragment with `manifest_put.py --task {task} --fragment <file>`.",
              file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    return 0


def is_inline(raw: str) -> bool:
    """`--fragment` carries the JSON itself when its first non-blank character is `{` (a fragment
    is always an object). Such an argument is never tried as a path: `s5_precheck.py` prints the
    command with the fragment inline, and a path reading it died with FileNotFoundError (t-108)."""
    return str(raw).strip().startswith("{")


def read_fragment(raw: str) -> dict:
    if is_inline(raw):
        try:
            data = json.loads(str(raw).strip())
        except ValueError as exc:
            raise ValueError(
                f"the fragment is not valid JSON ({exc}); an argument that starts with `{{` is read "
                "as the JSON itself, not as a path - quote it as one argument, or write it to a "
                "file and pass the path") from exc
    else:
        text = sys.stdin.read() if raw == "-" else Path(raw).read_text(encoding="utf-8")
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("a fragment is a JSON object with the keys of a manifest")
    return data


def _current_records(task_root) -> list:
    """The `expectation_changes[]` the manifest holds now, [] when there is none or it cannot be
    read: only the KEYS of these rows are asked (does a fragment row patch one or start one)."""
    return _current_rows(task_root, "expectation_changes")


def _current_rows(task_root, key: str) -> list:
    """The list under `key` of the stored manifest, [] when there is none or the manifest cannot be read."""
    try:
        current = json.loads(C.artifact(Path(task_root), "automation-manifest.json")
                             .read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = current.get(key) if isinstance(current, dict) else None
    return rows if isinstance(rows, list) else []


def _current_tests(task_root) -> list:
    """The `tests[]` the manifest holds now, [] when there is none or it cannot be read: only the `obligation_refs` of a
    row that a fragment patches are asked (`obligation_hash_problems`). The same reader as `_current_records`."""
    return _current_rows(task_root, "tests")


WORD_DOOR_TAGS = 3  # how many pairs' own tags one refusal prints


def _word_door(task_root: Path, task: str, rows) -> str:
    """The sentence about a person's word that ends a refusal of `expectation_changes` rows.

    Per pair the rows name: when a word already passed that pair at the S5 exit (the detector's own
    `word_passed_pairs`), the sentence says so and prints NO `--block` for it - a person's word is
    never asked for twice (P13). For a pair no word covers it prints the pair's OWN tag
    (`s5_precheck._pair_tag`: a word given for one pair passes that pair only). When no pair can be
    named from the rows the broad form of the stage is printed. Never raises: a measurement that
    fails here names every pair as not yet passed (the allowed error)."""
    wanted: list = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and _text(row.get("red_attempt")):
            green = row.get("green_attempt") if _text(row.get("green_attempt")) else None
            wanted += [(f, row["red_attempt"], green) for f in _record_functions(row) if _text(f)]
    passed: set = set()
    tags: dict = {}
    try:
        import s5_precheck as S5
        for f, red, green in wanted:
            tags[(f, red, green)] = S5._pair_tag({"function": f, "red_attempt": red, "green_attempt": green})
        manifest = json.loads(C.artifact(task_root, "automation-manifest.json").read_text(encoding="utf-8"))
        scope = S5.scope_cases(task_root, manifest, None)
        changes = S5.expectation_changes(task_root, scope, manifest)
        passed = {(p["function"], p["red_attempt"], p["green_attempt"])
                  for p in S5.word_passed_pairs(task_root, changes, scope)}
    except Exception:
        pass
    doors = [tags[k] for k in dict.fromkeys(wanted) if k in tags and k not in passed]
    done = [k[0] for k in dict.fromkeys(wanted) if k in passed]
    said = []
    if done:
        said.append(f"{', '.join(done[:WORD_DOOR_TAGS])} is already passed by a person's word: nothing to "
                    "record and nothing to ask them again")
    if doors:
        commands = " or ".join("`" + door(f"waiver.py --task {task} --stage S5 --block \"{tag}\"") + "`"
                               for tag in doors[:WORD_DOOR_TAGS])
        said.append("If a person has decided the test may stand as it is, no record is needed: the "
                    "orchestrator records their words with " + commands + " (one pair per word; "
                    "`--block \"changed-after-red\"` passes every pair of the stage that already had its "
                    "green run when the word was given)")
    if not wanted:
        said.append("If a person has decided the test may stand as it is, no record is needed: the "
                    "orchestrator records their words with `"
                    + door(f"waiver.py --task {task} --stage S5 --block \"changed-after-red\"") + "`")
    return ". ".join(said) + "."


def run(task: str, fragment_path: str, wait_seconds: float = 0.0) -> int:
    """`wait_seconds`: how long the commit waits for an in-flight story writer. `main` (the
    command line) chooses it; every other caller keeps 0 and fails at once on a held lock."""
    task_root = story_root(task, "manifest_put")        # the story EXISTS or this is a refusal (run_guarded prints it)
    path = task_root / "work" / "automation-manifest.json"
    try:
        fragment = read_fragment(fragment_path)
    except Exception as e:
        print(f"manifest_put: cannot read the fragment ({type(e).__name__}: {e})", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A fragment that carries nothing mergeable used to bump a revision, print a receipt and
    # exit 0, so the role read "revision 2" as "my manifest is written" and moved on. An empty
    # object is a fragment the role has yet to write, and saying so costs one turn instead of a
    # stage.
    # Which keys a fragment may carry is the merge's business and the list grows; what cannot be
    # a fragment is one that says NOTHING - no key but its own bookkeeping.
    if not [k for k in (fragment or {}) if k not in ("expected_revision", "revision", "note")]:
        return refuse("manifest_put.py --fragment",
                      ("the inline fragment" if is_inline(fragment_path) else fragment_path)
                      + " carries no manifest keys at all")
    # A `retract` that names no replaceable key is refused HERE and not in `merge` (RN1-22): merge replays every event
    # already committed and ignores an invalid one. The doors are the fragment keys the three refused names already have.
    retract_faults = retract_problems(fragment)
    if retract_faults:
        print("manifest_put: " + _problems_text(task_root, "retract", retract_faults)
              + ". `retract` is a list of top-level key names whose list the fragment replaces whole instead of adding to "
              "it (\"then_bindings\" also takes out the Thens of a unit it names and does not send). Correct the list in your "
              "fragment, e.g. \"retract\": [\"then_bindings\"]. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A `novelty` on a row is the measurer's, never a role's (t-187, F-B). The refusal is here and not
    # in `merge()`: merge is pure and replays every event already committed, and a refusal there would
    # reject a manifest written before this rule. The door is the role's own: leave the key out - the
    # stored block stays as it is - or let the writer measure it again.
    novelty_problems = novelty_row_problems(fragment)
    if novelty_problems:
        print("manifest_put: " + _problems_text(task_root, "novelty", novelty_problems)
              + ". A `tests[]` row's `novelty` is written by `manifest_from_tests.py` alone, as a block "
              "with `measured_on` and `measured_by` and never `resolved` (that form belongs to window "
              "items); a role never writes novelty. Take the `novelty` key out of the row in your "
              "fragment: the block already stored stays as it is. To have it measured again, re-run "
              "`manifest_from_tests.py` for your files. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A `base_outcome` is the code critic's record about one run (TQ1-18); a word that is not one of the two, or no run, would be
    # stored dead or read as a verdict it is not (FR-41). Before the commit, like `novelty` above: `merge` replays old events.
    base_problems = base_outcome_row_problems(fragment)
    if base_problems:
        print("manifest_put: " + _problems_text(task_root, "base-outcome", base_problems)
              + ". A `tests[]` row's `base_outcome` is `{\"outcome\": \"refused\" | \"working\", \"run\": \"<the attempt id of the "
              "run block whose log you read>\"}`: what the BASE of the test's before/after comparison answered in that run. Correct "
              "it in your fragment, or leave the key out if you did not open the log. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # Before anything is committed: an obligation id the plan does not name joins nothing and
    # is read downstream as a coverage gap. The task root is known here and not inside
    # `merge()`, which stays a pure function several other scripts call.
    refusal = unknown_obligation_refusal(task_root, fragment)
    if refusal and not _passed_by_word(task_root, refusal):
        print(f"manifest_put: {refusal}. Spell each id exactly as the plan's "
              "`coverage_obligations[].obligation_id`, and retract the old spelling with "
              "`retracted_obligations`. " + REPAIR_MARKER + "; if "
              "they have already decided the fragment stands as it is, the orchestrator "
              "records it with `" + door("waiver.py --task <TICKET> --stage S5 --block "
                                         "\"obligation-id\"") + "`, which passes this refusal.",
              file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A malformed record is refused BEFORE the commit, never inside the projection: a merge that
    # raises after the event is written leaves the story's projection stale (`event_store.commit`).
    problems = expectation_change_problems(fragment.get("expectation_changes"),
                                           _current_records(task_root))
    if problems:
        print("manifest_put: " + _problems_text(task_root, "expectation", problems)
              + ". " + REPAIR_MARKER + ". " + _word_door(task_root, task, fragment.get("expectation_changes")),
              file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A hand-typed `obligation_hash` is refused before the commit (EP1-38, AR-14): the code builds it from the refs.
    hash_problems = obligation_hash_problems(fragment, _current_tests(task_root))
    if hash_problems:
        print("manifest_put: " + _problems_text(task_root, "obligation-hash", hash_problems)
              + ". " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # An `approved` over a stored `unverified` with no note is refused before the commit (EP1-39, F-11 a); `merge` replays old journals.
    approval_problems = critic_approval_problems(fragment, _current_tests(task_root))
    if approval_problems:
        print("manifest_put: " + _problems_text(task_root, "critic-approval", approval_problems)
              + ". " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # An `assertion_id` on a line with no check is refused before the commit (TR2-1): a probe aimed there proves nothing. Rows whose id
    # did not change in this call are not read; unknowns (language, file, form) are notes printed at the end, never a refusal.
    line_problems, line_notes = assertion_line_problems(fragment, _current_tests(task_root), project_root())
    if line_problems:
        print("manifest_put: " + _problems_text(task_root, "assertion-line", line_problems)
              + ". Correct the row's `assertion_id` in your fragment to the line where the Then's check starts "
              "(`manifest_from_tests.py` prints it as `assertion_ref` `<file>:<first>-<last>`; the id is the first line of "
              "that range), or leave the key out. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # A Then left with its owner (GW1-14) is refused here when its row is malformed: the shape check is the
    # contract's (`then_remainder_errors`), the same one the marker parser and the S5 exit call. Before the commit, like
    # the checks above; `merge` stays pure (it replays old journals).
    remainder_problems = then_remainder_problems(task_root, fragment)
    if remainder_problems:
        print("manifest_put: " + _problems_text(task_root, "then-remainder", remainder_problems)
              + ". A Then a person takes is the row `{case, then, instance_id: null, assertion_ref: null, status: "
              "unresolved, reason: handed_to_person, owner?, part?, detail}`; write it with "
              "`qa_unresolved(case=, then=[n], reason=\"handed_to_person\", owner=, part=, detail=<steps>)` and "
              "re-run `manifest_from_tests.py` for your files. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # Two rows of one case with different reasons (F4): refused HERE, before the commit and before the judge is
    # asked, never in `merge` - the invariant of the position is that an event already in a journal keeps folding
    # (`merge` is pure and replays old events, which may hold two reasons; `fold` must not report them as unprojected).
    reason_conflicts = unresolved_reason_conflicts(fragment)
    if reason_conflicts:
        print("manifest_put: " + _problems_text(task_root, "unresolved-reasons", reason_conflicts)
              + ". " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    # `home_hash` of a provisional row is the code's, stamped HERE and committed with the fragment: `merge` stays pure and a replay
    # of the journal reads the hash that was true when the row was written, not a line that has changed since.
    fragment, stamp_notes = stamp_provisional(fragment, project_root())
    # Which critic verdicts this fragment takes away (the author's words changed under them) is
    # read BEFORE the commit, from the same merge the projection will run.
    incoming = fragment.get("expectation_changes")
    verdicts_dropped = merge({"expectation_changes": _current_records(task_root)},
                             {"expectation_changes": incoming})[1].get("verdicts_dropped") or [] \
        if isinstance(incoming, list) and incoming else []
    from event_store import EventStore, ProjectionStale, content_hash
    store = EventStore(path.parent.parent, wait_seconds=wait_seconds, stale_marker=MANIFEST_STALE_MARKER)
    fragment_key = "manifest:" + content_hash(fragment)

    def validate(events, payload):
        """EVERY refusal of the merge, before the event exists (TP2-2406 S5-4, 19.10.2026):
        the merge of seq 115 raised inside the projection, after the commit, and poisoned the journal.
        Invariant: whatever `fold` would later skip is refused here, so a new write never creates an
        unprojected event. The fold is the one `project` and `--recover` use, and `expected_revision`
        reads its revision (merged events only), which is the number the role sees in the file."""
        _refuse_unmergeable(fold(events), fragment, task)

    project = projector(path)
    try:
        events = store.read()
        seeded = _seed_from_legacy(task, store, events, path, fragment, project)
        if seeded:
            return seeded
        # The manifest as it stands (after a legacy seed, if there was one): a dropped row is gone from the file the
        # print below reads, and the slice and the Thens of what a retraction took are what the role must be told.
        before = fold(store.read()) if (fragment.get("retracted_unresolved") or fragment.get("then_bindings")
                                        or fragment.get("retracted_instances") or fragment.get("unresolved")) else {}
        event = store.commit("manifest_patch", {"fragment": fragment}, fragment_key,
                             validate=validate, project=project)
        merged = json.loads(path.read_text(encoding="utf-8"))
    except ProjectionStale as stale:
        # The fragment IS in the journal; only the projection failed. It is not the role's to repair
        # and not to send again (a repeat is the store's reuse path), and the door is a command the
        # role runs: the replay (FR-1, FR-2, FR-42).
        print("manifest_put: event committed; projection stale - the fragment is in the journal, do not "
              f"send it again; {_stale_door(task, stale.__cause__)}", file=sys.stderr)
        return EXIT_COMMITTED_STALE
    except _MergeRefused as exc:
        print(f"manifest_put: nothing was committed (the journal is unchanged): the fragment cannot be "
              f"merged - {exc}. Correct the fragment as that says and send it again with "
              f"`manifest_put.py --task {task} --fragment <file>`. " + REPAIR_MARKER + ".", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    except (ValueError, OSError) as exc:
        print(f"manifest_put: {exc}", file=sys.stderr)
        return EXIT_BAD_FRAGMENT
    cases = sorted({_case(e) for key in (*BY_CASE, *BY_INSTANCE) for e in merged.get(key) or [] if _case(e)})
    print(f"automation-manifest.json: revision {merged.get('revision')}, receipt {event['event_id']}")
    print("cases now in the manifest: " + (", ".join(cases) if cases else "none"))
    gap = _unprojected_text(merged)
    if gap:
        print("committed fragments the merge could not take (their own content is NOT in the manifest): " + gap
              + ". " + _unprojected_door(task))
    retracted = [str(rid) for rid in merged.get("retracted_instances") or [] if rid]
    if retracted:
        print("instance rows retracted into their current spelling: " + ", ".join(retracted))
    dropped = [str(oid) for oid in merged.get("retracted_obligations") or [] if oid]
    if dropped:
        print("obligation bindings retracted: " + ", ".join(dropped))
    for line in retracted_unresolved_lines(before, fragment):
        print(line)
    for line in moved_out_lines(before, fragment):
        print(line)
    taken_out = removed_then_lines(before, fragment)
    if taken_out:
        print("then_bindings rows taken out by this send (rows bound to an instance it retracted go with it; the rows "
              "it sent stand in their place; a row sent again brings one back):")
        for line in taken_out:
            print("  " + line)
    for line in kept_then_lines(before, fragment):
        print(line)
    for line in retract_idle_lines(fragment):
        print(line)
    for line in stamp_notes:
        print(line)
    records = merged.get("expectation_changes")
    if isinstance(records, list) and records and "expectation_changes" in fragment:
        print(f"expectation_changes: {len(records)} record(s) in the manifest")
    if verdicts_dropped:
        print("expectation_changes: the critic's verdict on " + "; ".join(verdicts_dropped)
              + " was dropped, because the author's words about it changed - the critic judges it again")
    if line_notes:
        print("assertion_id: the line was not checked for a check - " + "; ".join(line_notes) + " (the write went through)")
    return 0


def _replay_door(task: str, exc) -> str:
    """The door that fits WHY the replay failed. The busy-writer door is named only for the lock's own
    conflict: `EventStore.lock` raises `StateConflict` chained from the OS lock's `OSError`, while a
    damaged journal (`read`) chains a parse error or none. Told by class and chain, never by the text (FR-12)."""
    from event_store import StateConflict
    again = f"`{recover_command(task)}`"
    if isinstance(exc, StateConflict) and isinstance(exc.__cause__, OSError):
        return f"The story writer is busy: run {again} again in a moment."
    if isinstance(exc, StateConflict):
        return ("This is not a busy writer and running it again will not help: the journal itself is refused. "
                "Tell the orchestrator; a role does not edit `state/events.jsonl`.")
    if isinstance(exc, _MigrationConflict):
        return f"{_FILES_DECISION[0].upper()}{_FILES_DECISION[1:]}; then run {again}."
    return f"Fix what the error names (the disk, the permissions, a file held open), then run {again}."


def recover(task: str, wait_seconds: float = 0.0) -> int:
    """`--recover`: replay the journal's manifest events into `work/automation-manifest.json`.

    The door for a committed event whose projection did not finish (`run` names it) and for a
    journal that holds an event the merge cannot take (that one is named in `unprojected_events`).
    `controller.py --operation recover` rebuilds the controller's projection only and, before the
    manifest had its own marker, removed the manifest's trace without rebuilding it
    (TP2-2406 S5-4, 19.10.2026). Writes the projection only (FR-45) and is idempotent: the
    fold is deterministic, so a second run finds the file already holding the fold, writes nothing and
    says "already current". A missing or stale file is rebuilt from the journal. A journal with no
    manifest event writes nothing and says so. The gaps of `unprojected_events` are printed in every
    case (FR-41)."""
    task_root = story_root(task, "manifest_put")        # the story EXISTS or this is a refusal (run_guarded prints it)
    path = task_root / "work" / "automation-manifest.json"
    from event_store import EventStore
    store = EventStore(task_root, wait_seconds=wait_seconds, stale_marker=MANIFEST_STALE_MARKER)
    seen = {}

    def replay(events):
        seen["events"] = sum(1 for e in events if e.get("type") in MANIFEST_EVENTS)
        if seen["events"]:
            folded = fold(events)
            seen["manifest"] = folded
            seen["current"] = _projection_is_current(path, folded)
            if not seen["current"]:
                _write_projection(path, folded)

    try:
        store.recover(replay)
    except (ValueError, OSError) as exc:
        print(f"manifest_put: the journal could not be replayed into the manifest ({type(exc).__name__}: "
              f"{exc}). The journal is unchanged. {_replay_door(task, exc)}", file=sys.stderr)
        return EXIT_COMMITTED_STALE
    if not seen["events"]:
        print("manifest: nothing to project")
        return 0
    manifest = seen["manifest"]
    gap = _unprojected_text(manifest)
    unprojected = len(manifest.get("unprojected_events") or [])
    # The null outcome (FR-23): a manifest the journal already adds up to is left as it is and the line says so.
    print(("manifest: already current - " if seen["current"] else "manifest: ")
          + f"revision {manifest.get('revision', 0)}, {seen['events'] - unprojected} events merged"
          + (f", {unprojected} unprojected: {gap}" if unprojected else ""))
    if unprojected:
        print("The fragments listed above are in the journal; their own content is NOT in the manifest. "
              + _unprojected_door(task))
    return 0


def selftest() -> int:
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    window1 = {"tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001"},
                         {"case": "TC-002", "file": "a.py", "marker": "TC-002"}],
               "runs": [{"label": "w1"}], "run_witness": "evidence/w1.json"}
    window2 = {"tests": [{"case": "TC-003", "file": "b.py", "marker": "TC-003"}],
               "runs": [{"label": "w2"}], "run_witness": "evidence/w2.json"}

    merged, summary = merge(window1, window2)
    got = sorted(_case(t) for t in merged["tests"])
    case("window 2 does not erase window 1", got, ["TC-001", "TC-002", "TC-003"])
    case("its own entry is added", summary["added"], 1)
    case("the others are kept", summary["kept"], 2)
    case("runs are appended, never replaced", [r["label"] for r in merged["runs"]], ["w1", "w2"])
    case("a scalar the fragment carries wins", merged["run_witness"], "evidence/w2.json")

    verdict = {"tests": [{"case": "TC-001", "file": "a.py", "marker": "TC-001",
                          "critic_verdict": "approved"}]}
    merged2, summary2 = merge(merged, verdict)
    case("the critic replaces one entry", summary2["replaced"], 1)
    case("and touches no other", len(merged2["tests"]), 3)
    case("the verdict is on the right case",
         next(t for t in merged2["tests"] if _case(t) == "TC-001")["critic_verdict"], "approved")
    case("the other entries keep their shape",
         next(t for t in merged2["tests"] if _case(t) == "TC-002").get("critic_verdict"), None)

    # both directions. A whole-case `unresolved[]` row and a green `tests[]` entry are
    # contradictory claims about the same case; the mover wins and the stale copy goes.
    moved = {"unresolved": [{"case": "TC-003", "reason": "blocked_by_env"}]}
    merged3, summary3 = merge(merged2, moved)
    case("a whole-case unresolved row drops the stale test instance",
         sorted(_case(t) for t in merged3["tests"]), ["TC-001", "TC-002"])
    case("and arrives in unresolved[]",
         [_case(u) for u in merged3["unresolved"]], ["TC-003"])
    case("the independent unresolved record is added", summary3["added"], 1)

    back, summary4 = merge(merged3, {"tests": [{"case": "TC-003", "file": "b.py",
                                                "marker": "TC-003", "status": "green"}]})
    case("a green test entry clears the case's unresolved row", back["unresolved"], [])
    case("and the case is back in tests[]", sorted(_case(t) for t in back["tests"]),
         ["TC-001", "TC-002", "TC-003"])
    case("the drop is counted as a move", summary4["moved"], 1)

    partial = merge(back, {"unresolved": [{"case": "TC-003", "reason": "blocked_by_env",
                                           "partitions": ["P-warn"]}]})[0]
    case("a partition-scoped row does not erase the case's green instances",
         sorted(_case(t) for t in partial["tests"]), ["TC-001", "TC-002", "TC-003"])

    # The stand gap carries its own fix. The prose-only row is what TP1-15045 left the
    # person with; the row that names the file and the line is what would have unblocked it,
    # and it arrives as an ordinary patch of the same case.
    prose = {"unresolved": [{"case": "TC-006", "reason": "blocked_by_env",
                             "detail": "the sub-workflow partition cannot run"}]}
    fixed = {"unresolved": [{"case": "TC-006", "reason": "blocked_by_env",
                             "remedy": {"kind": "flag", "where": "customer-config.yaml:306-311",
                                        "change": "enabled: true", "restart": "testproject1"}}]}
    remedied = merge(merge({}, prose)[0], fixed)[0]["unresolved"][0]
    case("a later row with a remedy supersedes the prose-only row",
         remedied["remedy"]["where"], "customer-config.yaml:306-311")
    case("and keeps the detail the first row wrote", remedied["detail"],
         "the sub-workflow partition cannot run")
    handed = merge({"unresolved": [remedied]},
                   {"unresolved": [{"case": "TC-006", "reason": "handed_to_person"}]})[0]
    case("the person's `handed` answer rewrites the reason and keeps the remedy",
         (handed["unresolved"][0]["reason"], handed["unresolved"][0]["remedy"]["kind"]),
         ("handed_to_person", "flag"))

    split = {"tests": [{"case": "TC-001", "file": "a.py", "test_function": "test_limit",
                        "parameter": "eu"}]}
    once = merge(split, split)[0]
    case("the same instance never lands twice", len(once["tests"]), 1)
    case("an instance reads as function[parameter], with no case in it",
         _instance(once["tests"][0]), "test_limit[eu]")
    # an id a 0.7.7 manifest wrote still names the same row.
    prefixed = {"tests": [{"instance_id": "TC-001::test_limit[eu]", "critic_verdict": "approved"}]}
    upgraded = merge(once, prefixed)[0]
    case("a 0.7.7 case-prefixed id patches the row it always meant", len(upgraded["tests"]), 1)
    case("and the patch lands on it", upgraded["tests"][0].get("critic_verdict"), "approved")

    # One consolidated test proving three cases: green clears all three unresolved rows, and
    # one case going unresolved does not delete the evidence for the other two.
    shared = {"tests": [{"file": "c.py", "test_function": "test_all", "status": "green",
                         "covers": ["TC-003", "TC-004", "TC-005"]}]}
    blocked = {"unresolved": [{"case": "TC-003", "reason": "blocked_by_env"},
                              {"case": "TC-004", "reason": "blocked_by_env"},
                              {"case": "TC-005", "reason": "blocked_by_env"}]}
    cleared = merge(merge({}, blocked)[0], shared)[0]
    case("one green consolidated test clears every case it covers", cleared["unresolved"], [])
    partial_move = merge(cleared, {"unresolved": [{"case": "TC-003", "reason": "blocked_by_env"}]})[0]
    case("and one case going unresolved keeps the instance the other two still need",
         len(partial_move["tests"]), 1)
    all_moved = merge(partial_move, blocked)[0]
    case("only when every covered case has moved does the row go", all_moved["tests"], [])

    try:
        merge({}, {"tests": [{"file": "a.py", "test_function": "test_x", "case": "TC-1"},
                             {"file": "b.py", "test_function": "test_x", "case": "TC-2"}]})
        case("two files sharing a function name are refused, not silently merged", True, False)
    except ValueError as exc:
        case("two files sharing a function name are refused, not silently merged",
             "name different files" in str(exc), True)

    fix = {"self_fixes": [{"test": "t", "what": "selector", "why_test_defect": "renamed",
                           "evidence": "e.json"}]}
    twice = merge(merge({}, fix)[0], fix)[0]
    case("a byte-identical self_fix is not appended twice", len(twice["self_fixes"]), 1)

    empty, _ = merge({}, window1)
    case("a first window creates the manifest", len(empty["tests"]), 2)
    case("an empty fragment changes nothing", merge(merged3, {})[0], merged3)

    # TP2-2553: nine bindings under `OB-n` against a plan naming `TS-n-Om`. Renaming
    # them is only half the repair — the old spelling has to be able to leave the map, or it
    # stands beside the new one joining nothing.
    legacy = merge({}, {"obligation_bindings": [{"obligation_id": "OB-1", "instance_ids": ["test_a"]},
                                                {"obligation_id": "OB-2", "instance_ids": ["test_b"]}]})[0]
    renamed, summary5 = merge(legacy, {
        "obligation_bindings": [{"obligation_id": "TS-1-O1", "instance_ids": ["test_a"]}],
        "retracted_obligations": ["OB-1"]})
    case("a renamed obligation leaves only the plan's spelling",
         sorted(b["obligation_id"] for b in renamed["obligation_bindings"]), ["OB-2", "TS-1-O1"])
    case("and the retraction is recorded on the manifest",
         renamed["retracted_obligations"], ["OB-1"])
    case("the retraction is counted", summary5.get("retracted"), 1)
    case("`retracted_obligations` is not copied on as a scalar the next fragment carries",
         merge(renamed, {"run_witness": "e.json"})[0]["retracted_obligations"], ["OB-1"])
    try:
        merge(legacy, {"obligation_bindings": [{"obligation_id": "OB-1"}],
                       "retracted_obligations": ["OB-1"]})
        case("binding and retracting one id in one fragment is refused", True, False)
    except ValueError as exc:
        case("binding and retracting one id in one fragment is refused",
             "both bind and retract" in str(exc), True)

    # the record of a test that changed after its red run: merged by (functions, red, green)
    row = {"function": "test_m.test_x", "red_attempt": "r1", "green_attempt": "g1",
           "then_refs": [{"case": "TC-1", "then": 1}], "what_changed": "403 -> 401", "reason": "r"}
    first, _ = merge({}, {"expectation_changes": [row]})
    verdict, _ = merge(first, {"expectation_changes": [{
        "function": "test_m.test_x", "red_attempt": "r1", "green_attempt": "g1",
        "critic_verdict": "fitted_to_code"}]})
    case("a critic verdict patches the record and the author's fields survive",
         (len(verdict["expectation_changes"]), verdict["expectation_changes"][0]["reason"],
          verdict["expectation_changes"][0]["critic_verdict"]), (1, "r", "fitted_to_code"))
    case("an empty list is a no-op", merge(first, {"expectation_changes": []})[0], first)
    case("a well formed new row has no problem", expectation_change_problems([row]), [])
    case("a row without its author fields is refused", len(expectation_change_problems(
        [{"function": "f", "red_attempt": "r", "green_attempt": None}])), 3)

    # the fold: an event whose merge raises is named on the manifest and the journal goes on (t-040)
    journal = [{"type": "manifest_patch", "sequence": seq, "idempotency_key": f"k{seq}",
                "payload": {"fragment": fragment}}
               for seq, fragment in ((1, window1), (2, {"retracted_instances": ["nobody[x]"]}), (3, window2))]
    folded = fold(journal)
    case("fold: revision counts the merged events only", folded.get("revision"), 2)
    case("fold: an event whose merge raises is named, not fatal",
         [row["sequence"] for row in folded.get("unprojected_events") or []], [2])
    case("fold: the windows around it both merged", sorted(_case(t) for t in folded.get("tests") or []),
         ["TC-001", "TC-002", "TC-003"])
    case("fold: a clean journal carries no unprojected_events", "unprojected_events" in fold(journal[:1]), False)

    if failures:
        print("MANIFEST_PUT SELFTEST: VIOLATIONS")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("MANIFEST_PUT SELFTEST: no violations (merge by case, append-only lists, moves)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="merge a fragment into automation-manifest.json",
        epilog=epilog("manifest_put.py"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", help="ticket id")
    ap.add_argument("--fragment", help="path to the JSON fragment, - for stdin, or the JSON itself "
                                       "when it starts with {")
    ap.add_argument("--recover", action="store_true",
                    help="replay the task's journal into automation-manifest.json (no fragment)")
    ap.add_argument("--selftest", action="store_true")
    ns = ap.parse_args()
    if ns.selftest:
        sys.exit(selftest())
    import event_store
    if ns.recover:
        if ns.fragment is not None:
            ap.error("--recover replays the journal and takes no --fragment (one action per call): run "
                     "`manifest_put.py --task <T> --recover` first, then send the fragment in a second call")
        if not ns.task:
            ap.error("--recover needs --task <T>")
        sys.exit(recover(ns.task, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS))
    if not ns.task or not ns.fragment:
        ap.error("--task and --fragment are both required")
    sys.exit(run(ns.task, ns.fragment, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS))


if __name__ == "__main__":
    raise SystemExit(run_guarded(command_from_argv("manifest_put.py"), main))
