"""The artifact contract in code: closed vocabularies and the parsers that read them.

One home for what `references/artifact-contract.md` states in prose, so the validator, the
ledger, the traceability check and the delivery aggregator cannot drift apart — a vocabulary
copied into four scripts is four vocabularies. Nothing here writes; nothing here exits.
"""
import datetime
import json
import hashlib
import re
import string
import time
from pathlib import Path

import case_forms
import grammar as G


def force_utf8() -> None:
    """Windows console codepages cannot fit the characters these reports print. Called by
    every CLI in this family before its first print (hooklib does the same for the hooks)."""
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass


# --- a dispatch packet's paths are portable (t-329, B-249) -- the code lives in runtime_paths (t-304 N1) -----
# One resolver for the writers and every reader of a story's paths (FR-16, FR-17, FR-37): `runtime_paths` holds the tokens,
# `portable_known_paths` / `resolve_known_paths` / `known_paths_for_dispatch` (the RUN policy, t-329/t-335) and the READ
# policy (`project_for_task`, `state_paths`). The names below stay as one-line delegations, so every existing caller and
# pin (T329-3, T335) reads the same functions it always did - builder-rules item 1 allowed this one edit of contract.py.
import runtime_paths

PROJECT_TOKEN = runtime_paths.PROJECT_TOKEN
PLUGIN_TOKEN = runtime_paths.PLUGIN_TOKEN
PYTHON_TOKEN = runtime_paths.PYTHON_TOKEN
FINGERPRINT_SHOWN = runtime_paths.FINGERPRINT_SHOWN
LEGACY_RUN_KEYS = runtime_paths.LEGACY_RUN_KEYS


def _under(text: str, roots: list) -> str:
    return runtime_paths._under(text, roots)


def portable_known_paths(paths, project_root, plugin_root, task_root=None):
    return runtime_paths.portable_known_paths(paths, project_root, plugin_root, task_root)


def resolve_known_paths(paths, project_root, plugin_root, python, task_root=None):
    return runtime_paths.resolve_known_paths(paths, project_root, plugin_root, python, task_root)


def _same_place(left: str, right) -> bool:
    return runtime_paths._same_place(left, right)


def known_paths_for_dispatch(paths, *, project_root, plugin_root, python, current=None, door="", task_root=None):
    return runtime_paths.known_paths_for_dispatch(paths, project_root=project_root, plugin_root=plugin_root, python=python,
                                                  current=current, door=door, task_root=task_root)


# --- closed vocabularies (artifact-contract.md) -------------------------------------------

DISPOSITIONS = ("automate", "manual-agent", "manual-human", "skip", "unverifiable")
OBSERVABLE_SOURCES = ("diff", "current-code", "expected-contract")
# How a story's implementation was obtained, per repository. `none`/`ungrounded` are the
# same answer in two spellings: the manifest writes the first, pipeline.json the second.
IMPLEMENTATION_SOURCES = ("diff", "current-code", "none", "ungrounded")
ORACLE_PREFIXES = ("requirement:", "external:", "history:")
# A Then that sits in a test AFTER an assert that fails by the requirement (TP1-12586, TC-004 / TC-005 / TC-006 in
# one msteams test): the test stopped at the red assert and never reached this Then, so the Then was not checked, and
# nothing is wrong with it. The reason of a PER-THEN `then_bindings` row only (`blocking_check` names the red case or
# instance, `detail` what to check once it is fixed); a whole-case `unresolved[]` row never carries it
# (`s5_precheck`: `blocked-check-row`). A FACT the factory reads off a red test, never a person's word or a stand
# problem: no `owner`, no waiver. It holds the delivery as a product check still owed (`after_checks`). ONE home, here
# (FR-13); the readers import it (`THEN_REMAINDER_REASONS`, the ledger, the delivery check, the trace).
BLOCKED_BY_CHECK = "blocked_by_check"
# The word of a test written against a side that does not exist yet (t-2181 PC-4): ONE home here; `acceptance.PENDING_OUTCOME`
# aliases it, and the window outcomes and the probe rule take it (FR-13).
PENDING_IMPLEMENTATION = "pending_implementation"
UNRESOLVED_REASONS = ("impossible", "blocked_by_env", PENDING_IMPLEMENTATION, "contradicts_requirement",
                      # The person answered, at gate A or mid-S5, that THEY will run these
                      # tests: the runner of their profile does not exist in the session the
                      # factory works in (TP2-2536: Maestro/iOS, no Xcode for the
                      # agent). The code is written and statically reviewed, nothing ran, and
                      # the factory waits for no result. Never a stand problem (that is
                      # `blocked_by_env`, which is repaired or asked about) and never a
                      # `manual-human` row (that was the person's from the plan on).
                      "handed_to_person",
                      # A Then whose expected value nobody confirmed (P20): an `unknown` oracle whose
                      # question is still open. The reason of a per-Then `then_bindings` row, and of a
                      # whole-case `unresolved[]` row that names its `question`. NOT a stand problem and
                      # NOT `deferred_by_decision` (that prints "a person's recorded decision", false for a
                      # question nobody answered, FR-41); it holds no delivery - the person's debt
                      # (`ledger.person_debts`). ONE home, here (FR-13); `ledger.EXPECTATION_UNCONFIRMED`
                      # is this word.
                      "expectation_unconfirmed",
                      # A Then behind a red assert of the same test (see `BLOCKED_BY_CHECK` above): the reason of a
                      # per-Then `then_bindings` row, never of an `unresolved[]` row, no person's word.
                      BLOCKED_BY_CHECK)
EXPECTATION_UNCONFIRMED = "expectation_unconfirmed"
UNRESOLVED_DECIDED_PREFIX = "deferred_by_decision"
# What a `deferred_by_decision:*` row disputes, said by the row instead of read out of its
# prose. After gate A the approved case is the oracle for S5, so `case_expectation` is not a
# route out of the stage — it travels with a red test to S7 (`s5_precheck.check_case_is_oracle`).
# `derivation` is the legitimate one: "the expected status is not derivable from the register or
# the diff, the owner must supply the access-control contract" disputes nothing. `nothing` is
# for a deferral about anything else — a stand, a sequence, a dependency.
UNRESOLVED_DISPUTES = ("nothing", "derivation", "case_expectation")
HANDED_TO_PERSON = "handed_to_person"
# The stage override `waiver.py` writes when the person picks option (c) of the executor
# question. The match carries the profile so a story with two profiles hands over one.
HANDED_MATCH_PREFIX = "executor unavailable:"


def prefix_value(text, prefix: str) -> str | None:
    """The ONE token a prefixed block carries (`stand gap: TC-7`, `executor unavailable: e2e-ui`), or None. The prefix
    matches in any case at the start of the whitespace-folded text; the value is what follows it, edges and quotes cut,
    and must be a single token: no whitespace inside and no leading colon. A profile or a gap id is one token by
    construction (`gate_preflight` writes `f"{HANDED_MATCH_PREFIX} {profile_id}"`); a value that is words is no id any
    reader can look up. The ONE reader of this form: the writer (`waiver.block_name_row`), the person's phrase
    (`waiver.block_in_words`) and the reader (`handed_profiles`) all call it, so they cannot read a block differently."""
    folded = " ".join(str(text if text is not None else "").split())
    if not folded.lower().startswith(prefix.lower()):
        return None
    rest = folded[len(prefix):].strip().strip("`\"'")
    return rest if rest and not rest.startswith(":") and not any(ch.isspace() for ch in rest) else None


def names_whole(needle, text) -> bool:
    """True when `text` holds `needle` as a WHOLE identifier, in any case - the ONE predicate by which a person's word
    (a `stage_overrides[]` `match`, a dispatch id, a case key) is read against a line (GW1-1, AR-13). A substring is
    not enough: the word `R-3` must not pass a line about `BR-3`, `R-30` or `R-3.1`.

    Left edge: when the first character of `needle` is one of `[\\w-]`, the character before it is not. Right edge:
    when the last character is one of `[\\w-]`, the character after it is not, and is not one of `. : / \\ [ @`
    followed by ANY non-space character (`R-3.1`, `R-3:x`, `a.py::test_x[1]`, `a.py::test_x[-1]`, `a.py::test_x[(1, 2)]`,
    `PC-1@TC_002`, `tests\\a\\b.py` - a hostile variant never passes as the word it extends, GW1-52, finding 31.10.2026:
    the old right edge asked for a WORD character after the mark, so `[-1]`, `[(`, `["` and `@` slipped through).
    A needle edge of any other character (a backtick, a bracket) asks nothing of its side. `R-3.`, `(R-3)`, `R-3 [x]`
    and `R-3` at the end of the text are whole; `R-3, R-4` names `R-3` too (a list line is one line - not a regression). Empty or blank `needle` is False: a word without words
    passes nothing. Non-strings are read through `str()`; never raises. The error direction is toward False, which
    asks the person again."""
    needle, text = str(needle if needle is not None else "").lower(), str(text if text is not None else "").lower()
    if not needle.strip():
        return False
    word = r"[\w-]"
    left = rf"(?<!{word})" if re.match(word, needle[0]) else ""
    right = rf"(?!{word})(?![.:/\\\[@]\S)" if re.match(word, needle[-1]) else ""
    return re.search(left + re.escape(needle) + right, text) is not None


def live_stage_overrides(pipeline, stages=None) -> list:
    """The `stage_overrides[]` records a person's word still stands on, in file order: objects with a non-empty
    `decision` and no `revoked_at`; `stages` (a tuple, or one name) keeps those stages only, None keeps all. The ONE
    filter every reader that ACTS on a word starts from (AR-13): a revoked record is history and acts nowhere, whatever
    its `match` - `*` included (FR-40). Never raises: a pipeline that is no object, a `stage_overrides` that is no
    list (or is absent, or empty) give [] (AR-28)."""
    entries = pipeline.get("stage_overrides") if isinstance(pipeline, dict) else None
    if isinstance(stages, str):
        stages = (stages,)
    out: list = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or entry.get("revoked_at") or not str(entry.get("decision") or "").strip():
            continue
        if stages is not None and str(entry.get("stage") or "") not in stages:
            continue
        out.append(entry)
    return out


def stage_override_values(pipeline, prefix: str, stage: str = "S5") -> list:
    """[(value, entry)] — the live `stage_overrides[]` records of `stage` whose `match` is `prefix` plus ONE token
    (`prefix_value`) and whose `decision` (the person's words) is not empty, in file order. The ONE reader of a person's
    prefixed word (`executor unavailable:`, `then handed:`, `probe gap:`, `plan rows by person:`): `handed_profiles`, `then_handed_words` and
    `probe_gap_words` each keep their own join on top of it, so they cannot read a record differently (AR-13). A REVOKED
    record (`revoked_at`) is no word: the error direction is toward NO entry, which asks the person again. Never raises: a
    pipeline that is no object, a `stage_overrides` that is no list, a record that is no object, another stage, and a
    `match` that is no prefix plus one token give none."""
    out: list = []
    for entry in live_stage_overrides(pipeline, (stage,)):
        value = prefix_value(entry.get("match"), prefix)
        if value:
            out.append((value, entry))
    return out


def handed_profiles(pipeline: dict) -> dict:
    """{profile_id: {"words", "at"}} — the profiles the person took over, from their own words.

    One place reads this decision: `stage_overrides[]`, which is where every block a person's
    word passes already lands (`waiver.py --stage S5 --block "executor unavailable: <id>"`).
    A second store for the same fact would be a second answer to drift from.

    The value is read by `prefix_value`, as the writer reads it: a line whose value is words, empty or colon-led is no
    profile and is absent here. The writer refuses such a block, so the reader meets one only in a hand-edited record.
    A revoked record is no word (`stage_override_values`): the profile is asked about again."""
    return {profile: {"words": str(entry.get("decision") or "").strip(), "at": str(entry.get("at") or "")}
            for profile, entry in stage_override_values(pipeline, HANDED_MATCH_PREFIX)}


# --- one Then handed to its owner (GW1-14) ------------------------------------------------------
# TP1-12586 (22.10.2026): everything in TC-001 was checkable on the stand except the datasource-link part of
# Then 4 (no Jira there). The person said "leave it to me" and the manifest could only carry that as a partition row
# beside the green test, which `s5_precheck` refuses as `partial-green`: the author had to write a test that cannot run.
# The unit the plan and the cases count by is the Then, so a Then-level hand-off is a REMAINDER: a `then_bindings` row
# `{case, then, instance_id: null, assertion_ref: null, status: unresolved, reason: handed_to_person, owner?, part?,
# detail}`. ONE home here (FR-13, AR-13): the shape check, the list and the person's word all come from these
# functions; the precheck, the writers, the ledger, the delivery check, the report and the trace call them.
THEN_HANDED_MATCH_PREFIX = "then handed:"
THEN_REMAINDER_OWNERS = ("person", "other_environment")
THEN_REMAINDER_DEFAULT_OWNER = "person"   # an absent `owner` reads as the reason word itself says (builder rule 9)
_THEN_NUMBER_RE = re.compile(r"[0-9]+")
# The tag family of the Then-level hand-off findings and the ONE finding of it that WAITS for a person's word (AR-13,
# AR-15): `s5_precheck` builds the finding ids from them and `exit_gate` reads the waiting tag, both from here.
THEN_REMAINDER_TAG = "then-remainder-"
THEN_REMAINDER_WAITS = THEN_REMAINDER_TAG + "unrecorded-"
# The reasons a `then_bindings` row may carry to be a REMAINDER (a Then no test proves): left with its owner
# (`handed_to_person`), or behind a red assert of the same test (`blocked_by_check`, HF2-3). A reader that asks for the
# remainders names the reasons it wants (`reasons=`) and the default is the person's hand-off alone, so every caller
# written before the second reason existed reads exactly what it read (AR-13: one list, here).
THEN_REMAINDER_REASONS = (HANDED_TO_PERSON, BLOCKED_BY_CHECK)

def then_number(value) -> int:
    """The Then number a `then_bindings` row names, 0 when it names none: THE one reader of a row's `then` (AR-13; the
    precheck and the code judge call it). A row whose `then` was a list or a dict used to crash the whole check
    (`int([4])`, t-059 p. 2): a gate that cannot read a row reads it as naming none, so its clause stays uncovered and
    the refusal stands (FR-59), it does not stop the factory.

    Reading rule: an `int` that is no `bool` and is >= 1 is that number; a `str` of ASCII digits (after `strip()`) whose
    value is >= 1 is that number (a manifest a role wrote may carry `"then": "2"`); everything else - `None`, `""`,
    `0`, a negative, a bool, a float (even `4.0`), a list, a dict, a string that is not digits - is 0. The same
    contract as `then_remainder_errors` ("a bool, a float is none"). The error direction is towards an uncovered
    clause, never towards a pass."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, str):
        value = value.strip()
        value = int(value) if value.isascii() and value.isdigit() else 0
    if isinstance(value, int) and value >= 1:
        return value
    return 0


# The keys by which an `unresolved[]` row says WHICH part of its case it speaks about (HF2-3, N5): ONE home. Two groups
# that are replaced independently (a patch that re-sends the instances keeps the partitions), and `thens`, which is NOT
# a slice key: a row with `thens` and no slice key is still the whole case's row (the Then it names says which clause is
# red, not whose row it is). The readers - `_slice_scoped` below, `manifest_put._partition_scoped` and
# `_replace_contradicts_slice`, `acceptance.row_slice` - take their keys from these, so none keeps a list of its own.
UNRESOLVED_INSTANCE_KEYS = ("instance_id", "instance_ids")
UNRESOLVED_PARTITION_KEYS = ("partition", "partitions")
UNRESOLVED_SLICE_KEYS = UNRESOLVED_INSTANCE_KEYS + UNRESOLVED_PARTITION_KEYS
UNRESOLVED_THENS_KEY = "thens"


def _slice_scoped(entry) -> bool:
    """An `unresolved[]` row naming partitions or instances speaks about a SLICE of its case (the predicate of
    `manifest_put._partition_scoped`); a row without them is the whole case's. The keys are
    `UNRESOLVED_SLICE_KEYS`: `thens` is not one, so a row that names only Thens is still the whole case's (a
    key that is present and empty - `[]`, `""`, None - names nothing)."""
    return isinstance(entry, dict) and any(entry.get(key) for key in UNRESOLVED_SLICE_KEYS)


def then_scoped_row(row) -> bool:
    """Is this `unresolved[]` row about particular Thens of a case that RAN, not about the whole case (EP1-39)? Its reason
    is `PROBE_NOT_APPLICABLE_REASON` (`contradicts_requirement`), its `thens` a non-empty list, and it names no slice
    (`not _slice_scoped`). The ONE predicate (AR-13): `manifest_put._then_row` delegates here, and
    `then_remainder_rows` reads it. A `thens` that is no list (`"2"`), an empty one, another reason, or a row that
    names instances or partitions is not this row: the wrong form widens no protection."""
    if not isinstance(row, dict) or str(row.get("reason") or "") != PROBE_NOT_APPLICABLE_REASON:
        return False
    thens = row.get(UNRESOLVED_THENS_KEY)
    return isinstance(thens, list) and bool(thens) and not _slice_scoped(row)


def partition_key(value) -> str:
    """The comparable form of a partition label: stripped, a leading `P-` cut (any case), case-folded; `""` for an
    empty or absent label. THE one spelling of "the same partition" (AR-13): the plan writes `P-msteams`, a test and a
    hand-written row write `msteams`, and a reader that compared the raw labels read two partitions where there was one
    and opened a pass for the red one. Error direction: `""` is the key of NOTHING - a reader that intersects keys drops
    it first, so two unreadable labels never make one partition. A value that is no string reads as its `str()`
    (`None` is empty)."""
    text = "" if value is None else str(value).strip()
    if text[:2].lower() == "p-":
        text = text[2:]
    return text.casefold()


def then_remainder_rows(manifest: dict, cfg=None, reasons=(HANDED_TO_PERSON,)) -> list:
    """The `then_bindings` rows that SAY a Then is a remainder, malformed ones included: status other than
    `covered`, a reason in `reasons` (default: `handed_to_person`, the Then left with its owner; the other member of
    `THEN_REMAINDER_REASONS` is `blocked_by_check`, a Then behind a red assert of its own test), a case that has NO
    whole-case `unresolved[]` row (any reason). A case that has one keeps today's meaning: its per-clause rows are the
    whole-case hand-off's echo (`manifest_from_tests` writes one per clause), never remainders. The shape is judged by
    `then_remainder_errors`, not here, so a gate can refuse what this finds. Error direction: a row is listed rather
    than dropped. The default call lists exactly the rows it listed before the second reason existed. `reasons` is a
    list or tuple of words (a single word is that word, not its letters); anything else asks for nothing.

    A row that `then_scoped_row` names (a `contradicts_requirement` row naming only Thens of a case that ran) is NOT a
    whole-case row (EP1-39): it says a Then is unresolved, not the case, and a Then waiting behind a red assert of its
    own test (`blocked_by_check`) must not vanish because of it (AR-27)."""
    cfg = case_config() if cfg is None else cfg
    wanted = (reasons,) if isinstance(reasons, str) else tuple(reasons) if isinstance(reasons, (list, tuple)) else ()
    wholes = [str(u.get("case") or "") for u in manifest_unresolved(manifest)
              if not _slice_scoped(u) and not then_scoped_row(u)]
    wholes = [w for w in wholes if w]
    out = []
    for row in (manifest or {}).get("then_bindings") or []:
        if not isinstance(row, dict) or str(row.get("status") or "") == "covered":
            continue
        if str(row.get("reason") or "") not in wanted:
            continue
        case = str(row.get("case") or "").strip()
        if not case or any(case_matches(w, case, cfg=cfg) for w in wholes):
            continue
        out.append(row)
    return out


def then_remainder_errors(row) -> list:
    """Why a Then-level hand-off row is malformed: one FR-1 sentence per problem, [] when it is well formed. The ONE
    shape check (the marker parser, `manifest_put` and the precheck call it). `then` is the number of a clause (an
    integer >= 1; a bool, a string, a float is none), `owner` one of THEN_REMAINDER_OWNERS when the key is present,
    `detail` the steps or command the owner follows (non-empty), `instance_id` null (a remainder has no test),
    `part` a string when present.

    A row whose reason is `blocked_by_check` is judged by its own shape (HF2-3): `then` as above, `blocking_check` a
    non-empty string with no whitespace (the key of the red case, or the id of the red instance), `detail` non-empty
    (what to check once the red is fixed), `instance_id` null or a string (the test that holds the Then, which stops at
    the red assert), and NO `owner` (a fact the factory read off a red test has no owner to choose). Any other reason
    is judged as before."""
    if not isinstance(row, dict):
        return ["the row is not an object"]
    errors = []
    then = row.get("then")
    if isinstance(then, bool) or not isinstance(then, int) or then < 1:
        errors.append(f"`then` must be the number of a Then clause (an integer >= 1), got {then!r}")
    if row.get("reason") == BLOCKED_BY_CHECK:
        blocker = row.get("blocking_check")
        if not (isinstance(blocker, str) and blocker.strip() and not any(ch.isspace() for ch in blocker)):
            errors.append("`blocking_check` must name the red check this Then waits behind - the key of its case or the "
                          f"id of its test, one word with no spaces - got {blocker!r}")
        detail = row.get("detail")
        if not (isinstance(detail, str) and detail.strip()):
            errors.append("`detail` must say what to check once the red is fixed, and is empty")
        instance = row.get("instance_id")
        if instance is not None and not isinstance(instance, str):
            errors.append(f"`instance_id` must be the id of the test that holds this Then, or null, got {instance!r}")
        if row.get("owner") is not None:
            errors.append("`owner` must be absent: a Then behind a red check is not left with anybody, it waits for the fix")
        return errors
    owner = row.get("owner")
    if owner is not None and owner not in THEN_REMAINDER_OWNERS:
        errors.append(f"`owner` must be one of {', '.join(THEN_REMAINDER_OWNERS)} (or absent: it then reads "
                      f"{THEN_REMAINDER_DEFAULT_OWNER}), got {owner!r}")
    detail = row.get("detail")
    if not (isinstance(detail, str) and detail.strip()):
        errors.append("`detail` must say what the owner does (the steps or the command), and is empty")
    if row.get("instance_id"):
        errors.append("`instance_id` must be null: a Then left with its owner has no test of its own "
                      "(a Then a test proves is bound to it, and is not left)")
    part = row.get("part")
    if part is not None and not isinstance(part, str):
        errors.append(f"`part` must be a string naming the part of the Then the owner checks, got {part!r}")
    return errors


def then_remainders(manifest: dict, cfg=None, reasons=(HANDED_TO_PERSON,), triage=None, report=None) -> list:
    """[{case, case_id, then, owner, part, detail, reason}] — the Thens this story left as remainders, in the
    manifest's order; by default the Thens left with their owner (`reasons`, see `then_remainder_rows`). Rows whose
    `then` is no clause number are not here (the precheck refuses them through `then_remainder_rows`); an absent or
    unknown `owner` reads `person`, the reason word's own meaning.

    A `blocked_by_check` row (only when `reasons` asks for it) also carries `blocking_check` and `instance_id` (the
    test that holds the Then, or None) and has NO owner: its `owner` is `""`, not `person` - nobody holds a Then that
    waits for a fix. `reason` is on every row, so a reader that asked for both tells them apart without a second
    pass; the rows of the default call are the rows it returned before, plus that key.

    `triage` and `report` (R6, t-1508; both, else neither is read): when `reasons` asks for `blocked_by_check`, the Thens
    the CURRENT triage names as waiting (`triage_blocked_rows`, rows bound to this run's failures) join the manifest's,
    one row per (case, Then) - a Then in both is listed once, the manifest's row first - and a manifest row for a Then
    that ran and failed (`red_blocked_rows`) is left out: an executed red Then is never read as one that waits. A triage
    row also carries `diagnostic` (`{evidence, outcome}` or None). Without them the rows are what they were."""
    out = []
    dropped = red_blocked_rows(manifest, report, cfg) if (triage is not None and report is not None
                                                          and BLOCKED_BY_CHECK in reasons) else []
    for row in then_remainder_rows(manifest, cfg, reasons):
        if any(row is d for d in dropped):
            continue
        then = row.get("then")
        if isinstance(then, bool) or not isinstance(then, int) or then < 1:
            continue
        case = str(row.get("case") or "").strip()
        try:
            bare = split_case_key(case)[1] or case
        except Exception:
            bare = case
        owner = row.get("owner")
        part = row.get("part")
        reason = str(row.get("reason") or "")
        item = {"case": case, "case_id": bare, "then": then,
                "owner": owner if owner in THEN_REMAINDER_OWNERS else THEN_REMAINDER_DEFAULT_OWNER,
                "part": " ".join(part.split()) if isinstance(part, str) else "",
                "detail": " ".join(str(row.get("detail") or "").split()), "reason": reason}
        if reason == BLOCKED_BY_CHECK:
            instance = row.get("instance_id")
            item.update(owner="", blocking_check=str(row.get("blocking_check") or "").strip(),
                        instance_id=instance if isinstance(instance, str) and instance else None)
        out.append(item)
    if triage is not None and report is not None and BLOCKED_BY_CHECK in reasons:
        have = {(item["case_id"], item["then"]) for item in out if item["reason"] == BLOCKED_BY_CHECK}
        for item in triage_blocked_rows(triage, report, cfg):
            key = (item["case_id"], item["then"])
            if key not in have:
                have.add(key)
                out.append(item)
    return out


def then_handed_words(pipeline: dict) -> dict:
    """{(case key, Then number): {"words", "at"}} — the Thens the person took, from their own words.

    Read from `stage_overrides[]` like every block a person's word passes (`waiver.py --stage S5 --block "then handed:
    <case>#<n>[,<n>...]"`): a live S5 record with words, whose `match` is the prefix and ONE token (`prefix_value`).
    A word joins a row by IDENTIFIER equality only (the case key as the row spells it, the Then number): never a
    substring, never `*`, never `partial-green` (FR-12). Error direction: toward NO entry, which leaves the remainder
    refused. A value that does not parse (an empty case, `#0`, `#4.5`, `#four`, a trailing comma, a missing `#`) gives
    none, and so does a revoked record, another stage, or a pipeline that is no object."""
    out: dict = {}
    for value, entry in stage_override_values(pipeline, THEN_HANDED_MATCH_PREFIX):
        case, hash_, numbers = value.rpartition("#")
        parts = numbers.split(",")
        if not (hash_ and case and all(_THEN_NUMBER_RE.fullmatch(p) and int(p) >= 1 for p in parts)):
            continue
        for part in parts:
            out[(case, int(part))] = {"words": str(entry.get("decision") or "").strip(), "at": str(entry.get("at") or "")}
    return out


# --- a stand gap carries its own fix ----------------------------------------------------
# TP1-15045 (S5, 22.09.2026): the automator found the exact cause of a blocked partition
# (`customer-config.yaml:304-311`, `features:subWorkflow enabled: false`) and the manifest
# carried only a `detail` sentence, so the person read "blocked_by_env" instead of the one
# line that would have unblocked it. A `remedy` is the fix in a machine-readable shape: what
# kind of thing is missing, where it lives (a file with lines or a variable NAME — never a
# value), what to set, and what to restart afterwards.
# `reporter` (0.7.19): the profile's runner writes no report the factory can parse — the
# Karma of TP2-2553 ran `progress`/`kjhtml` and had no `karma-junit-reporter`; the gate
# A rehearsal proves the reporter on one existing test and cards the gap the same four ways.
REMEDY_KINDS = ("flag", "credential", "data", "service", "reporter")
REMEDY_FIELDS = ("kind", "where", "change")
# The remedy of a case the person accepted as blocked at gate A (`planning_contract.apply_gate_answers`,
# O7) is derived from the case's own precondition items, so it needs no new REMEDY kind: the item's
# `kind` (gate_preflight.PRECONDITION_KINDS) maps to the remedy kind that names the same thing.
# Without a remedy `acceptance.blocked_instances` answers `no_remedy` and the accepted case still gets
# run and judged as a failure - the card's promise ("S5 reports exactly these as not executed") broken.
REMEDY_KIND_OF_PRECONDITION = {"feature_flag": "flag", "data": "data", "account": "credential",
                               "env": "credential", "service": "service"}
# The person's answer to a stand-gap card, recorded where every decision of theirs lands:
# `stage_overrides[]` through `waiver.py --stage <S> --block "stand gap: <gap id>"`. The gap
# id is the precondition id (`PC-1`) at gate A or the case key (`area/TC-007`) at gate B.
STAND_GAP_MATCH_PREFIX = "stand gap:"
# What the person chose: the factory applies the change on their word (`apply`), they apply
# it themselves (`theirs`), the case is handed to them to run where the prerequisite exists
# (`handed`, the `handed_to_person` row), or the gap is accepted as blocked (`accept`).
STAND_GAP_OPTIONS = ("apply", "theirs", "handed", "accept")
_SECRET_VALUE_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9+/=_\-\.]{16,}$")


def remedy_errors(remedy) -> list:
    """Why a `remedy` object is not one — empty when it is. Names only: a `change` that reads
    like a token is refused so that a credential never lands in an artifact."""
    if not isinstance(remedy, dict):
        return ["remedy must be an object {kind, where, change, restart?}"]
    errors = []
    kind = str(remedy.get("kind") or "")
    if kind not in REMEDY_KINDS:
        errors.append(f"remedy.kind must be one of {' | '.join(REMEDY_KINDS)}")
    for field in ("where", "change"):
        if not str(remedy.get(field) or "").strip():
            errors.append(f"remedy.{field} is empty")
    change = str(remedy.get("change") or "").strip()
    if kind == "credential" and _SECRET_VALUE_RE.match(change):
        errors.append("remedy.change looks like a secret value - name the variable, never its value")
    if "restart" in remedy and not isinstance(remedy.get("restart"), str):
        errors.append("remedy.restart must be a string (what to restart), when present")
    return errors


def stand_gap_id(match) -> str:
    """The gap id a `stage_overrides[]` record's `match` names: `stand gap: `TC-7`` -> `TC-7`;
    "" when the text does not start (any case) with STAND_GAP_MATCH_PREFIX, e.g. `tracker route`."""
    text = " ".join(str(match or "").split())
    if not text.lower().startswith(STAND_GAP_MATCH_PREFIX):
        return ""
    return text[len(STAND_GAP_MATCH_PREFIX):].strip("`\"' ")


def _answer_moment(value) -> float:
    """When an answer was given, as a number to compare: an ISO stamp (`Z` and a naive one read as
    UTC). An empty or unparseable `at` is the oldest moment there is, so a well-formed answer always
    beats it."""
    text = str(value or "").strip()
    try:
        if text[-1:] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        moment = datetime.datetime.fromisoformat(text)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        return moment.timestamp()
    except Exception:
        return float("-inf")


def stand_gap_decisions(pipeline: dict) -> dict:
    """{gap_id: {"option", "words", "at", "stage"}} — the person's answers to stand-gap cards, read from
    `stage_overrides[]` like `handed_profiles`. The option is the first word of the decision
    when it is one of STAND_GAP_OPTIONS (the driver writes it there from the closed list of
    `references/question-vocabulary.json`); any other wording is kept whole under `words` with
    `option` empty, so a free-text answer is never misread as one of the four.

    ONE reader for every consumer (the delivery check, the guard's `apply` grant, the gate cards, the
    dashboard). Several records of one gap id are one story told in turns: the latest `at` wins whatever
    its stage (`Z` and a naive stamp read as UTC; an empty or unparseable `at` counts as the oldest;
    equal stamps - the later record in the list). A record the person revoked (`revoked_at` set) is read
    by nobody: it opens nothing and accepts nothing, and an id whose every record is revoked is absent.
    A revoked record also stands the older live answers of its id down (`stand_gap_live_entries`). A non-dict entry, a
    blank decision and an empty gap id are skipped."""
    out: dict = {}
    for record in stand_gap_live_entries(pipeline):          # in `_order`: the last record of an id is the one in force
        entry = record["entry"]
        decision = str(entry.get("decision") or "").strip()
        first = decision.split()[0].strip(":,.").lower()
        out[record["key"]] = {"option": first if first in STAND_GAP_OPTIONS else "", "words": decision,
                              "at": record["at"], "stage": record["stage"]}
    return out


def stand_gap_live_entries(pipeline) -> list:
    """The stand-gap records in force, each `{key, stage, at, moment, pos, entry}` (`key` = the gap id, `moment` =
    `_answer_moment(at)`, `pos` = the place in `stage_overrides[]`), sorted by `(moment, pos)` - the order in which the
    latest answer of an id comes last. The ONE reader of which stand-gap record lives; `stand_gap_decisions` and
    `stand_gaps._live_records` both call it, so they cannot disagree (AR-13, AR-15).

    A record is live when it is an object with a gap id, a non-empty decision and no `revoked_at`, AND the same gap id
    has no REVOKED record with a later key `(moment of its `at`, position)`: taking back the latest word of a gap does not
    bring an older answer of another stage back to life (S5 `accept` at t1, S9 `theirs` at t3, S9 revoked: no answer,
    the person is asked - B-376). The key compared is the record's `at`, not its `revoked_at`; so an older record revoked
    later does not put down a newer live one (S5 `accept` t1 revoked at t4, S9 `theirs` t3 stays), and a new answer after
    the revocation is later than it and stands. An empty or unreadable `at` is the oldest moment. A pipeline that is no
    object, a `stage_overrides` that is no list: [] (AR-28)."""
    overrides = pipeline.get("stage_overrides") if isinstance(pipeline, dict) else None
    live: list = []
    revoked: dict = {}                                       # gap id -> the latest key of a revoked record
    for position, entry in enumerate(overrides if isinstance(overrides, list) else []):
        if not isinstance(entry, dict):
            continue
        key = stand_gap_id(entry.get("match"))
        if not key:
            continue
        moment = _answer_moment(entry.get("at"))
        if entry.get("revoked_at"):
            revoked[key] = max(revoked.get(key, (float("-inf"), -1)), (moment, position))
        elif str(entry.get("decision") or "").strip():
            live.append({"key": key, "stage": str(entry.get("stage") or ""), "at": str(entry.get("at") or ""),
                         "moment": moment, "pos": position, "entry": entry})
    live = [r for r in live if r["key"] not in revoked or (r["moment"], r["pos"]) > revoked[r["key"]]]
    return sorted(live, key=lambda r: (r["moment"], r["pos"]))


def replaces_tail(replaced) -> str:
    """The tail a recorded decision carries when the person wrote the same thing more than once: ` (replaces their earlier line:
    <the earlier lines, joined by "; ">)`; '' when there is no earlier line (`replaced` empty or None). One element has no `; `."""
    return " (replaces their earlier line: " + "; ".join(replaced) + ")" if replaced else ""


def person_decision(word: str, line: str, replaced=()) -> str:
    """The decision text the driver records for a line the person wrote: `<word> - the person wrote: <line>` and, when they wrote
    it more than once, the earlier lines it replaces (`replaces_tail`). The WRITER whose reader is `stand_gap_decisions`: that
    reader takes the decision's first word as the option, so `word` goes first, as it is given (t-666 R2)."""
    return f"{word} - the person wrote: {line}" + replaces_tail(replaced)


# --- traceability: the report's appendix and the dashboard's case rows share one vocabulary ---
# One row per requirement x case (x Then group when one test proves two requirements with
# different assertions). The result is a closed, human list: what the person reads is the
# outcome, never the factory's own state names (`partial`, `review_skipped`, `ti_...`).
TRACE_RESULTS = ("pass", "bug", "wait", "blocked", "not run", "unreachable", "deferred", "not planned")
TRACE_LEVELS = ("unit", "component", "api", "integration", "e2e-ui", "manual-agent", "manual-human")  # PLAN_LEVELS + the two human lanes
TRACE_SHAPES = ("new", "extend", "reuse", "parameterize", "consolidate")
TRACE_ROW_FIELDS = ("requirement", "what", "case", "then", "tests", "level", "shape", "result", "bug", "basis")
TRACE_FILE = "traceability.json"  # under work/, written by traceability.py --write
# Size in pipeline.json: `size` is the current call; `size_initial` the first one recorded at S2,
# `size_final` the last, `size_reason` the words behind a call that differs from the formula.
SIZE_KEYS = ("size", "size_initial", "size_final", "size_reason")
CASE_TITLE_RE = re.compile(r"^\s*title:\s*(.+?)\s*$", re.MULTILINE)


# --- gate questions: a question the person can answer carries its readings ---------------
# TP1-15045, gate A: "where must a removed node appear when the YAML has no layout meta?"
# stayed unanswered through the whole story, and the factory then tested the letter of AC-4
# ("shown at its former position") with a 1 px coordinate check — while the implementing
# developer's comment on the parent ticket said positions in the diff are re-laid out and mean
# nothing. Put to the owner as "the source says X; reading 1 (from the AC): coordinates;
# reading 2 (from the developer's comment): the place in the structure; what changes with
# each", the same question was answered in one minute. A question without readings is not a
# question, it is a note the person scrolls past.
QUESTION_FIELDS = ("id", "question", "source_says", "readings", "severity", "owner_role",
                   "before", "now")  # `before`/`now`: only a behaviour-claim question (below), both or neither
READING_FIELDS = ("reading", "from", "if_chosen")
QUOTE_FIELDS = ("quote", "where")
BEFORE_NOW_FIELDS = ("value", "where")
# `claim` (t-227, P20): the origin of the two readings of a before/now question. The behaviour NOW
# is shown to the person as data, never as `from: code` - a reading that says "code" is the
# implementation voting for itself, which is the mistake the question exists to catch.
CLAIM_ORIGIN = "claim"
READING_ORIGINS = ("acceptance_criteria", "description", "comment", "parent_ticket", "code",
                   "test", "precedent", "person", CLAIM_ORIGIN, "attachment")


def question_errors(question, norm_ids=None) -> list:
    """Shape errors of one gate question; [] when a person can answer it as it stands.

    A question written before 0.7.16 is a bare `{question, severity, owner_role}`; readers
    still show it, the gate rehearsal names it as something the requirements tester rewrites.
    `norm_ids` (`norm_row_ids` of the register; None = unknown, the rule is inert): the norms-list question
    (`is_norms_question`) carries no reading `from: code` - the code is no oracle of a norm (F5 b, t-1692 B2)."""
    if not isinstance(question, dict):
        return ["question is not an object"]
    errors = []
    if not str(question.get("question") or "").strip():
        errors.append("question.question is empty")
    quotes = question.get("source_says")
    # X2-6: a ROLE's question (the register row carries `asked_by`) names what the role READ (`read`; an absent `read` is `read_missing`,
    # E-X2-6a), not quotes of a source - it needs no `source_says`; a quote it does give is still checked below
    role_asked = bool(str(question.get("asked_by") or "").strip())
    if not isinstance(quotes, list) or not quotes:
        if not role_asked:
            errors.append("question.source_says names no quote (what the source says, and where)")
    else:
        for i, q in enumerate(quotes):
            if not isinstance(q, dict) or not all(str(q.get(k) or "").strip() for k in QUOTE_FIELDS):
                errors.append(f"question.source_says[{i}] needs quote and where")
    readings = question.get("readings")
    if not isinstance(readings, list) or len(readings) < 2:
        errors.append("question.readings has fewer than two readings — one reading is a decision, not a question")
    else:
        for i, r in enumerate(readings):
            if not isinstance(r, dict):
                errors.append(f"question.readings[{i}] is not an object")
                continue
            for k in READING_FIELDS:
                if not str(r.get(k) or "").strip():
                    errors.append(f"question.readings[{i}].{k} is empty")
            if str(r.get("from") or "").split(":")[0] not in READING_ORIGINS:
                errors.append(f"question.readings[{i}].from must start with one of {', '.join(READING_ORIGINS)}")
    errors.extend(norms_question_errors(question, norm_ids))
    errors.extend(before_now_errors(question))
    return errors


def norms_question_errors(question, norm_ids) -> list:
    """The part of `question_errors` that is about the norms-list question: a reading `from: code` on it is refused (the code is no
    oracle of a norm). The question says what it is by the marker `norms_list: true` (D1-B, B7): a marked question that names a row
    which is no norm is refused. (The spec's second error, "the structural rule holds without the mark", is NOT written: it contradicts
    the port's pins that an unmarked norms question passes - returned to the coordinator.) [] for any other question, and when
    `norm_ids` is empty or None (the marker is inert then)."""
    if not norm_ids or not isinstance(question, dict):
        return []
    errors = []
    if question.get("norms_list") is True:
        qid = question.get("id") or "?"
        stray = sorted(named_r_ids(question) - set(norm_ids), key=lambda r: int(r[2:]))
        errors += [f"question {qid} is marked `norms_list` but names {r}, which is no norm row - fix: remove {r} from it, or drop the "
                   "mark and ask it as a fork question" for r in stray]
    if not is_norms_question(question, norm_ids):
        return errors
    readings = question.get("readings")
    return errors + [f"question.readings[{i}].from is `code` on the question that lists the norms - the code is no source of a norm, so no "
                     "reading drops the norm on its word; fix: the norm is the default reading, and a reading that says it does not apply is "
                     "the person's own wording (`from: person`)"
                     for i, r in enumerate(readings if isinstance(readings, list) else [])
                     if isinstance(r, dict) and str(r.get("from") or "").split(":")[0] == "code"]


def before_now_errors(question) -> list:
    """Shape errors of the `before` / `now` a behaviour-claim question carries; [] for a question
    that carries neither (every question written before t-227) or both, well-formed.

    The pair is all or nothing: the person is asked to choose between two behaviours, so a
    question showing only one of them asks nothing. `value` is what the behaviour is (a status
    code, a text, `unknown` when the base revision cannot be read - FR-41, never a guess) and
    `where` is where it was read. Both readings come from `claim`: a reading from `code` would
    present the implementation as a source of the requirement (P20)."""
    if not isinstance(question, dict):
        return []
    present = [key for key in ("before", "now") if key in question]
    if not present:
        return []
    errors = []
    for key in ("before", "now"):
        if key not in question:
            errors.append(f"question carries `{present[0]}` but no `{key}`: a before/now question shows both")
            continue
        side = question.get(key)
        if not isinstance(side, dict) or not all(str(side.get(k) or "").strip() for k in BEFORE_NOW_FIELDS):
            errors.append(f"question.{key} needs {' and '.join(BEFORE_NOW_FIELDS)} "
                          "(what the behaviour is, and where it was read; `unknown` when nothing can be read)")
    readings = question.get("readings")
    for i, r in enumerate(readings if isinstance(readings, list) else []):
        if isinstance(r, dict) and str(r.get("from") or "").split(":")[0] != CLAIM_ORIGIN:
            errors.append(f"question.readings[{i}].from must be `{CLAIM_ORIGIN}` on a before/now question "
                          "(the behaviour now is shown as data, never as `from: code`)")
    return errors


# The ONE carrier of the meanings of a before/now question's two readings, in the order the code writes them
# (HF4-7): `now` - the behaviour now is the expected one; `before` - a regression, the behaviour before is.
# A reading carries its meaning in the field `claim`; a case's `question_thens` entry for such a question is
# keyed by these two words, never by letter (run 12586, Q7: the case wrote `a` for "rejected", the person
# read `a` as "the behaviour now").
CLAIM_KEYS = ("now", "before")


def claim_readings(before_value: str, now_value: str) -> list:
    """The FIXED pair of readings of a before/now question, in this order, with no default
    (F13/C9): the behaviour now is intended, or it is a regression of the behaviour before. The
    person's own wording is always open to them and is never written as a third reading. Each
    reading says what it means in `claim` (`CLAIM_KEYS`, `now` first)."""
    before = str(before_value or "").strip()
    now = str(now_value or "").strip()
    if not before or before.lower() == "unknown":
        regression = "A regression: the behaviour before the change is the expected one - unknown; say what it was."
        regression_chosen = ("The expected value of the Then is what you say the behaviour was before the "
                             "change; the behaviour now is reported as a defect.")
    else:
        regression = f"A regression: the behaviour before the change is the expected one ({before})."
        regression_chosen = (f"The expected value of the Then is the behaviour before the change ({before}); "
                             "the behaviour now is reported as a defect.")
    return [
        {"reading": f"Intended: the behaviour now is the expected one ({now}).", "from": CLAIM_ORIGIN,
         "if_chosen": f"The expected value of the Then is the behaviour now ({now}); the Then is checked against it.",
         "claim": CLAIM_KEYS[0]},
        {"reading": regression, "from": CLAIM_ORIGIN, "if_chosen": regression_chosen, "claim": CLAIM_KEYS[1]},
    ]


def is_claim_question(question) -> bool:
    """Is this a before/now question - one whose readings are the fixed pair? The ref `raise` (a question the
    case designer asks for and the S4 exit raises) always is; a register row is when any of its readings carries
    `claim` - the one marker the designer is told - or it is the code's own pair written before the marker existed
    (`claim_reading_index` (ii)). A row that only SHOWS `before` and `now` is not (`claim_mark_problem` names it).
    Presence only: a malformed pair is `before_now_errors`'."""
    if question == RAISE_REF:
        return True
    if not isinstance(question, dict):
        return False
    readings = question.get("readings")
    if isinstance(readings, list) and any(isinstance(r, dict) and "claim" in r for r in readings):
        return True
    return claim_reading_index(question, CLAIM_KEYS[0]) is not None


def claim_reading_index(question, key):
    """The position (0 = a, 1 = b) of the reading of `question` that means `key` (`now` | `before`), or None
    when the question does not say. Which reading is the behaviour now is DATA, in this order: (i) the readings
    carry `claim` - exactly the two words, once each; (ii) they carry none, and their texts are byte for byte
    those of `claim_readings(before.value, now.value)` - every question the code raises (`raise_for_case`,
    `claim_projector`): an equality test on the code's own pair, not a guess; (iii) anything else - a question
    the requirements tester wrote without `claim`, an unknown word, two readings with one meaning, three
    readings, a key in another case - None. The error direction is "the question does not say" (FR-41, FR-59)."""
    if key not in CLAIM_KEYS or not isinstance(question, dict):
        return None
    readings = question.get("readings")
    if not isinstance(readings, list) or len(readings) != 2 or not all(isinstance(r, dict) for r in readings):
        return None
    if any("claim" in r for r in readings):
        marks = [r.get("claim") for r in readings]
        if marks == list(CLAIM_KEYS) or marks == list(reversed(CLAIM_KEYS)):
            return marks.index(key)
        return None
    before, now = question.get("before"), question.get("now")
    if not isinstance(before, dict) or not isinstance(now, dict):
        return None
    pair = claim_readings(before.get("value"), now.get("value"))
    if [r.get("reading") for r in readings] == [p["reading"] for p in pair]:
        return CLAIM_KEYS.index(key)
    return None


def _claim_letter(question, key):
    """The reading letter that means `key`, or None. A question that lists no `readings` at all (a bare row, as the
    older readers and tests hand over) is read as the code's own pair: now = a, before = b."""
    if isinstance(question, dict) and not isinstance(question.get("readings"), list):
        return {CLAIM_KEYS[0]: CLAIM_INTENDED, CLAIM_KEYS[1]: "b"}.get(key)
    index = claim_reading_index(question, key)
    return None if index is None else string.ascii_lowercase[index]


NOT_NEEDED_KEY = "not_needed"   # the key of the `not needed` answer in a plan row's `if_answered` and a case's `question_thens`
CLAIM_NOT_MARKED = "the question does not mark which reading is the behaviour now"


def reading_letters(question) -> list:
    """The reading letters of a register question: its own `letters`, else a, b, ... by the number of readings."""
    if not isinstance(question, dict):
        return []
    letters = question.get("letters")
    if isinstance(letters, (str, list)):
        return [str(x) for x in letters]
    readings = question.get("readings")
    return list(string.ascii_lowercase[:len(readings)]) if isinstance(readings, list) else []


def question_then_keys(question) -> list:
    """The keys a case's `question_thens` entry for `question` is written under: `["now", "before"]` for a before/now
    question and for the ref `raise`; the reading letters of every other question."""
    return list(CLAIM_KEYS) if is_claim_question(question) else reading_letters(question)


def question_then_text(question, entry, answer) -> tuple:
    """(text | None, why): what one `question_thens` entry of a case says for `answer`, a reading letter or `not_needed`.

    THE one reader of "does this entry carry the text of this answer" (HF4-7, AR-13): the gate card, the resolver and
    the late-answer applier / `variant_errors` all ask here. An EMPTY text is a text ("this answer asserts nothing
    here"); None is "no text is written for this answer", with the reason in `why`.
    A before/now question's entry is keyed `now` / `before`: the letter is turned into the reading it names, the
    reading into its meaning (`claim_reading_index`), the meaning into the key - the case never decides which letter
    is which. A question that does not say which reading is which gives no text (iii). An entry keyed by LETTER on such
    a question is read by letter only when the person has ALREADY answered that letter (they chose on the card where
    that text stood under it); for an open question no text is put under a letter it was not written for."""
    if not isinstance(entry, dict):
        return None, "the case holds no entry for this question"
    if answer == NOT_NEEDED_KEY:
        text = entry.get(NOT_NEEDED_KEY)
        return (text, "") if isinstance(text, str) else (None, "the case writes no text for `not needed`")
    if not isinstance(answer, str) or not answer:
        return None, "there is no reading letter"
    readings = entry.get("readings")
    if not isinstance(readings, dict):
        return None, "the case gives no readings for this question"
    if not is_claim_question(question):
        text = readings.get(answer)
        if isinstance(text, str):
            return text, ""
        return None, CLAIM_NOT_MARKED if any(key in readings for key in CLAIM_KEYS) else f"the case has no text for reading {answer}"
    if any(key in readings for key in CLAIM_KEYS):
        position = string.ascii_lowercase.find(answer) if len(answer) == 1 else -1
        keys = [k for k in CLAIM_KEYS if position >= 0 and claim_reading_index(question, k) == position]
        if not keys:
            unmarked = isinstance(question, dict) and claim_reading_index(question, CLAIM_KEYS[0]) is None
            return None, CLAIM_NOT_MARKED if unmarked else f"reading {answer} has no meaning here"
        text = readings.get(keys[0])
        return (text, "") if isinstance(text, str) else (None, f"the case has no text for `{keys[0]}`")
    answered = (isinstance(question, dict) and question.get("status") == "answered"
                and str(question.get("reading") or "").strip() == answer and question.get("changed_since_answer") is not True)
    text = readings.get(answer)
    if answered and isinstance(text, str):
        return text, ""
    shown = "; ".join(f'{k}: "{" ".join(str(v).split())[:100]}"' for k, v in readings.items())
    return None, ("the case gives its texts by letter, which does not say which reading each belongs to on a "
                  f"before/now question (its texts, tied to no reading: {shown}); the case goes back to its designer")


def claim_mark_problem(question) -> str:
    """"" or what is wrong with a before/now question that does not say which reading is the behaviour now (`claim` on
    each reading), for the rehearsal of gate A to hand to the requirements tester. "" for a question that is no
    before/now one, one that marks its readings, and one built from the code's own pair."""
    if not isinstance(question, dict) or not (is_claim_question(question) or ("before" in question and "now" in question)):
        return ""
    if claim_reading_index(question, CLAIM_KEYS[0]) is not None and claim_reading_index(question, CLAIM_KEYS[1]) is not None:
        return ""
    return (f"it shows before/now but its readings do not say which is the behaviour now: give each reading `claim: "
            f"{'|'.join(CLAIM_KEYS)}`, once each - the case's texts cannot be tied to a reading without it")


# --- where an expected value comes from (t-227, P20: code is never an oracle) ------------------
# TP1-15045, cmp2, TC_015: Then 2 said `403` and Then 4 "equal to the expected value". The 403
# was read off the diff (the very change under test) and labelled "the pre-refactor contract"; the
# base revision answered 400. A test whose expected value is read from the implementation can only
# pass. So every Then of a case names where its expected value comes from, in a closed list, and a
# requirement that exists only in the diff is a BEHAVIOUR CLAIM the person confirms or rejects.
# The words live here beside READING_ORIGINS (FR-13 house pattern; `vocabularies.md` maps them to
# the basis prefixes, t-227c); `code` is deliberately not one of them.
#
# The rule is dated, not retroactive (law FB-12): a case `updated` before ORACLE_CUTOFF, and a
# register or plan `created` before it, are never refused for lacking these fields. By DAY: every
# cmp2 artifact (01.10) stays legacy.
ORACLE_CUTOFF = "2026-10-02"
# `requirement` is the word a case now writes for a register requirement of ANY ticket source (P23: the
# description, a criterion, a comment, an attachment, a linked ticket); `ac` stays legal for ever as the
# older name of the same thing - a case saved with it reads as it did (FR-14, FR-40) - and is never
# rewritten: the resolver returns the word as stored. ONE tuple names the words whose ref is an R-n.
REQUIREMENT_ORACLE_WORDS = ("requirement", "ac", "spec")
THEN_ORACLE_WORDS = ("requirement", "ac", "spec", "precedent", "person", "unknown")
THEN_ORACLE_FIELDS = ("then", "source", "ref")
# `code` is never an oracle, whatever a data file says (P20, FR-58): the floor `then_oracle_errors` hands to the door check.
THEN_ORACLE_NEVER = ("code",)
OPEN_VOCABULARIES_PATH = Path(__file__).resolve().parent.parent / "references" / "open-vocabularies.json"


def open_word_errors(value, words, vocabulary: str, *, never=()) -> list:
    """Why `value` is not acceptable for a PROPOSED list (spec t-1765 F-3 (b)), one line per problem; [] when it is.

    Acceptable: a word of `words`, or the door `new: <word> -- <why>` - the word 2-40 characters of `door.word_re`, the reason
    at least `door.min_reason_chars` after trimming (both in `references/open-vocabularies.json`, the one reader, AR-1/AR-13).
    A word of the vocabulary's `never` (and of the caller's `never`, a floor the data cannot lower) is refused ALWAYS, as a
    plain word and as `new: <word> -- ...`, compared lowercased and BEFORE the word shape (FR-58: `code` has no door).
    Form only: whether the new word is needed, and whether it hides a banned one, is the stage critic's judgment (AR-29).
    The file unreadable, or no such vocabulary: a word outside the list is refused as unreadable - never a pass (AR-28);
    a word OF the list needs no file."""
    options = [str(word) for word in words]
    text = str(value if value is not None else "").strip()
    shown = text[:60]
    if text in options:
        return []
    floor = {str(word).lower() for word in never}
    try:
        data = json.loads(OPEN_VOCABULARIES_PATH.read_text(encoding="utf-8"))
        door, entry = data["door"], data["vocabularies"][vocabulary]
        prefix, separator = str(door["prefix"]), str(door["separator"])
        shape, minimum = re.compile(str(door["word_re"])), int(door["min_reason_chars"])
        banned = floor | {str(word).lower() for word in entry.get("never") or []}
        is_open = entry.get("open") is True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, re.error) as exc:
        banned = floor
        if text.lower() in banned:
            return [f"'{shown}' is never a value of {vocabulary}: no door lifts it"]
        return [f"'{shown}' is not one of {' | '.join(options)} and the door file references/open-vocabularies.json "
                f"cannot be read for {vocabulary} ({type(exc).__name__}): unreadable, not a pass"]
    never_text = (f"'{shown}' is never a value of {vocabulary} (not as `{prefix} <word> -- <why>` either): "
                  "no door lifts it")
    door_text = (f"one of: {', '.join(options)}" + (f" or `{prefix} <word> -- <why>` (a new word of 2-40 lowercase letters, "
                 f"digits, - or _, and a reason of at least {minimum} characters)" if is_open else " (this list is closed)"))
    if text.lower() in banned:
        return [never_text]
    if not text.startswith(prefix):
        return [f"'{shown}' is not {door_text}"]
    if not is_open:
        return [f"'{shown}': the {vocabulary} list is closed - write {door_text}"]
    word, found, why = text[len(prefix):].partition(separator)
    word, why = word.strip(), why.strip()
    if not found:
        return [f"'{shown}' has no reason: write `{prefix} <word> -- <why>`, the reason after `{separator.strip()}`"]
    if word.lower() in banned:
        return [never_text]
    if not shape.match(word):
        return [f"'{shown}': the new word '{word[:60]}' must match {shape.pattern} (2-40 lowercase letters, digits, - or _, "
                "starting with a letter)"]
    if len(why) < minimum:
        return [f"'{shown}': the reason is {len(why)} characters, at least {minimum} are needed - say why no word of the list fits"]
    return []


# What a word needs as its `ref`: R-n for requirement/ac/spec; for precedent the BASE revision's behaviour
# (`base:<rev>:<path>:<line>`, F4 - a requirement names a parity with OLDER behaviour); a question id for
# person/unknown (the register's own ids, `Q1`, not an alias).
# A second form (t-2181 PC-9a): `reference:<item>`, an item of the story's reference snapshot (the OLD version walked on its own stand);
# C7 inside `then_oracle_errors` ties it to a snapshot item and a parity requirement.
REFERENCE_ITEM = r"[A-Za-z0-9][A-Za-z0-9._-]*"
REFERENCE_REF_RE = re.compile(rf"^reference:({REFERENCE_ITEM})$")
BASE_REF_PATTERN = r"base:[^:\s]+:\S+:\d+"
BASE_REF_RE = re.compile(rf"^{BASE_REF_PATTERN}$")   # a claim's `before_ref` takes `reference:<item>` only with `snapshot_items` (PC-9c item check)
PRECEDENT_REF_RE = re.compile(rf"^(?:{BASE_REF_PATTERN}|reference:{REFERENCE_ITEM})$")
REQUIREMENT_BASIS_RE = re.compile(r"requirement:(R-\d+)")
PARITY_YES = "yes"
CLAIM_HEADING = "## Behaviour claims"
# `origin` is LAST and is read only by its header (an old table has no such column - empty means the
# row was written at S2). The seven before it are the S2 columns the validator names to the role.
CLAIM_COLUMNS = ("r", "before", "before_ref", "now", "now_ref", "differs", "question", "origin")
CLAIM_ORIGIN_S3 = "S3-grounding"
# The register's `delta` column (written at S2, LAST after `impact`): does the product already behave as the
# requirement says? Read only by its header - an extra column of a project is never read as `delta`.
DELTA_WORDS = ("new", "changed", "unchanged")
CLAIM_DIFFERS = ("yes", "no", "unknown")
CLAIM_UNKNOWN = "unknown"
CLAIM_ABSENT = "absent"
# A cell that says "nothing here": `-`-like spellings count as empty so that a register written
# with a dash instead of the em dash is still read as "no AC reference" (C10). The error
# direction is toward calling a row a claim - the claim only costs a question, a missed one costs
# a test that can only pass.
EMPTY_CELLS = ("", "-", "—", "–")
_BEFORE_REF_FORMS = "`diff:-<path>:<line>`, `base:<rev>:<path>:<line>`, `screenshot:<ref>` or `absent`"
_FRONT_RE = re.compile(r"\A﻿?---\s*\r?\n(.*?)\r?\n---", re.DOTALL)


def after_oracle_cutoff(value) -> bool:
    """True when a `created` / `updated` date is on or after ORACLE_CUTOFF; an absent or
    unrecognised date is False (the rule does not apply)."""
    found = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return bool(found) and found.group(1) >= ORACLE_CUTOFF


def oracle_date_state(value) -> str:
    """How the oracle rules read one `created` / `updated` value: `dated` (a real date on or after
    ORACLE_CUTOFF: the checks run), `legacy` (a real date before it: they are off, on purpose),
    `missing` (nothing there) or `unparseable` (something there that is no ISO date, `2026-13-45`
    included). The last two are NOT "off": a file whose date cannot be read must say so, because
    `after_oracle_cutoff` alone reads them as legacy and switches every dated check off with no
    word (t-269 F1)."""
    text = str(value or "").strip()
    if not text:
        return "missing"
    found = re.match(r"(\d{4}-\d{2}-\d{2})(?!\d)", text)
    if not found:
        return "unparseable"
    try:
        datetime.date.fromisoformat(found.group(1))
    except ValueError:
        return "unparseable"
    return "dated" if found.group(1) >= ORACLE_CUTOFF else "legacy"


def oracle_date_problem(value, field: str = "created") -> str:
    """The refusal for a `created` / `updated` the dated oracle rules cannot read: names the field,
    what it holds and the form expected; "" when the date reads (dated or legacy). Error direction:
    a date nobody can read is refused, never treated as "before the cutoff" - that is how every
    dated check was switched off without a word."""
    state = oracle_date_state(value)
    if state in ("dated", "legacy"):
        return ""
    held = "empty" if state == "missing" else f"'{str(value).strip()[:40]}'"
    return (f"`{field}` is {held}: the oracle rules (then_oracles, behaviour claims) switch on this date "
            f"(from {ORACLE_CUTOFF}), so it must be an ISO date, YYYY-MM-DD - write `{field}: {ORACLE_CUTOFF}` "
            "(or the day the file was really written)")


def oracle_date_note(value, field: str = "created") -> str:
    """One line for `--verbose`: a file dated before ORACLE_CUTOFF is left alone by the oracle rules,
    and says so ("" for any other state)."""
    if oracle_date_state(value) != "legacy":
        return ""
    return (f"`{field}` {str(value).strip()[:10]} is before {ORACLE_CUTOFF}: the oracle checks "
            "(then_oracles, behaviour claims) are off for this file")


def front_line(text: str, key: str):
    """The raw value of ONE front-matter line (`key: value`), None when the key is absent. The
    front matter is flat (a nested block is lost), so the line is the whole value."""
    block = _FRONT_RE.match(str(text or ""))
    if not block:
        return None
    found = re.search(r"(?m)^" + re.escape(key) + r":[ \t]*(.*?)[ \t]*$", block.group(1))
    return found.group(1) if found else None


def set_front_line(text: str, key: str, value) -> str:
    """`text` with the front-matter line `key: <value>` rewritten in place (`value` a str), or removed
    (`value` None). The text is returned unchanged when it has no front matter or no such line; every
    other byte stays, line endings included. A body line that looks like the key is never touched."""
    text = str(text or "")
    block = _FRONT_RE.match(text)
    if not block:
        return text
    front = block.group(1)
    out, hit = [], False
    for line in front.splitlines(keepends=True):
        if re.match(re.escape(key) + r":", line):
            hit = True
            if value is not None:
                out.append(f"{key}: {value}" + line[len(line.rstrip("\r\n")):])
        else:
            out.append(line)
    if not hit:
        return text
    new_front = "".join(out)
    if not front.endswith("\n") and new_front.endswith("\n"):
        new_front = re.sub(r"\r?\n\Z", "", new_front, count=1)  # the removed line was the last one
    return text[:block.start(1)] + new_front + text[block.end(1):]


def parse_json_list(raw):
    """(list | None, problem): a front-matter value that must be ONE line of JSON holding a list
    of objects. `None` raw (the key is absent) is (None, ""); an empty value, broken JSON, a
    non-list or a non-object entry is (None, <what is wrong>)."""
    if raw is None:
        return None, ""
    items = raw
    if isinstance(raw, str):
        if not raw.strip():
            return None, "the value is empty"
        try:
            items = json.loads(raw)
        except (ValueError, RecursionError):
            return None, "the value is not valid JSON on ONE line"
    if not isinstance(items, list):
        return None, "the value is not a list"
    if not all(isinstance(item, dict) for item in items):
        return None, "an entry is not an object"
    return items, ""


def then_oracles_from_text(text: str):
    """(entries | None, problem) of a case file's `then_oracles` line; None - the key is absent."""
    return parse_json_list(front_line(text, "then_oracles"))


def question_thens_from_text(text: str):
    """(entries | None, problem) of a case file's `question_thens` line; None - the key is absent."""
    return parse_json_list(front_line(text, "question_thens"))


ALTERNATIVE_ID = re.compile(r"ALT-\d{1,3}")        # fullmatch: the id of one declared reading B of a case
ALTERNATIVE_READING_MAX = 300                      # characters of `reading`, after strip
ALTERNATIVE_REF = re.compile(r"R-\d+|Q\d+")        # fullmatch: the requirement or the question that leaves both readings open


def alternatives_from_text(text: str):
    """(entries | None, problem) of a case file's `alternatives` line; None - the key is absent. The ONE reader of the key
    (the validator, the probe and its report call it)."""
    return parse_json_list(front_line(text, "alternatives"))


def alternatives_errors(name: str, raw, thens, known_r=None, questions=None) -> list:
    """Why a case's `alternatives` (the readings B a Then must FAIL under) is not acceptable, one line per problem; [] when it
    is. `raw` the front-matter value (None - the key is absent, which is no claim); `thens` the numbers under `## Then`;
    `known_r` the register's ids and `questions` {id: row} of the readiness file (None - not readable: the shape alone is
    checked). Pure; code checks shape and refs, never what the reading says (FR-12)."""
    if raw is None:
        return []
    entries, problem = parse_json_list(raw)
    if entries is None:
        return [f"{name}: FORM - `alternatives` must be ONE line of JSON, a list of "
                '{"id", "then", "reading", "ref"} objects (for example '
                'alternatives: [{"id": "ALT-1", "then": 2, "reading": "the stamp is taken at completion", "ref": "R-2"}]): '
                f"{problem}"]
    numbers = sorted(n for n in (thens or []) if isinstance(n, int))
    errors, seen_ids, seen_pairs = [], set(), set()
    for item in entries:
        alt = item.get("id")
        if not isinstance(alt, str) or not ALTERNATIVE_ID.fullmatch(alt) or not 1 <= int(alt[4:]) <= 999:
            errors.append(f"{name}: FORM - alternatives `id` {alt!r} must be ALT-<n> with n from 1 to 999")
        elif alt in seen_ids:
            errors.append(f"{name}: FORM - alternatives `id` {alt} is used twice: one id, one reading")
        else:
            seen_ids.add(alt)
        then = item.get("then")
        if isinstance(then, bool) or not isinstance(then, int) or then not in numbers:
            errors.append(f"{name}: FORM - alternatives `then` {then!r} must be an integer naming an item under `## Then` "
                          f"(this case has {', '.join(map(str, numbers)) or 'none'})")
        reading = item.get("reading")
        if not isinstance(reading, str) or not reading.strip():
            errors.append(f"{name}: FORM - alternatives `reading` must be a non-empty string of at most "
                          f"{ALTERNATIVE_READING_MAX} characters naming reading B")
        elif len(reading.strip()) > ALTERNATIVE_READING_MAX:
            errors.append(f"{name}: FORM - alternatives `reading` is {len(reading.strip())} characters, at most "
                          f"{ALTERNATIVE_READING_MAX} are allowed: say reading B shorter")
        else:
            pair = (then, " ".join(reading.split()))
            if pair in seen_pairs:
                errors.append(f"{name}: FORM - alternatives lists Then {then!r} with the same `reading` twice: one reading, one id")
            seen_pairs.add(pair)
        ref = item.get("ref")
        if not isinstance(ref, str) or not ALTERNATIVE_REF.fullmatch(ref):
            errors.append(f"{name}: FORM - alternatives `ref` {ref!r} is required and must be an `R-n` or a `Qn` "
                          "(the requirement or the question that leaves both readings open)")
        elif ref.startswith("R-") and known_r is not None and ref not in known_r:
            errors.append(f"{name}: FORM - alternatives `ref` {ref} is not in the requirements register")
        elif ref.startswith("Q") and questions is not None and ref not in questions:
            errors.append(f"{name}: FORM - alternatives `ref` {ref} is not a question of the readiness file")
    return errors


# --- the register: which requirements exist only in the diff ----------------------------------

def _header_index(header: list, name: str, default: int, exact: bool = False) -> int:
    """The column called `name`. `exact=True` is the form of a column that has NO positional fallback and
    no prefix match (`delta`, `origin`): not found gives `default` (-1), so a project's extra column is never
    read as the value; the caller checks `0 <= i < len(cells)`."""
    lowered = [strip_cell(c).lower() for c in header]
    for i, cell in enumerate(lowered):  # an exact name first: `before` is not `before_ref`
        if cell == name:
            return i
    if exact:
        return default
    for i, cell in enumerate(lowered):
        if cell.startswith(name):
            return i
    return default


def register_rows(text: str) -> list:
    """One dict per row of the `## Register` table: r, requirement, source, derived_from, ac_ref, observable, delta, code_says.
    `requirement` is the column whose header STARTS WITH `Requirement` (the template: `Requirement (one verifiable statement)`);
    a table with no such column is refused with a ValueError naming it (FR-11), never read as rows with an empty key.
    The columns are found by their header; the contract's own order is the fallback - except `delta` and `code_says`, which
    are read only by their header: `None` when the register has no such column (every register written before it
    existed, and a seven-column one), the cell text (possibly empty) when it has. `code_says` is THE reader of that column
    (AR-13): `branch_accounting.code_says_check` and `bug_records.code_reading_problems` parse it, nobody re-reads the table."""
    raw = md_table(text, "## Register")
    if not raw:
        return []
    header, body = raw[0], raw[1:]
    req_at = next((i for i, c in enumerate(header) if strip_cell(c).lower().startswith("requirement")), -1)
    if req_at < 0:
        raise ValueError("the `## Register` table has no `Requirement` column (the template's header is "
                         "`Requirement (one verifiable statement)`); expected a column whose header starts with `Requirement`")
    idx = {"source": _header_index(header, "source", 2), "derived_from": _header_index(header, "derived_from", 3),
           "ac_ref": _header_index(header, "ac_ref", 5), "observable": _header_index(header, "observable", 6)}
    delta_at = _header_index(header, "delta", -1, exact=True)
    says_at = _header_index(header, "code_says", -1, exact=True)
    parity_at = _header_index(header, "parity", -1, exact=True)
    rows = []
    for cells in body:
        rid = strip_cell(cells[0]) if cells else ""
        if not REQ_ID_RE.fullmatch(rid):
            continue
        row = {"r": rid, "requirement": strip_cell(cells[req_at]) if req_at < len(cells) else ""}
        for key, i in idx.items():
            row[key] = strip_cell(cells[i]) if i < len(cells) else ""
        row["delta"] = None if delta_at < 0 else (strip_cell(cells[delta_at]) if delta_at < len(cells) else "")
        row["code_says"] = None if says_at < 0 else (strip_cell(cells[says_at]) if says_at < len(cells) else "")
        row["parity"] = None if parity_at < 0 else (strip_cell(cells[parity_at]) if parity_at < len(cells) else "")
        rows.append(row)
    return rows


def requirement_id(text):
    """The R id a `requirement:R-n` basis/oracle names, or None for any other text (the one reader of that form)."""
    found = REQUIREMENT_BASIS_RE.fullmatch(str(text or "").strip())
    return found.group(1) if found else None


def parity_ids(text: str) -> set:
    """The R ids of the register rows whose `parity` cell is exactly `yes` (S-c: the requirement says the new version behaves as the old
    one did; t-2181 PC-9a). THE reader of that column (AR-13), read only by its header: a register with no such column, an empty cell or
    any other word gives no id - absent means `no`, so a parity `precedent` is refused, never waved through."""
    return {row["r"] for row in register_rows(text) if row.get("parity") == PARITY_YES}


NORM_DERIVED_PREFIXES = ("aspect:", "norm:", "invariant:", "bug:")   # a `derived` row with one of these states a NORM (t-1692 B3: `bug:candidate-defect` too)
NORMS_QUESTION_MIN_ROWS = 2     # a question naming at least this many norm rows (and no other row) is the norms-list question
_NAMED_R_RE = re.compile(r"(?<![\w-])R-\d+(?!\w)")


def norm_row_ids(text: str) -> set:
    """The R ids of the register's norm rows: `source: derived` with a `derived_from` of `NORM_DERIVED_PREFIXES` (a product norm; a
    `bug:` row states its norm too - a failed call is not shown as a success). One reader (AR-13) for the refusals below."""
    return {row["r"] for row in register_rows(text)
            if row["source"] == "derived" and row["derived_from"].strip().lower().startswith(NORM_DERIVED_PREFIXES)}


def named_r_ids(question) -> set:
    """The R ids the text a question shows (`question`, `source_says`) names (REQ whole ids, never a part of a longer word)."""
    held = " ".join(str(question.get(k) or "") for k in ("question", "source_says"))
    return set(_NAMED_R_RE.findall(held))


def _structural_norms_question(question, norm_ids) -> bool:
    """The structural rule alone: at least `NORMS_QUESTION_MIN_ROWS` R ids named, every one a norm row."""
    if not norm_ids or not isinstance(question, dict):
        return False
    named = named_r_ids(question)
    return len(named) >= NORMS_QUESTION_MIN_ROWS and named <= set(norm_ids)


def is_norms_question(question, norm_ids) -> bool:
    """Is this the ONE norms-list question (F5 b)? The marker `norms_list: true` says so (D1-B B7, a field the role writes, never a
    phrase, FR-12); without it the structural rule decides: the text it shows (`question`, `source_says`) names at least
    `NORMS_QUESTION_MIN_ROWS` R ids and every R id it names is a norm row of the register. A question that names one row, or any
    row that is no norm, is a fork question. `False` when there are no norm rows (the world before the rule): the marker is inert."""
    if not norm_ids or not isinstance(question, dict):
        return False
    return question.get("norms_list") is True or _structural_norms_question(question, norm_ids)


def delta_state(row) -> str:
    """`new` | `changed` | `unchanged` | `absent` | `invalid`: what the row's `delta` cell says, and nothing more.
    `absent` - the register has no `delta` column (`register_rows` gave None); `invalid` - the cell is not one of
    DELTA_WORDS exactly (empty, `New`, `same`, `n/a`). The error direction is toward the coverage count: only the
    word `unchanged` can take a row out of it, and not even that alone (the base slice has to show the place
    untouched - G2-2); no prefix of `observable` promotes anything. An unreadable row is `absent`."""
    value = row.get("delta") if isinstance(row, dict) else None
    if value is None:
        return "absent"
    return value if isinstance(value, str) and value in DELTA_WORDS else "invalid"


def _silent_cell(cell: str) -> bool:
    value = strip_cell(cell)
    return value in ("", "silent", "n/a") or value.startswith("n/a:")


def implementation_only(text: str) -> list:
    """The R ids that exist ONLY in the diff, computed from the register text (F10/FR-16: code
    computes it, nobody declares it). All hold: `source: derived`, no `ac_ref`, every cell of the
    contradiction matrix `silent` or `n/a:*` (an R with no matrix row counts as all-silent), and an
    observable that starts with `diff:`. Such an R is a behaviour claim, never a requirement."""
    matrix = {}
    for cells in md_table(text, "## Contradiction matrix")[1:]:
        rid = strip_cell(cells[0]) if cells else ""
        if REQ_ID_RE.fullmatch(rid):
            matrix[rid] = cells[1:]
    out = []
    for row in register_rows(text):
        if (row["source"] == "derived" and row["ac_ref"] in EMPTY_CELLS
                and row["observable"].startswith("diff:")
                and all(_silent_cell(c) for c in matrix.get(row["r"], []))):
            out.append(row["r"])
    return out


def behaviour_claims(text: str) -> list:
    """One dict per row of the `## Behaviour claims` table (CLAIM_COLUMNS, the header names them);
    [] when the section is absent. The `## Register` columns are never touched (F9). `origin` is read by
    its header only: a table without it gives `""` (written at S2), never a neighbouring column."""
    raw = md_table(text, CLAIM_HEADING)
    if not raw:
        return []
    header, body = raw[0], raw[1:]
    idx = {name: (_header_index(header, name, -1, exact=True) if name == "origin"
                  else _header_index(header, name, i))
           for i, name in enumerate(CLAIM_COLUMNS)}
    rows = []
    for cells in body:
        rid = strip_cell(cells[0]) if cells else ""
        if not rid or rid.lower() == "r":
            continue
        row = {name: (strip_cell(cells[i]) if 0 <= i < len(cells) else "") for name, i in idx.items()}
        row["r"] = rid
        rows.append(row)
    return rows


def claim_questions(text: str) -> dict:
    """{R: question id} of the register's behaviour claims (the first row of an R wins)."""
    out: dict = {}
    for row in behaviour_claims(text):
        out.setdefault(row["r"], row["question"])
    return out


CLAIM_INTENDED = "a"  # the default letter of "the behaviour now is the expected one" for the code's own pair; a question is asked via `claim_reading_index`


def claim_confirmed(question) -> bool:
    """Did the person confirm the behaviour NOW as the expected one (O1)? Only reading `a` of the
    fixed pair does, on the text they were shown: reading `b` (a regression: the behaviour before is
    expected), their own wording (no letter), `not_needed`, an open or `named` question and a question
    edited since the answer all leave the claim unconfirmed. Error direction: toward unconfirmed - a
    requirement read from the implementation must never become legal again on the strength of an
    answer that said the implementation is WRONG (cmp2 Q7: `b` made `ac:R-19` legal). A record that
    stores NO row hash (`changed_since_answer` None) cannot say which text the person was shown, so it
    is unconfirmed too (t-269 F5): only a record whose hash matches today's row (False) confirms."""
    if not (isinstance(question, dict) and question.get("status") == "answered"):
        return False
    # the letter of "the behaviour now" is asked of the question (HF4-7, N7-2), not assumed: a question that does not
    # mark its readings has none, and confirms nothing
    intended = _claim_letter(question, CLAIM_KEYS[0])
    return (intended is not None and str(question.get("reading") or "").strip() == intended
            and question.get("changed_since_answer") is False)


def unconfirmed_implementation_only(text: str, questions=None) -> set:
    """The implementation-only R ids whose claim nobody has confirmed: `questions` is
    {question id: register row with `status`, `reading`, `changed_since_answer`}
    (`question_register.load`); a claim is confirmed only by `claim_confirmed` (the person chose
    reading `a`). With no `questions` every implementation-only R is unconfirmed - the safe direction."""
    return set(implementation_only(text)) - _confirmed_claims(text, questions)


def _confirmed_claims(text: str, questions=None) -> set:
    """The R ids whose behaviour claim a person confirmed (`claim_confirmed`); none when there are no `questions`."""
    return {r for r, qid in claim_questions(text).items()
            if isinstance(questions, dict) and claim_confirmed(questions.get(qid))}


# G2-12 (P20): code and somebody else's test are no source of a requirement. The day the rule starts, by the register's own
# `created` (the form of `_oracle_dated`): a register written before it keeps the narrower reading it was written under
# (FR-14, a story in flight is not turned red); `ORACLE_CUTOFF` is older and would refuse such a story.
UNCONFIRMED_SOURCE_CUTOFF = "2026-10-31"
_CODE_OBSERVABLE = "current-code:"
_TEST_DERIVED_FROM = "test:"


def _created_since(text: str, cutoff: str) -> bool:
    """True when the `created` of a register or plan text is on or after `cutoff` - or cannot be read as an ISO date at
    all (no front matter, empty, `yesterday`): the error direction is toward the new reading, which only costs a question."""
    found = re.match(r"(\d{4}-\d{2}-\d{2})(?!\d)", str(front_line(text, "created") or "").strip())
    if not found:
        return True
    try:
        datetime.date.fromisoformat(found.group(1))
    except ValueError:
        return True
    return found.group(1) >= cutoff


def _after_unconfirmed_source_cutoff(text: str) -> bool:
    """True when the register's `created` is on or after UNCONFIRMED_SOURCE_CUTOFF (or unreadable): `_created_since`."""
    return _created_since(text, UNCONFIRMED_SOURCE_CUTOFF)


# G2-10: a table row holds MORE cells than its header only when a bare `|` stands in a cell (the role writes `\|`, see
# `grammar.split_cells`). The day the check starts, by the file's own `created`: a register or plan saved before it
# keeps the reading it was written under (FR-14, a story in flight is not turned red) and gets a warning line instead.
CELL_COUNT_CUTOFF = "2026-10-31"


def after_cell_count_cutoff(text: str) -> bool:
    """True when the `created` of a register or plan text is on or after CELL_COUNT_CUTOFF - or cannot be read (the new
    world: the refusal has a door, writing a real `created`)."""
    return _created_since(text, CELL_COUNT_CUTOFF)


def excess_cell_rows(text: str, heading: str) -> list:
    """`[(first cell, header width, cells found)]` for every row of the table under `heading` that holds a non-empty cell
    BEYOND its header's width - the footprint of a bare `|` in a cell (the cells after it moved into other columns).
    A row SHORTER than the header (an older, narrower table) and trailing empty cells are not excess."""
    table = md_table(text, heading)
    if not table:
        return []
    width = len(table[0])
    return [(row[0], width, len(row)) for row in table[1:] if any(cell.strip() for cell in row[width:])]


def code_sourced_requirements(text: str) -> list:
    """The R ids whose ONLY source is the new code or somebody else's test, read from the register text (nobody declares
    it): `source: derived`, no `ac_ref` (`-`, `n/a` and the like are empty), a contradiction matrix that is silent
    (`silent`, `n/a:*`; an R with no matrix row counts as silent), and an `observable` that starts with `current-code:` or
    a `derived_from` that starts with `test:`. Every comparison ignores case and backticks; the error direction is toward
    the row being listed - a false listing costs a question, a missed one a test that can only pass."""
    matrix = {}
    for cells in md_table(text, "## Contradiction matrix")[1:]:
        rid = strip_cell(cells[0]) if cells else ""
        if REQ_ID_RE.fullmatch(rid):
            matrix[rid] = cells[1:]
    out = []
    for row in register_rows(text):
        ac_ref = row["ac_ref"].lower()
        if (row["source"].lower() == "derived" and (ac_ref in EMPTY_CELLS or ac_ref.startswith("n/a"))
                and (row["observable"].lower().startswith(_CODE_OBSERVABLE)
                     or row["derived_from"].lower().startswith(_TEST_DERIVED_FROM))
                and all(_silent_cell(c.lower()) for c in matrix.get(row["r"], []))):
            out.append(row["r"])
    return out


def unconfirmed_requirements(text: str, questions=None) -> set:
    """The R ids no source confirms: `unconfirmed_implementation_only` plus, for a register `created` on or after
    UNCONFIRMED_SOURCE_CUTOFF, `code_sourced_requirements`; minus the claims a person confirmed (`claim_confirmed`: reading
    `a` of the fixed pair, on the text they were shown). The label is computed, there is no column and no new oracle word:
    a Then resting on such an R reads `unknown` with the claim's question. Errs only toward "not confirmed": no `questions`,
    an unreadable question, `named`, `b`, own words and a row edited since the answer all leave the R in the set.
    `implementation_only` (the diff-only class) is not changed."""
    found = unconfirmed_implementation_only(text, questions)
    if _after_unconfirmed_source_cutoff(text):
        found |= set(code_sourced_requirements(text)) - _confirmed_claims(text, questions)
    return found


def claim_required_requirements(text: str) -> list:
    """The R ids that owe a row under `## Behaviour claims`, in register order: `implementation_only`, plus, for a register
    `created` on or after UNCONFIRMED_SOURCE_CUTOFF (or with an unreadable `created`: toward the new reading, which costs a
    question), `code_sourced_requirements`. A register older than the cutoff owes rows for the diff-only class alone."""
    owed = set(implementation_only(text))
    if _after_unconfirmed_source_cutoff(text):
        owed |= set(code_sourced_requirements(text))
    return list(dict.fromkeys(row["r"] for row in register_rows(text) if row["r"] in owed))


def claim_row_errors(row: dict, questions=None, link_index=None, snapshot_items=None) -> list:
    """What one behaviour-claim row lacks, as short fragments (the validator prefixes the file and
    the R). `questions` is {id: question dict} of requirements-readiness.json, or None when it is
    not there yet (the register may be written before it: the id is then not checked). `link_index`
    is `claim_link_index(questions)` for a caller that checks many rows against the one map.
    `snapshot_items` the ids of the story's reference snapshot (`reference_snapshot.item_ids`), None when there is none or the
    caller gives none: then `before_ref: reference:<item>` is refused as it was before PC-9c (the error direction is refusing)."""
    errors = []
    before, before_ref = row.get("before", ""), row.get("before_ref", "")
    now, now_ref = row.get("now", ""), row.get("now_ref", "")
    differs, qid = row.get("differs", ""), row.get("question", "")
    if not before:
        errors.append("`before` is empty (the behaviour before the change, `absent` for a new path, "
                      "or `unknown` when nothing can be read - never a guess)")
    if before.lower() == CLAIM_UNKNOWN:
        pass  # nothing could be read: the question still goes out, saying so (FR-41)
    elif before.lower() == CLAIM_ABSENT:
        if before_ref not in ("", CLAIM_ABSENT) and before_ref not in EMPTY_CELLS:
            errors.append(f"`before_ref` of an `absent` claim is `{CLAIM_ABSENT}`, not '{before_ref}'")
    elif REFERENCE_REF_RE.match(before_ref) and snapshot_items is not None:
        # t-2181 PC-9c: `reference:<item>` is a legal `before_ref` only for an item of the story's snapshot. Presence only: whether the
        # item shows what `before` says is the case critic's judgment (AR-29). `snapshot_items` None (no snapshot, or a caller that has
        # none to give) leaves the form refused with the words it has always had.
        item = REFERENCE_REF_RE.match(before_ref).group(1)
        if item not in snapshot_items:
            errors.append(f"`before_ref` '{before_ref}' is not an item of work/reference-snapshot.yaml (its items: "
                          f"{', '.join(sorted(map(str, snapshot_items))) or 'none'}); cite one of them, or the forms {_BEFORE_REF_FORMS}")
    elif not (before_ref == CLAIM_ABSENT or re.match(r"^diff:-\S", before_ref)
              or BASE_REF_RE.match(before_ref) or re.match(r"^screenshot:\S", before_ref)):
        errors.append(f"`before_ref` '{before_ref}' is none of {_BEFORE_REF_FORMS}")
    if not now or not now_ref:
        errors.append("`now` and `now_ref` are both required (what the behaviour is now, and the diff line or current-code place it was read from)")
    if differs not in CLAIM_DIFFERS:
        errors.append(f"`differs` '{differs}' is none of {' | '.join(CLAIM_DIFFERS)}")
    if differs == "yes" and not qid:
        errors.append("`differs: yes` with no `question`: a behaviour that changed is asked about, never assumed")
    elif not qid:
        errors.append("no `question`: an implementation-only requirement never reaches the plan without "
                      "its question to the person")
    elif isinstance(questions, dict):
        question = questions.get(qid)
        if not isinstance(question, dict):
            errors.append(f"question {qid} is not in `open_questions` of requirements-readiness.json")
        elif before_now_errors(question) or "before" not in question:
            errors.append(f"question {qid} does not show before/now (`before` and `now`, each with value and where)")
        else:
            errors.extend(_claim_link_errors(row, qid, question, questions, link_index))
    return errors


def claim_link_index(questions) -> dict:
    """{R id: [question ids that name it]} over a question map, in the map's order: the reverse index `_claim_link_errors` asks. A caller
    that checks MANY claim rows against one map builds it once and hands it to `claim_row_errors` (t-1781: one scan per row made the
    projector quadratic - 10 000 claims took 750 s); a single call builds it itself. {} for a map that is not a dict."""
    index: dict = {}
    for other_id, other in (questions.items() if isinstance(questions, dict) else ()):
        if isinstance(other, dict):
            for named_id in named_r_ids(other):
                index.setdefault(named_id, []).append(other_id)
    return index


def _claim_link_errors(row: dict, qid: str, question: dict, questions: dict, index=None) -> list:
    """F13 (D1-B B9): the claim row points at a question that is about OTHER requirements while another question is about this one. Only
    when the question NAMES R ids (a question that names none gets nothing: no reading of meaning, FR-12). A question map that is not a
    dict never gets here (the caller checks). `index` is `claim_link_index(questions)` when the caller has it already."""
    rid = str(row.get("r") or "").strip()
    named = named_r_ids(question)
    if not rid or not named or rid in named:
        return []
    index = claim_link_index(questions) if index is None else index
    others = [str(other_id) for other_id in index.get(rid, ()) if other_id != qid]
    if not others:
        return []
    ids = ", ".join(sorted(named, key=lambda r: int(r[2:])))
    return [f"the claim of {rid} points to {qid}, which is about {ids}; {others[0]} is the question about {rid} - fix: point the claim to "
            f"{others[0]}, or name {rid} in {qid}"]


# --- the Then: where its expected value comes from --------------------------------------------

# O4 (the designer has no Bash, so it cannot run `question_register.py --raise`): it writes the
# question as ONE front-matter line `raise_questions` and the Then as `unknown` with the ref `raise`;
# the S4 exit (`critic_rollcall.py --apply-fixes`) raises it, writes the new id into the case and drops
# the line. The validator accepts `raise` only paired with that entry, and the gate A rehearsal refuses
# a `raise` that is still there: no `unknown` reaches gate A without its question.
RAISE_REF = "raise"


def claim_question(spec, who: str = "the question file") -> tuple:
    """(question without its id | None, problems): a before/now question as its author writes it.

    The author's content is `question`, `source_says`, `severity`, `owner_role`, `before` and `now`
    (each of the last two `{value, where}`); the two readings are the code's (`claim_readings`).
    `who` names the carrier in the sentences (the `--question-file`, or `raise_questions`). Shared by
    `question_register.raise_question` and the validator, so the shape the designer is told at write
    time is the one the S4 exit will accept."""
    spec = spec if isinstance(spec, dict) else {}
    question = {"question": spec.get("question"), "source_says": spec.get("source_says"),
                "severity": spec.get("severity"), "owner_role": spec.get("owner_role"),
                "before": spec.get("before"), "now": spec.get("now")}
    problems = [f"{who} needs `{side}` as an object {{value, where}}"
                for side in ("before", "now") if not isinstance(question[side], dict)]
    if problems:
        return None, problems
    question["readings"] = claim_readings(question["before"].get("value"), question["now"].get("value"))
    for key in ("severity", "owner_role"):
        if not str(question.get(key) or "").strip():
            problems.append(f"{who} needs `{key}`")
    problems.extend(question_errors(dict(question, id="Q0")))
    return (None if problems else question), problems


GROUNDING_ROW_SEVERITY = "major"        # not blocking by itself (question_register.NOT_BLOCKING): the answer shapes the plan, it does not gate S3
GROUNDING_ROW_READINGS = (
    ("Needed in this story: the change has to do it",
     "The plan covers it as a requirement of this story, and the change is held to it."),
    ("Not needed in this story",
     "It is left out of this story's checks, and the report names it as not asked of this change."))


def grounding_row_question(prose, quote, where) -> dict:
    """A question the strategist wrote on a grounding row or a requirement line (`question` of `work/grounding.yaml`) as a register question
    without an id (G2-2): `question` is the strategist's prose; `source_says` the one quote it stands on (`quote`, `where`); the two
    `readings` are the code's (needed / not needed in this story, both `from: claim` - no reading of its own voice), no `before` / `now`
    (a row's question has no behaviour pair to show); `severity` and `owner_role` are fixed. Passes `question_errors` when `prose`,
    `quote` and `where` are not blank; a blank one comes back as it is, and `question_errors` names it."""
    return {"question": str(prose or "").strip(),
            "source_says": [{"quote": str(quote or "").strip(), "where": str(where or "").strip()}],
            "readings": [{"reading": reading, "from": CLAIM_ORIGIN, "if_chosen": chosen} for reading, chosen in GROUNDING_ROW_READINGS],
            "severity": GROUNDING_ROW_SEVERITY, "owner_role": "qa-test-strategist"}


def then_oracle_errors(name: str, raw, raw_question_thens, thens, impl_only=None, known_r=None,
                       questions=None, raw_raise_questions=None, snapshot_items=None, parity=None, basis="") -> list:
    """Why a case's `then_oracles` is not acceptable, one line per problem; [] when it is.

    C7 (`precedent` with `reference:<item>`): `snapshot_items` the ids of `work/reference-snapshot.yaml` (None - there is no snapshot),
    `parity` the register's `parity_ids` (None - no register), `basis` the case's basis (`requirement:R-n` names the requirement the
    parity rests on). A caller that passes none of them gets the refusal with its door: the error direction is toward refusing.

    `raw` the front-matter value (None - the key is absent); `raw_question_thens` the case's
    `question_thens` value; `thens` the numbers under `## Then`; `impl_only` the implementation-only
    R ids NOT yet confirmed (None - no register); `known_r` the register's ids (None - no register);
    `questions` {id: question dict + status} of the readiness file (None - the file is missing);
    `raw_raise_questions` the case's `raise_questions` value (None - the key is absent): the ref
    `raise` of an `unknown` Then is legal only with an entry for that Then there, and an entry for a
    Then whose oracle is not `unknown`/`raise` is refused.
    Code checks presence, shape and refs only: whether R-13's text supports `403` is the case
    critic's judgment (FR-12/FR-47) - "Then 403 with {ac, R-13} where R-13 has no 403" passes here."""
    numbers = sorted(n for n in (thens or []) if isinstance(n, int))
    if raw is None:
        if not numbers:
            return []
        return [f"{name}: FORM - `then_oracles` is missing (a case with updated >= {ORACLE_CUTOFF}): say where "
                f"the expected value of Then {', '.join(map(str, numbers))} comes from, as ONE line of JSON: "
                'then_oracles: [{"then": 1, "source": "requirement", "ref": "R-1"}] with source one of '
                f"{' | '.join(THEN_ORACLE_WORDS)} (code is never a source; `unknown` needs a question that shows before/now)"]
    entries, problem = parse_json_list(raw)
    if entries is None:
        return [f"{name}: FORM - `then_oracles` must be ONE line of JSON, a list of "
                '{"then", "source", "ref"} objects (an empty value, or a nested block the flat front '
                f"matter loses, reads as nothing): {problem}"]
    errors = []
    asked, _ = parse_json_list(raw_question_thens)
    asked_for: dict = {}
    for item in asked or []:
        then = item.get("then")
        if isinstance(then, int) and not isinstance(then, bool):
            asked_for.setdefault(then, set()).add(str(item.get("question") or "").strip())
        # HF4-7 (N7-1): a question being raised is ALWAYS a before/now one, whose readings are the code's fixed pair; its
        # texts are keyed `now` / `before`, never by letter - refused here, at the write, not a round later at the S4 exit
        readings = item.get("readings")
        if str(item.get("question") or "").strip() == RAISE_REF and isinstance(readings, dict):
            stray = [str(key) for key in readings if key not in CLAIM_KEYS]
            if stray:
                errors.append(f"{name}: FORM - question_thens for Then {item.get('then')!r} asks the question being raised "
                              f"(`{RAISE_REF}`), which is always a before/now question: its reading order is fixed by the "
                              f"factory, not by the case, so the texts are keyed `{CLAIM_KEYS[0]}` and `{CLAIM_KEYS[1]}`, "
                              f"not {', '.join('`%s`' % key for key in stray)}. Write the same line with "
                              f'"readings": {{"{CLAIM_KEYS[0]}": "<the Then if the behaviour now is expected>", '
                              f'"{CLAIM_KEYS[1]}": "<the Then if the behaviour before is expected>"}}')
    seen = set()
    raising: set = set()
    for entry in entries:
        then = entry.get("then")
        if not isinstance(then, int) or isinstance(then, bool) or then not in numbers:
            errors.append(f"{name}: FORM - then_oracles names Then {then!r}, which is not an item under `## Then` "
                          f"(this case has {', '.join(map(str, numbers)) or 'none'})")
            continue
        if then in seen:
            errors.append(f"{name}: FORM - then_oracles names Then {then} twice: one Then, one oracle "
                          "(a Then that mixes sources is split into two Thens)")
            continue
        seen.add(then)
        source, ref = str(entry.get("source") or "").strip(), str(entry.get("ref") or "").strip()
        where = f"{name}: FORM - Then {then}"
        kind = source
        if source not in THEN_ORACLE_WORDS:
            # the door `new: <word> -- <why>` (F-3 (b)); `code` has none, in any spelling (P20, FR-58)
            door = open_word_errors(source, THEN_ORACLE_WORDS, "then_oracle", never=THEN_ORACLE_NEVER)
            if door:
                errors.append(f"{where}: source {door[0]} "
                              "(`code` is never an oracle: an expected value read from the implementation can only pass)")
                continue
            # a word of the role's own is checked by the STRICTEST ref rule: a register requirement that is not
            # implementation-only, or a question of the register - the stage critic judges the word itself
            kind = "requirement" if REQ_ID_RE.fullmatch(ref) else "question"
        if kind in REQUIREMENT_ORACLE_WORDS:
            if not REQ_ID_RE.fullmatch(ref):
                errors.append(f"{where}: `{source}` needs a register requirement as ref (R-n), not '{ref}'")
            elif known_r is not None and ref not in known_r:
                errors.append(f"{where}: {ref} is not in the register of the task")
            elif impl_only is not None and ref in impl_only:
                errors.append(f"{where}: {ref} is implementation-only (derived from the diff, from `current-code:` or from "
                              "somebody else's `test:`, no ticket source and no document speaks to it): a statement read from "
                              "the code is never a requirement. Use `unknown` with "
                              "the question that shows before/now, or `person` once it is answered")
        elif source == "precedent":
            if not PRECEDENT_REF_RE.match(ref):
                errors.append(f"{where}: `precedent` needs the BASE revision's behaviour as ref "
                              f"(base:<rev>:<path>:<line>) or an item of the reference snapshot (reference:<item>), "
                              f"not '{ref}'; any other precedent is a question with the precedent shown as before")
            elif REFERENCE_REF_RE.match(ref):
                # C7: the item is in the story's snapshot AND the case basis is `requirement:R-n` of a `parity: yes` row. Presence and
                # cross-reference only; whether the item shows what the Then says is the case critic's judgment (AR-29).
                if snapshot_items is None:
                    errors.append(f"{where}: `precedent` cites {ref}, but the story has no reference snapshot (the S1 reference walk writes "
                                  "work/reference-snapshot.yaml with `reference_snapshot.py put`); cite `base:<rev>:<path>:<line>` or "
                                  "raise a question until it exists")
                else:
                    if REFERENCE_REF_RE.match(ref).group(1) not in snapshot_items:
                        errors.append(f"{where}: {ref} is not an item of work/reference-snapshot.yaml (its items: "
                                      f"{', '.join(sorted(map(str, snapshot_items))) or 'none'}); cite one of them or raise a question")
                    parity_r = requirement_id(basis)
                    if not parity_r:
                        errors.append(f"{where}: {ref} rests on a parity requirement: the case `basis` must be `requirement:R-n` of the "
                                      f"register row whose `parity` is `{PARITY_YES}` (the basis is '{str(basis or '').strip()[:60]}')")
                    elif parity is None:
                        errors.append(f"{where}: {ref} needs {parity_r} to be a parity requirement, but the register has no `parity` column "
                                      f"or could not be read (the requirements tester adds the column and sets `{PARITY_YES}`; without it "
                                      "the Then is a question)")
                    elif parity_r not in parity:
                        errors.append(f"{where}: {ref} needs {parity_r} to be a parity requirement, but its register row does not "
                                      f"say `parity: {PARITY_YES}` (the requirements tester sets the `parity` column; without it the Then "
                                      "is a question)")
        else:  # person | unknown: both name a question of the register
            if source == "unknown" and ref == RAISE_REF:
                raising.add(then)  # the question does not exist yet: its entry in `raise_questions` is checked below
            elif not ref:
                errors.append(f"{where}: `{source}` needs the question id as ref")
            elif questions is None:
                errors.append(f"{where}: `{source}` names {ref}, but requirements-readiness.json is missing or "
                              "unreadable: an `unknown` never travels without the door a person can answer through")
            elif not isinstance(questions.get(ref), dict):
                errors.append(f"{where}: {ref} is not in `open_questions` of requirements-readiness.json "
                              "(raise the question first: the id is the register's own, `Q1` is not `Q-1`)")
            elif source == "person" and questions[ref].get("status") != "answered":
                errors.append(f"{where}: `person` names {ref}, which is not answered yet: write `unknown` "
                              "until the person's answer is recorded")
            elif source == "unknown" and (before_now_errors(questions[ref]) or "before" not in questions[ref]):
                errors.append(f"{where}: question {ref} does not show before/now (`before` and `now`, each with "
                              "value and where): without them the person cannot tell what is being asked")
        have = asked_for.get(then, set())
        if source == "unknown":
            if ref not in have:
                errors.append(f"{where}: `unknown` needs an entry for this Then in `question_thens` for {ref} "
                              "(what the Then says under each reading); without it the answer changes nothing")
        elif have:
            errors.append(f"{where}: then_oracles says `{source}:{ref}` while `question_thens` gives readings "
                          f"for {', '.join(sorted(h for h in have if h)) or 'a question'}: settled or open, never both")
    missing = [n for n in numbers if n not in seen]
    if missing:
        errors.append(f"{name}: FORM - then_oracles has no entry for Then {', '.join(map(str, missing))}: one entry "
                      "per numbered Then")
    errors.extend(raise_question_errors(name, raw_raise_questions, raising, numbers))
    return errors


def raise_question_errors(name: str, raw, raising: set, numbers: list) -> list:
    """The `raise_questions` side of O4, one line per problem. `raising` the Thens whose oracle is
    `unknown` with the ref `raise`; `raw` the case's `raise_questions` value (None - the key is absent).
    A `raise` with no entry, and an entry for a Then that is not `raise`d, are both refused: the pair is
    legal only as a pair, so an `unknown` never reaches gate A without the question that asks it."""
    if raw is None and not raising:
        return []
    entries, problem = parse_json_list(raw)
    form = ('raise_questions: [{"then": 4, "question": "<what the person is asked>", "source_says": '
            '[{"quote": "...", "where": "..."}], "severity": "major", "owner_role": "po_ba", '
            '"before": {"value": "...", "where": "..."}, "now": {"value": "...", "where": "..."}}]')
    if raw is not None and entries is None:
        return [f"{name}: FORM - `raise_questions` must be ONE line of JSON, a list of question objects "
                f"(an empty value, or a nested block the flat front matter loses, reads as nothing): {problem}. "
                f"The form: {form}"]
    errors, entered = [], set()
    for entry in entries or []:
        then = entry.get("then")
        if not isinstance(then, int) or isinstance(then, bool) or then not in numbers:
            errors.append(f"{name}: FORM - raise_questions names Then {then!r}, which is not an item under `## Then`")
            continue
        if then in entered:
            errors.append(f"{name}: FORM - raise_questions names Then {then} twice: one Then, one question")
            continue
        entered.add(then)
        if then not in raising:
            errors.append(f"{name}: FORM - raise_questions has an entry for Then {then}, whose oracle in then_oracles is "
                          f"not {{\"source\": \"unknown\", \"ref\": \"{RAISE_REF}\"}}: a question is raised only for a Then "
                          "that waits for it (remove the entry, or write the Then as `unknown` with the ref `raise`)")
            continue
        errors.extend(f"{name}: FORM - Then {then}: {problem}"
                      for problem in claim_question(entry, "raise_questions")[1])
    for then in sorted(raising - entered):
        errors.append(f"{name}: FORM - Then {then} is `unknown` with the ref `{RAISE_REF}` but raise_questions has no "
                      f"entry for it: write one (the question the person is asked, with what the behaviour is before "
                      f"the change and now). The form: {form}")
    return errors


BEFORE_VALUE_NEEDED = ("the person's value for before is needed: they chose the behaviour before the change, "
                       "and the question shows it as unknown - ask them what it was")


def before_value_needed(question) -> bool:
    """O2/F3: is this `answered` before/now question one whose answer does NOT settle anything yet? True for
    reading `b` ("the behaviour before the change is the expected one") while the question's own `before` is
    empty or the designer's `unknown` placeholder - the person chose a value nobody has written down, so the
    expected value is still missing (FR-41). The ONE test the resolver (`resolve_then_oracle`), the report's
    "Left with you" and the gate's still-open list share: they cannot disagree about whether Q7 is settled.
    A question with no `before` (every question written before t-227) is never one."""
    if not isinstance(question, dict) or question.get("status") != "answered":
        return False
    reading = str(question.get("reading") or "").strip()
    if not reading or not isinstance(question.get("before"), dict):
        return False
    if question.get("before_from_thens") is True:
        # RN1-11: `question_register.record` saw every case Then of this question carry a real text for this letter, so
        # the expected value is written - in the cases, not in `before` (the one writer of the stamp, AR-14)
        return False
    value = str(question["before"].get("value") or "").strip()
    if value and value.lower() != CLAIM_UNKNOWN:
        return False
    # the reading "the behaviour before is expected" is asked of the question (HF4-7, N7-2); a question that does not
    # say which reading it is cannot show that the person did NOT choose it, so with no before value it needs one
    regression = _claim_letter(question, CLAIM_KEYS[1])
    return regression is None or reading == regression


def resolve_then_oracle(entry, question=None, question_then=None) -> dict:
    """THE resolver of one Then's oracle AT READ TIME (C6/FR-16): the readers (traceability,
    ledger, report, the code critic's `invented_expectation`) call this and nothing else.

    `entry` one `then_oracles` item; `question` the register row of `entry.ref` as
    `question_register.load` returns it (`status`, `reading`, `changed_since_answer`), None when
    there is none; `question_then` the case's `question_thens` item for this Then and question.
    An `unknown` Then whose question is `answered` by a reading letter reads as `person`, its expected
    value the matching reading text of `question_then` (an empty text means the answer asserts
    nothing here); the approved case is never edited after gate A. On a before/now question reading
    `b` (a regression) is the question's `before` value, and stays `unknown` while that is unknown (O2).
    Everything else stays `unknown`
    with the reason in `why` - own wording (no letter), `not_needed`, a row changed since the answer, a
    letter `question_thens` has no text for - because the error direction is toward "unconfirmed",
    never toward inventing a person's word (FR-41).

    Returns {then, source, ref, state: settled | open | invalid, expected, reading, why}."""
    entry = entry if isinstance(entry, dict) else {}
    source = str(entry.get("source") or "").strip()
    out = {"then": entry.get("then"), "source": source, "ref": str(entry.get("ref") or "").strip(),
           "state": "settled", "expected": None, "reading": "", "why": ""}
    if source not in THEN_ORACLE_WORDS:
        out.update(state="invalid", why=f"'{source}' is not an oracle word")
        return out
    if source != "unknown":
        return out
    out["state"] = "open"
    if not isinstance(question, dict):
        out["why"] = "the question is not in the register"
        return out
    status = str(question.get("status") or "open")
    if status != "answered":
        out["why"] = f"the question is {status}"
        return out
    if question.get("changed_since_answer") is True:
        out["why"] = "the question changed after it was answered: the answer was given to another text"
        return out
    letter = str(question.get("reading") or "").strip()
    if not letter:
        out["why"] = "answered in the person's own wording: nothing is applied"
        return out
    before = question.get("before")
    if before_value_needed(question):
        out["why"] = BEFORE_VALUE_NEEDED
        return out
    real_before = isinstance(before, dict) and str(before.get("value") or "").strip().lower() not in ("", CLAIM_UNKNOWN)
    if isinstance(before, dict) and letter == _claim_letter(question, CLAIM_KEYS[1]) \
            and (real_before or question.get("before_from_thens") is not True):
        # (RN1-11: with no real before value and the record's `before_from_thens` stamp the case's own text answers, below)
        # O2: on a before/now question the reading that means "the behaviour BEFORE the change is the expected
        # one" (asked of the question, HF4-7; a question that does not say has none and never gets here) makes the
        # person's value that `before`.
        out.update(source="person", state="settled", expected=str(before.get("value") or "").strip(), reading=letter)
        return out
    text, why = question_then_text(question, question_then, letter)
    if text is None:
        out["why"] = (f"question_thens has no text for reading {letter}: {why}" if why else
                      f"question_thens has no text for reading {letter}")
        return out
    out.update(source="person", state="settled", expected=text, reading=letter)
    return out


# --- bugs: a red test is a draft until someone reproduces it ----------------------------
# On 15045 two of four bugs came from red tests nobody triaged (no row in triage.json) and no
# critic had read (the cases sat in the "Unreviewed for gate A" list): one was the test's own
# selector counting the legend chip, the other the contradiction above. A person could not
# reproduce either by hand. A bug draft therefore carries the triage row it rests on and manual
# steps a person can follow, and stays `unconfirmed` until a person or a second independent
# run on another stand confirms it; the report and the gate show the two groups apart.
#
# HF8-16 (run 12586): the analyst reproduced a red three times and the report still said "nobody has reproduced
# it". `reproduced_by_factory` is the step between: the factory's own later run (or the analyst's own script) saw it
# fail again, a person has not confirmed it. The CODE derives the word from a typed receipt (`reproduction` on the
# draft, read only by `bug_records.confirmation_of`); a role that writes the word without a receipt gets
# `unconfirmed`. `handoffs/vocabulary.yaml` mirrors the tuple (a test holds them equal).
BUG_CONFIRMATIONS = ("unconfirmed", "reproduced_by_factory", "confirmed_by_person", "confirmed_by_rerun")
# The kinds of a `reproduction` entry: a rerun of the red test on fresh data (a later attempt of the run report), or
# the analyst's own script (a receipt file under evidence/), or a walk of the analyst on the stand (t-1991 U2: the record
# `place_answers.py write` keeps, judged by `bug_records._walk_receipt_problem`). Whether the data was fresh is the role's word (FR-47).
BUG_REPRODUCTION_KINDS = ("fresh_data_rerun", "own_script", "walk")
# Why a filed bug is not in the tracker (HF8-21, `bug_records.filing_of`): the code's own derivation from the config, the run's
# record, the person's words at gate B and the books of `external_writes.py` - never a role's claim. The WORDS a person reads
# are data (`handoffs/vocabulary.yaml` `bug_not_sent_reasons`, a test holds the keys equal to this tuple).
BUG_NOT_SENT_REASONS = ("project_choice", "gate_b_word", "no_access", "run_closed")
BUG_DRAFT_REQUIRED = ("title", "impact", "violates", "case", "triage_ref", "manual_steps")
# The red test travels with the bug (P28, spec t-1765 X7-5): a draft and a bug carry EITHER `red_test` (`{path, command}` - the
# failing test that shows the defect and re-checks the fix) OR `red_test_none` (why there is none: a one-off or manual check).
# One of the two, never neither: the empty outcome is stated (AR-23). Both forms of a draft use it.
BUG_DRAFT_RED_TEST = ("red_test", "red_test_none")
# Asked of a draft or a bug created on or after this day (ISO date); an older one carries none and is not re-litigated.
BUG_RED_TEST_CUTOFF = "2026-11-04"
# One bug, many manifestations (spec t-2187 N1): a draft may carry the shared cause (`mechanism`) and every way it shows
# (`manifestations[]`). The closed words are data beside the contract (AR-1): how far the analyst got on the cause, and the kinds of
# evidence a `mechanism.basis` entry stands on - a line of the application code, a run the recorder captured, or the person's own
# words at gate B (F-6 (a), the "merge" door). Read only by `bug_records.mechanism_problems` / `manifestation_problems`.
MECHANISM_STATUSES = ("confirmed", "unverified", "unknown")
MECHANISM_BASIS_KINDS = ("code_line", "run", "person")
# Asked of a triage draft created on or after this day (ISO date) to carry `mechanism` (spec t-2187 3.2, world 3: the charters and the
# phase text name the field since this day, FR-38, FR-5); None = nobody is asked. Read only by `mechanism_owed`.
BUG_MECHANISM_CUTOFF = "2026-11-10"


def mechanism_owed(record, fallback_day: str = "") -> bool:
    """Is `mechanism` asked of this triage draft? The one reader of `BUG_MECHANISM_CUTOFF` (AR-13), the same date rule as
    `red_test_owed`: the record's `created` day, else `fallback_day` (the draft file's own day); no cutoff or no readable day is
    not asked. Whether the draft already carries `mechanism`, and whether it is a code-reading draft, is the caller's to say."""
    cutoff = BUG_MECHANISM_CUTOFF        # read at call time: a test may set it
    data = record if isinstance(record, dict) else {}
    day = G.date_prefix(data.get("created")) or G.date_prefix(fallback_day)
    return bool(cutoff) and bool(day) and day >= str(cutoff)


def red_test_owed(record, fallback_day: str = "") -> bool:
    """Is the red test asked of this draft or bug? The one reader of `BUG_RED_TEST_CUTOFF` (AR-13): the record's `created` day,
    else `fallback_day` (a caller's own day, e.g. the draft file's); a record with no readable day is not asked (the rule does
    not apply, as `grammar.after_cutoff`)."""
    data = record if isinstance(record, dict) else {}
    day = G.date_prefix(data.get("created")) or G.date_prefix(fallback_day)
    return bool(day) and day >= BUG_RED_TEST_CUTOFF


def red_test_problems(record, flat: bool = False) -> list:
    """Why a bug draft or a bug record does not carry its red test, one line per problem; [] when it does. Shape only: that
    `red_test` is `{path, command}` (both non-empty) on a draft - or, with `flat=True` (a bug file's flat frontmatter, which
    holds no mapping), any non-empty text `<path> -- <command>` - and that `red_test_none` is a non-empty reason. Whether the
    test is the right one or the reason holds is the reporter's / the reading tier's judgment (AR-29). Both set is a conflict
    and is refused: the bug either has a red test or says why not."""
    data = record if isinstance(record, dict) else {}
    test, none = data.get("red_test"), data.get("red_test_none")
    test_given = bool(test) and (bool(str(test).strip()) if not isinstance(test, dict) else True)
    none_given = bool(str(none or "").strip().strip("-"))
    names = " or ".join(f"`{name}`" for name in BUG_DRAFT_RED_TEST)
    form = "`red_test: <path of the failing test> -- <command that runs it>`" if flat         else "`red_test: {path: <the failing test>, command: <how to run it>}`"
    if test_given and none_given:
        return [f"both `red_test` and `red_test_none` are set - write one: {names}"]
    if test_given:
        if isinstance(test, dict):
            lacking = [key for key in ("path", "command") if not str(test.get(key) or "").strip()]
            if lacking:
                return ["`red_test` lacks " + ", ".join(f"`{key}`" for key in lacking) + f" - write {form}"]
        elif not flat:
            return [f"`red_test` of a draft is a mapping, not text - write {form}"]
        return []
    if none_given:
        return []
    return [f"no red test: write {names}. {form} - the failing test that shows the defect and re-checks "
            "the fix; `red_test_none: <why>` - e.g. a manual check that no test can hold (the test travels with the bug, P28)"]


# The second form of a draft (t-1676, RN1-12): `evidence: "code-reading"` - a bug candidate found by comparing an oracle (a settled
# answer or an unambiguous register requirement) with an S1 code fact, where no factory test spoke; a walk of the analyst may be its receipt. It has no triage row, so it has no
# `case` / `triage_ref`; `bug_records.code_reading_problems` is its one checker. A closed list, so it lives beside the contract (FR-13).
BUG_DRAFT_CODE_READING_REQUIRED = ("title", "impact", "violates", "oracle", "fact", "check_state", "manual_steps")
CODE_READING_CHECK_STATES = ("not_executed", "unverifiable")
# The register column `code_says` (RN1-17 item 0): what the S1 facts say about a requirement whose expected result is stated
# without alternatives. `meets: <fact id>` | `contradicts: <fact id>` | `unknown` (the empty outcome, AR-23).
CODE_SAYS_WORDS = ("meets", "contradicts", "unknown")
# A branch of these kinds makes the expected result itself open (the person picks the branch); `partition` and `refusal` do not.
AMBIGUOUS_BRANCH_KINDS = ("variant", "qualifier")


def bug_confirmation(record) -> str:
    """`confirmation` of a bug draft or bug record; a record written before 0.7.16 carries
    none and reads as confirmed_by_person — nobody re-litigates a bug the person already filed.

    A word that is there and is not one of the closed list reads `unconfirmed` (HF8-16, FR-41): a typo must not
    lift a bug to the step a person stood behind; the error goes down. An absent or empty field is the legacy
    case above. This is the WORD as written; whether `reproduced_by_factory` holds is `bug_records.confirmation_of`."""
    value = str((record or {}).get("confirmation") or "").strip() if isinstance(record, dict) else ""
    if not value:
        return "confirmed_by_person"
    return value if value in BUG_CONFIRMATIONS else "unconfirmed"


# --- retries: a resumed dispatch names why its parent stopped -----------------------------
# On TP1-15045 the Factory tab read "retry dispatches: 10 - parents (10)": 10 of 53
# dispatches were second attempts and not one of them said why, although the parents'
# checkpoint reasons held the answer (turn budget, a question awaiting the person, a stand
# that was not installed, a factory script that broke). A count of repeats without a cause
# is not a metric; the cause is the finding. The list is closed so that a person reads the
# same word on every story; `host_error` carries the host's code after a colon.
RETRY_REASONS = ("no_digest_at_exit", "subagent_silent", "host_error", "turn_budget",
                 "compaction", "unaccepted_result", "awaiting_person", "environment",
                 "factory_defect", "checkpoint", "person_word", "unknown")
# The reasons that make a resumed dispatch a CONTINUATION of its parent's work, not a repair of it (F2 t-1753): the parent
# stopped for a reason of the run (a window, a budget, a silent or crashed host), not because its result was wrong. A data
# row (AR-1): the retro's repair-round count (`retro_numbers.dispatch_rounds`) reads it; the dashboard's C06 "rework" is
# the cost of every dispatch linked `parent_retry`, a wider figure (references/metrics/catalogue.json names the relation).
CONTINUATION_RETRY_REASONS = ("checkpoint", "compaction", "turn_budget", "subagent_silent", "no_digest_at_exit",
                              "host_error")
_HOST_CODE_RE = re.compile(r"\b(E[A-Z]{3,})\b|exit code (\d+)|host error[:\s]+([A-Za-z0-9_]+)")
_FACTORY_SCRIPT_RE = re.compile(r"\b\w+\.py\b")


def retry_reason_valid(value) -> bool:
    """True for a closed-list value, or `host_error:<code>` with a non-empty code."""
    value = str(value or "")
    if value.startswith("host_error:"):
        return bool(value.split(":", 1)[1].strip())
    return value in RETRY_REASONS and value != "host_error"


def is_continuation_reason(value) -> bool:
    """True when a retry reason (`host_error:<code>` included) names a continuation, not a repair (F2 t-1753)."""
    return str(value or "").split(":", 1)[0] in CONTINUATION_RETRY_REASONS


def retry_reason_for(parent: dict, words: str = "") -> str:
    """Classify why a dispatch is being resumed, from its parent's recorded status/reason.

    A dispatch written before 0.7.15 carries no `retry_reason`; readers classify its parent
    on the fly with this same function, so the Factory tab reads one vocabulary across old
    and new stories. First match wins; the wording is the 15045 checkpoints' own."""
    if str(words or "").strip():
        return "person_word"
    parent = parent if isinstance(parent, dict) else {}
    status = str(parent.get("status") or "").lower()
    reason = str(parent.get("reason") or "").lower()
    def has(*needles):
        return any(n in reason for n in needles)
    if has("awaiting the person", "awaiting human", "blocking question"):
        return "awaiting_person"
    if status == "never_started" or has("never launched", "never reached an agent", "silent",
                                        "stopped without", "no agent"):
        return "subagent_silent"
    if "digest" in reason and has("no ", "missing", "without"):
        return "no_digest_at_exit"
    if "compact" in reason:
        return "compaction"
    if (has("turn budget", "turn-budget", "window budget")
            or ("turns" in reason and has("exhausted", "ran out", "guard fired", "cap"))):
        return "turn_budget"
    m = _HOST_CODE_RE.search(str(parent.get("reason") or ""))
    if m:
        return "host_error:" + next(g for g in m.groups() if g)
    if has("toolchain", "credentials", "stand", "environment", "not installed", ".env"):
        return "environment"
    if _FACTORY_SCRIPT_RE.search(reason) and has("cannot", "broke", "breaks", "fails", "error"):
        return "factory_defect"
    if status == "returned_unaccepted" or has("unaccepted", "returned"):
        return "unaccepted_result"
    if status in ("incomplete", "paused", "blocked") and has("applied", "verified", "executed",
                                                             "written", "green", "done", "carried"):
        return "checkpoint"
    return "unknown"


def trace_row_errors(row) -> list:
    """Shape errors of one traceability row; [] when it is well-formed."""
    if not isinstance(row, dict):
        return ["row is not an object"]
    errors = []
    for field in ("requirement", "case", "result"):
        if not str(row.get(field) or "").strip() and not (field == "case" and row.get("result") == "not planned"):
            errors.append(f"trace.{field} is empty")
    if row.get("result") not in TRACE_RESULTS:
        errors.append(f"trace.result must be one of {', '.join(TRACE_RESULTS)}")
    if row.get("result") == "bug" and not str(row.get("bug") or "").strip():
        errors.append("trace.bug names the bug record when result is bug")
    if row.get("level") and row.get("level") not in TRACE_LEVELS:
        errors.append(f"trace.level must be one of {', '.join(TRACE_LEVELS)}")
    if row.get("shape") and row.get("shape") not in TRACE_SHAPES:
        errors.append(f"trace.shape must be one of {', '.join(TRACE_SHAPES)}")
    if "tests" in row and not isinstance(row.get("tests"), list):
        errors.append("trace.tests must be a list of {instance_id, file}")
    return errors


def case_title(path: Path) -> str:
    """The case's human title from its frontmatter; '' when absent."""
    m = CASE_TITLE_RE.search(read_text(path)[:2000])
    return m.group(1).strip().strip('"') if m else ""


def plan_levels(artifacts: Path) -> dict:
    """{TS-n: level} from the plan's own `level` column (the strategist's call at S3)."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    plan = artifact(art, "test-plan.md")
    return {r.get("ts"): str(r.get("level") or "").strip() for r in parse_plan(plan) if r.get("ts")}


def case_levels(artifacts: Path) -> dict:
    """{case_key: level} — the case's `Plan row:` / frontmatter `plan_row` -> the plan's
    `level` column. The level a person approved at gate A, read from where it was recorded;
    a case whose row has no level is absent from the map, never guessed."""
    levels = plan_levels(artifacts)
    out = {}
    for key, entry in case_index(artifacts).items():
        row = str(entry.get("plan_row") or "")
        if not row:
            row = case_plan_row(Path(entry["path"]))
        if levels.get(row):
            out[key] = levels[row]
    return out


def handed_tests(manifest: dict, thens: bool = False, reasons=(HANDED_TO_PERSON,)) -> list:
    """[{case, profile, what, detail}] — what this story handed to the person, from the
    manifest's own `unresolved[]` rows. The ledger, the delivery summary, the gate-B brief and
    the report all read this one list, so the person is told the same thing four times.

    `thens=True` (GW1-14) appends one row per Then left with its owner (`then_remainders`): the same keys plus `then`,
    `owner` and `part`, `profile` empty and `what` the detail. The default stays the whole-case list byte for byte:
    every caller that asks "was the WHOLE case not run here" (the witness, the window, the proof level, the run
    mapping, the gate-B brief, the summary) keeps meaning exactly that.

    `reasons` (HF2-3) widens only the `thens=True` rows, to the remainders of those reasons (`then_remainders`); the
    whole-case list is the person's hand-off alone whatever it says (a whole-case `unresolved[]` row never carries
    `blocked_by_check`). A row of another reason than `handed_to_person` adds `reason`, `blocking_check` and
    `instance_id`; the rows of the default call are byte for byte what they were."""
    out = []
    for entry in manifest_unresolved(manifest):
        if str(entry.get("reason") or "") != HANDED_TO_PERSON:
            continue
        detail = " ".join(str(entry.get("detail") or "").split())
        profile, _, what = detail.partition(": ")
        case = str(entry.get("case") or "")
        # A row may be keyed `<area>/TC-NNN` when two areas share a number (FB-2428-1) while
        # the manifest's own test links still spell the bare id. Both travel, so a reader
        # matching either spelling finds it.
        try:
            bare = split_case_key(case)[1] or case
        except Exception:
            bare = case
        out.append({"case": case, "case_id": bare, "detail": detail,
                    "profile": profile.strip() if what else "",
                    "what": (what or detail).strip()})
    if thens:
        for r in then_remainders(manifest, reasons=reasons):
            row = {"case": r["case"], "case_id": r["case_id"], "then": r["then"], "owner": r["owner"], "part": r["part"],
                   "detail": r["detail"], "profile": "", "what": r["detail"]}
            if r["reason"] != HANDED_TO_PERSON:
                row.update(reason=r["reason"], blocking_check=r.get("blocking_check", ""), instance_id=r.get("instance_id"))
            out.append(row)
    return out
# The RUN's own status (run-report.json `execution_status`) — not a single test's.
EXECUTION_STATUS = ("passed", "failed", "env_blocked", "not_executed", "broken_run", "timeout")
# One TEST's status inside run-report.json `results[]`. Until 0.3.0 nothing defined this, so
# rows reached the dashboard with no status at all and it printed "?" from its own default
# (TP2-2290: nine skipped tests, no names, no statuses, no reasons).
RESULT_STATUS = ("passed", "failed", "error", "skipped", "not_run")
# The statuses that prove the environment answered for that instance: it ran and produced a
# product outcome. `skipped`, `not_run` and `error` are not that proof, so they never
# supersede an environment block.
TERMINAL_RESULT_STATUSES = ("passed", "failed")
# Whose problem a `delivery_ready: no` reason is. `delivery_ready: no` used to be one
# undifferentiated list, so a join failure inside our own reducer read to the person exactly
# like an unproven product behaviour (0.6.0 feedback on TP2-2530, item 3). The
# factory's own defect is never presented to the person as theirs to fix.
DELIVERY_REASON_OWNERS = ("product", "factory", "environment", "review")
# What a ticket named in THIS ticket is to it. Never the parent's other children.
RELATED_KINDS = ("implementation", "blocker", "bug", "mention")
# Where a check sits in the test pyramid, bottom-up. Declared in test-plan.md's `level`
# column, carried to the board through the case -> manifest `plan_row` -> plan chain.
# `component` was added in 0.3.0: a frontend component test and a service test with its
# collaborators stubbed are neither `unit` nor `api`, and TP2-2290 put three of them
# under "API autotests" because the dashboard classified by looking for the substring "ui"
# in the test name instead of reading the level the plan had already recorded.
PLAN_LEVELS = ("unit", "component", "api", "integration", "e2e-ui")
# the one spelling of the assert-stricter word for readers that must name it (the trace table's basis, t-1338 Q1)
TRIAGE_STRICTER_VERDICT = "ASSERT_STRICTER"
# the one spelling of the misread-evidence word for the readers that must name it (the S7 re-judge round, the delivery owner)
TRIAGE_MISREAD_VERDICT = "RUNNER_MISREAD_EVIDENCE"
TRIAGE_VERDICTS = ("APP_BUG", "TEST_BUG", "TEST_BUG:collection", "ENV_ISSUE", "FLAKY",
                   "APP_CHANGED",
                   # The approved case misread the requirement. Only the failure analyst may
                   # reach it, only from a red test handed over with `contradicts_requirement`,
                   # and only against the requirement register - an existing test is never an
                   # oracle. It is not a bug: the case goes back to the designer (`rework`).
                   "CASE_DEFECT",
                   # The assert asks for more than the requirement does (HF2-18, 12586: the same action
                   # WITHOUT this story's change shows the same difference, and the requirement is silent).
                   # Only the failure analyst may reach it, and only on its own control experiment -
                   # `control.result: effect_without_change` with the experiment's evidence file
                   # (`triage_control_problems`); without it the row is refused and the red stays a product
                   # failure. NOT a bug: no repair, no bug draft, no `rework`, no gate A, no rewritten case -
                   # the delivery lists it in "Left with you" and the person decides (remove the assert, or
                   # refine the requirement).
                   TRIAGE_STRICTER_VERDICT,
                   # The check did not answer: code writes it at S7 (`source: code`) for a manual
                   # check whose own record says what stopped it; the analyst may replace it.
                   "NOT_EXECUTED",
                   # A manual runner's verdict contradicts its own captures (HF8-19, 12586): the failure analyst finds, in the
                   # text the attempt itself captured, a quote that decides the Then the other way. Only the analyst may reach
                   # it and only with `contradiction` (`triage_contradiction_problems`). NOT a bug and NOT a repair: the
                   # runner judges the same captures again (S7 re-judge, no new run); until a new record replaces the
                   # result the delivery stays red (`failed:RUNNER_MISREAD_EVIDENCE`, owner `factory`).
                   TRIAGE_MISREAD_VERDICT,
                   # A manual runner's observation (`<case>#obs<n>`, P26) that the analyst judged not a bug. Valid ONLY on an
                   # observation target, with a `reason` quoting the recorded evidence (`triage_no_defect_problems`); it never
                   # blocks the delivery and is never a product failure.
                   "NO_DEFECT")
# What a code review can conclude about one test. `approved_with_fixes` exists because
# the list used to have two values, so a missing ticket marker -- a comment -- could only
# be said as `rejected`, and `rejected` means a full second round (QA-EXAMPLE).
CRITIC_VERDICTS = ("approved", "approved_with_fixes", "rejected",
                   # The proof was stopped by a tool or the stand, not by the test (D-0013): its
                   # own word, never a rejection (FR-35).
                   "unverified")
FLAKY_MECHANISMS = ("isolation", "race", "timing", "shared_state", "teardown", "environment", "unknown")
# What the analyst's control experiment found (HF2-18): the same action run WITHOUT the change under test.
# The role judges which it is (AR-2); code checks only that the record is well formed.
TRIAGE_CONTROL_RESULTS = ("effect_without_change", "no_effect_without_change", "impossible")


def triage_reason(row) -> str:
    """RD1-19 (AR-13, AR-22): the ONE reader of why a triage row says its verdict - `detail` (the analyst's sentence), then
    `control.observed` (what the control experiment saw), then `reason` (an older spelling), then ''. Whitespace is collapsed;
    a value that is not a string, a `control` that is not an object, or a row that is not an object reads as empty - never
    an error, and never a verdict input (the report quotes it, nothing decides on it)."""
    if not isinstance(row, dict):
        return ""
    control = row.get("control")
    candidates = (row.get("detail"), control.get("observed") if isinstance(control, dict) else None, row.get("reason"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def triage_control_problems(row, task_root=None) -> list:
    """The problems of one triage row's `control` block (HF2-18), `[]` when there are none. THE one reader of the block
    (AR-13): the validator (`validate_artifacts.check_triage_v0`) and the delivery check (`check_delivery.triage_reasons`)
    both ask it. It checks the FORM and never classifies a failure (FR-12, AR-2): no phrase list, no reading of any
    wording - what counts as an extra or a different value, or a requirement that is silent, is the analyst's judgment.

    ERROR DIRECTION (a doubt never lowers the delivery): `ASSERT_STRICTER` turns a red into a line in "Left with you",
    so it passes only with `control.result: effect_without_change`, non-empty `action` / `without` / `observed`, and an
    `evidence` file that exists under `task_root`. A row of any other verdict needs no `control` (an old triage reads as it
    did); when it carries one, the block must still be well formed. `task_root=None` means the CALLER has no task root:
    the existence of `evidence` is then not judged here (and the caller says so) - never a pass of the word itself,
    which still needs every other field. Pure, never raises."""
    if not isinstance(row, dict):
        return []
    stricter = row.get("verdict") == "ASSERT_STRICTER"
    door = ("write the `control` block on this row (`result`, `action`, `without`, `observed`, `evidence`) and re-run "
            "`validate-batch`; or change the verdict: without the effect outside the change it is `APP_BUG` "
            "(or `CASE_DEFECT`)")
    control = row.get("control")
    if control is None:
        return ([f"verdict ASSERT_STRICTER needs its control experiment - the row has no `control` block: {door}"]
                if stricter else [])
    if not isinstance(control, dict):
        return [f"`control` must be an object with the keys `result`, `action`, `without`, `observed`, `evidence`, "
                f"not {type(control).__name__}: {door}"]
    problems = []

    def said(key: str) -> str:
        value = control.get(key)
        return value.strip() if isinstance(value, str) else ""

    result = control.get("result")
    if result not in TRIAGE_CONTROL_RESULTS:
        problems.append(f"`control.result` is {result!r}, expected one of {list(TRIAGE_CONTROL_RESULTS)}")
    if result == "impossible":
        if not said("why"):
            problems.append("`control.result` is impossible but `control.why` is empty: say why the experiment could not "
                            "be run (the same action without the change), so the draft can name it")
    else:
        for key in ("action", "without", "observed", "evidence"):
            if not said(key):
                problems.append(f"`control.{key}` is empty: " + {
                    "action": "name the action that was repeated",
                    "without": "say what was left out of it (the change under test)",
                    "observed": "say what the repeated action showed",
                    "evidence": "name the file under evidence/ that holds the experiment's output"}[key])
        if said("evidence") and task_root is not None:
            try:
                # the experiment's output is a file the RUN wrote under `evidence/` (spec section 2, FR-58): a file that
                # merely exists elsewhere under the root - the triage itself, the plan - is the analyst's word, not a witness
                issue = evidence_ref_issue(task_root, {"path": said("evidence")}, "`control.evidence`", require_hash=False,
                                           under="evidence")
            except (OSError, ValueError) as exc:
                issue = f"`control.evidence` path cannot be read ({exc})"
            if issue:
                problems.append(issue + "; name the experiment's output file relative to the task root, under evidence/ "
                                "(for example `evidence/control-<label>.json`)")
    if "given_gap" in control and not said("given_gap"):
        problems.append("`control.given_gap` is empty: omit it, or say what the test's data lacked of the case's Given")
    if stricter and result in TRIAGE_CONTROL_RESULTS and result != "effect_without_change":
        problems.append(f"verdict ASSERT_STRICTER needs `control.result: effect_without_change`, the row says {result}: "
                        "when the change causes the effect, or the experiment could not be run, the assert is not "
                        "stricter than the requirement - change the verdict (`APP_BUG`, or `CASE_DEFECT`)")
    return problems


def triage_contradiction_problems(row, task_root=None) -> list:
    """The problems of one triage row of the verdict `RUNNER_MISREAD_EVIDENCE` (HF8-19), `[]` when there are none. THE one
    reader of the block (see `_contradiction_problems`); every problem it returns names the door (FR-1, FR-2): the analyst writes
    the row again, or gives another verdict. Pure, never raises."""
    try:
        found = _contradiction_problems(row, task_root)
    except Exception as exc:       # a doubt is a refusal, never a pass and never a crash of the validator or the delivery check
        found = [f"the `contradiction` block could not be checked ({type(exc).__name__})"]
    return [p if "write the row again" in p else p + " (the analyst writes the row again, or gives another verdict)" for p in found]


def _contradiction_problems(row, task_root=None) -> list:
    """The problems of one triage row of the verdict `RUNNER_MISREAD_EVIDENCE` (HF8-19), `[]` when there are none. THE one
    reader of the `contradiction` block (AR-13): the validator (`validate_artifacts.check_triage_v0`), the delivery check
    (`check_delivery.triage_reasons`) and the S7 re-judge reader (`Driver.s7_rejudge_rows`) all ask it. It checks the FORM and
    where the evidence stands, and NEVER whether the quote contradicts the Then (FR-12, FR-47, AR-2): that is the analyst's
    judgment, and the runner judges it again. The block is `{then, runner_said, evidence, quote}`: `then` the number of a Then
    of the case, `runner_said` the runner's own words, `evidence` a TEXT capture file under an attempt of the row's case
    (`work/evidence/manual/<case>/a<n>/...`, task-relative), `quote` words (at most `THEN_QUOTE_MAX`, whitespace squashed) that
    stand in that file.

    ERROR DIRECTION (a doubt never lowers the delivery): the word keeps the delivery red and sends a paid re-judge, so it passes
    only for a MANUAL check (a row with a `case`, no `test`, an `instance_id` that is the case or none, no `reorder`), with every
    field of the block said, the evidence read from a file inside an attempt of that case, and the quote found in it. The only
    mistake allowed is a false refusal, whose door is the analyst writing the row again (or another verdict: the runner stands).
    A row of another verdict is not judged here. `task_root=None` means the CALLER has no task root: the existence of the file
    and the quote are then not judged (the caller says so) - never a pass of the word itself. Pure, never raises."""
    if not isinstance(row, dict) or row.get("verdict") != TRIAGE_MISREAD_VERDICT:
        return []
    door = ("write the row again with `contradiction: {then, runner_said, evidence, quote}`, the evidence being a text file "
            "the runner's own attempt captured and the quote copied from it; or change the verdict (the runner's result stands "
            "as it is, `APP_BUG` for a product failure)")
    word = TRIAGE_MISREAD_VERDICT

    def text(value) -> str:
        return value.strip() if isinstance(value, str) else ""

    problems = []
    case, test, instance = text(row.get("case")), text(row.get("test")), text(row.get("instance_id"))
    if not case:
        problems.append(f"verdict {word} is for a manual check and the row names no `case`")
    if test or (instance and instance != case):
        problems.append(f"verdict {word} is for a manual check, and the row names an automated test "
                        f"({test or instance}): an automated failure is judged by its own run, not re-judged")
    if row.get("reorder") is True:
        problems.append(f"verdict {word} cannot ask for a `reorder`: a manual check has no test to reorder")
    block = row.get("contradiction")
    if block is None:
        return problems + [f"verdict {word} needs its `contradiction` block - the row has none: {door}"]
    if not isinstance(block, dict):
        return problems + [f"`contradiction` must be an object with the keys `then`, `runner_said`, `evidence`, `quote`, "
                           f"not {type(block).__name__}: {door}"]
    then = block.get("then")
    if isinstance(then, bool) or not (isinstance(then, int) or (isinstance(then, str) and then.strip().isascii()
                                                                and then.strip().isdigit())):
        problems.append(f"`contradiction.then` is {then!r}, expected the number of the Then the quote decides")
    for key, what in (("runner_said", "the words the runner gave for its verdict"),
                      ("evidence", "the text file the runner's attempt captured, task-relative"),
                      ("quote", "the words from that file that decide the Then")):
        if not text(block.get(key)):
            problems.append(f"`contradiction.{key}` is empty or not text: say {what}")
    quote, evidence = text(block.get("quote")), text(block.get("evidence"))
    try:
        import manual_evidence as ME
        limit = ME.THEN_QUOTE_MAX
    except Exception:
        ME, limit = None, 300
    if len(" ".join(quote.split())) > limit:
        problems.append(f"`contradiction.quote` is longer than {limit} characters: quote the shortest part that decides")
    if not (evidence and task_root is not None and case):
        return problems
    if "\x00" in evidence or "\x00" in quote:
        return problems + ["`contradiction` carries a NUL character: copy plain text"]
    try:
        import manual_capture as MC
        root = Path(task_root).resolve()
        home = MC.case_root(root, case)
        under = home.relative_to(root).as_posix()
        issue = evidence_ref_issue(root, {"path": evidence}, "`contradiction.evidence`", require_hash=False, under=under)
        if not issue:
            inside = (root / evidence).resolve().relative_to(home).parts
            if len(inside) < 2 or MC.attempt_number(inside[0]) < 0:
                issue = f"`contradiction.evidence` path {evidence} is not inside an attempt of {case} ({under}/a<n>/...)"
            elif inside[1:] == ("record.json",):
                # the attempt's own record holds the runner's prose, not what the attempt captured (F-8)
                issue = f"`contradiction.evidence` path {evidence} is the attempt's own record, not a capture"
            else:
                named = re.sub(r"-r\d+$", "", text(row.get("attempt_id")))
                if named and inside[0] != named:
                    issue = (f"`contradiction.evidence` path {evidence} lies in attempt {inside[0]}, but the row names attempt "
                             f"{text(row.get('attempt_id'))}")
    except (OSError, ValueError) as exc:
        issue = f"`contradiction.evidence` cannot be read ({exc})"
    if issue:
        return problems + [issue + "; name a file the runner's own attempt captured (a path of the attempt's evidence_refs)"]
    try:
        if ME is None:
            raise ValueError("the quote reader is not available")
        if quote and not ME._quote_in(root, {"path": evidence}, quote):
            problems.append(f"`contradiction.quote` is not in {evidence} (a text capture, read as a whole, whitespace squashed): "
                            "copy the words as the file holds them")
        numbers = ME._request_thens(root, case)
        if numbers and isinstance(then, (int, str)) and not isinstance(then, bool) and str(then).strip().isdigit() \
                and int(str(then).strip()) not in numbers:
            problems.append(f"`contradiction.then` {then} is not a Then of {case} (its Thens: {', '.join(map(str, numbers))})")
    except (OSError, ValueError) as exc:
        problems.append(f"`contradiction.quote` could not be checked against {evidence} ({exc})")
    return problems


TRIAGE_DIAGNOSTIC_OUTCOMES = ("held", "red", "not_reached")


def triage_diagnostic_problems(row, task_root=None) -> list:
    """The problems of one triage row's `diagnostic` block (R4, t-1508), `[]` when there are none. THE one reader of the
    block (AR-13): the validator and the delivery check ask it (they are wired to it by R6). The block is
    `{evidence, thens?, observed}`: `evidence` the file `red_sandbox.py --diagnostic` wrote (`evidence/diagnostic-<label>.json`,
    code's file, never the role's), `observed` what the run showed in the analyst's words, `thens` optional rows
    `{then: <n>, outcome: held | red | not_reached}`. It judges the FORM and never reads a wording (FR-12, AR-2).

    ERROR DIRECTION: a block that cannot be shown to rest on a run is a problem, never a pass: the evidence must be a file
    named `diagnostic-*.json` under `evidence/` of the task. A row with no `diagnostic` has none to judge. `task_root=None`
    means the caller has no task root: the existence of the file is then not judged (and the caller says so). Pure, never
    raises."""
    if not isinstance(row, dict) or "diagnostic" not in row or row.get("diagnostic") is None:
        return []
    block = row["diagnostic"]
    door = ("write the block as {\"evidence\": \"evidence/diagnostic-<label>.json\", \"observed\": \"<what the run showed>\", "
            "\"thens\": [{\"then\": <n>, \"outcome\": \"held|red|not_reached\"}]} (`thens` may be left out), the evidence being the file "
            "`red_sandbox.py --diagnostic` printed")
    if not isinstance(block, dict):
        return [f"`diagnostic` must be an object with `evidence`, `observed` and optionally `thens`, not {type(block).__name__}: {door}"]
    problems = []

    def said(key: str) -> str:
        value = block.get(key)
        return value.strip() if isinstance(value, str) else ""

    if not said("observed"):
        problems.append("`diagnostic.observed` is empty: say what the diagnostic run showed")
    evidence = said("evidence")
    if not evidence:
        problems.append("`diagnostic.evidence` is empty: name the file `red_sandbox.py --diagnostic` wrote under evidence/")
    else:
        name = evidence.replace("\\", "/").rsplit("/", 1)[-1]
        if not (name.startswith("diagnostic-") and name.endswith(".json")):
            problems.append(f"`diagnostic.evidence` is {evidence!r}: expected a file named diagnostic-<label>.json, the one "
                            "`red_sandbox.py --diagnostic` wrote (a control experiment's file is `control.evidence`)")
        elif task_root is not None:
            try:
                issue = evidence_ref_issue(task_root, {"path": evidence}, "`diagnostic.evidence`", require_hash=False,
                                           under="evidence")
            except (OSError, ValueError) as exc:
                issue = f"`diagnostic.evidence` path cannot be read ({exc})"
            if issue:
                problems.append(issue + "; name the file the diagnostic run wrote, relative to the task root, under evidence/")
    if "thens" in block:
        thens = block["thens"]
        if not isinstance(thens, list):
            problems.append(f"`diagnostic.thens` must be a list of {{then, outcome}} rows, not {type(thens).__name__}")
        else:
            for index, item in enumerate(thens):
                if not isinstance(item, dict) or then_number(item.get("then")) < 1 or isinstance(item.get("then"), str):
                    problems.append(f"`diagnostic.thens[{index}]` must be {{\"then\": <number >= 1>, \"outcome\": ...}}")
                elif item.get("outcome") not in TRIAGE_DIAGNOSTIC_OUTCOMES:
                    problems.append(f"`diagnostic.thens[{index}].outcome` is {item.get('outcome')!r}, expected one of "
                                    f"{list(TRIAGE_DIAGNOSTIC_OUTCOMES)}")
    return problems


def case_then_numbers(task_root, case, text=None) -> list:
    """The Then numbers of one case, in the order its file states them; `[]` when the case file is not found or states
    no Then (the caller says which, FR-59: an unknown is never a pass). THE one reader of the numbers a Then-level row
    is judged against (AR-13): the precheck's `blocked_by_check` row (`s5_precheck._check_blocked_then`) and the
    triage's `blocked_thens` (`triage_blocked_problems`) both ask it, so the two never disagree about which clauses a
    case has. `text` is the case file's text when the caller has read it already (the precheck's `texts`); else the
    file is found the precheck's way (`s5_precheck.find_case_file`). Pure apart from reading that file, never raises."""
    import s5_precheck as S5
    try:
        if text is None:
            path = S5.find_case_file(Path(task_root), case) if task_root is not None else None
            text = path.read_text(encoding="utf-8", errors="replace") if path else ""
        return [n for n, _ in S5.then_clauses(text or "")]
    except Exception:
        return []


def _blocked_entries(row) -> list:
    """The `blocked_thens` entries of one triage row that are objects; `[]` when the row has none or the key is no list
    (the validator names that, `triage_blocked_problems`)."""
    got = row.get("blocked_thens") if isinstance(row, dict) else None
    return [e for e in got if isinstance(e, dict)] if isinstance(got, list) else []


def _blocked_item(row: dict, entry: dict) -> dict:
    """One `blocked_thens` entry of a triage row in the form `then_remainder_errors` judges (a `blocked_by_check` row of
    `then_bindings`): the row's case and instance, the entry's Then, blocker and detail. No `owner`."""
    instance = row.get("instance_id")
    return {"case": str(row.get("case") or "").strip(), "then": entry.get("then"), "reason": BLOCKED_BY_CHECK,
            "blocking_check": entry.get("blocking_check"), "detail": entry.get("detail"),
            "instance_id": instance if isinstance(instance, str) and instance.strip() else None}


def _bound_triage_rows(triage, report) -> tuple:
    """`(rows, bound)`: the rows of `triage` (a triage document or its rows) and the ids of those bound to a failure of
    `report` by THE binding (`bind_triage`, attempt rule included). A row of another attempt is not in `bound`."""
    if isinstance(triage, dict):
        rows = triage_rows(triage)
    else:
        rows = [r for r in triage if isinstance(r, dict)] if isinstance(triage, list) else []
    failures, _notes = triage_failures(report)
    if not rows or not failures:
        return rows, set()
    matched = bind_triage(failures, rows)["matched"]
    return rows, {id(r) for bound in matched.values() for r in bound}


def triage_blocked_rows(triage, report, cfg=None) -> list:
    """The Thens a triage names as waiting for another case's defect, in the shape `then_remainders` returns
    (`{case, case_id, then, owner: "", part, detail, reason: blocked_by_check, blocking_check, instance_id}`), ONLY from
    rows bound to the CURRENT failure (`bind_triage(triage_failures(report), rows)`): the evidence of another run or
    attempt is not this run's (AR-28). A malformed entry (`then_remainder_errors`) or a row naming no case gives no row -
    the validator and the delivery check name it (`triage_blocked_problems`); the form check is the ONE shape check.
    A triage row carries the verdict of its red and never lowers it: these rows only say which Thens wait."""
    rows, bound = _bound_triage_rows(triage, report)
    out = []
    for row in rows:
        if id(row) not in bound:
            continue
        for entry in _blocked_entries(row):
            item = _blocked_item(row, entry)
            if not item["case"] or then_remainder_errors(item):
                continue
            if not _blocker_is_red(str(item["blocking_check"]).strip(), row, rows, bound):
                continue    # a stale blocker waits for nothing: neither a pass nor a line in "Left with you"
            try:
                bare = split_case_key(item["case"], cfg=cfg)[1] or item["case"]
            except Exception:
                bare = item["case"]
            diagnostic = row.get("diagnostic") if isinstance(row.get("diagnostic"), dict) else None
            out.append({"case": item["case"], "case_id": bare, "then": item["then"], "owner": "", "part": "",
                        "detail": " ".join(str(item["detail"]).split()), "reason": BLOCKED_BY_CHECK,
                        "blocking_check": str(item["blocking_check"]).strip(), "instance_id": item["instance_id"],
                        "diagnostic": _diagnostic_of_then(diagnostic, item["then"])})
    return out


def _blocker_is_red(blocker: str, row: dict, rows: list, bound: set) -> bool:
    """`blocker` (a case key or a test id) resolves to a triage row, other than `row`, bound to the CURRENT failure."""
    for other in rows:
        if other is row or id(other) not in bound:
            continue
        case = str(other.get("case") or "").strip()
        if (case and case_matches(blocker, case)) or any(same_id(blocker, n) for n in row_names(other)):
            return True
    return False


def _diagnostic_of_then(block, then) -> dict | None:
    """`{evidence, outcome}` of a row's `diagnostic` block for one Then (`outcome` is `""` when the block does not name
    the Then), None when the row has no usable block. The words are the analyst's; the outcome is a closed word."""
    if not isinstance(block, dict) or not isinstance(block.get("evidence"), str) or not block["evidence"].strip():
        return None
    outcome = ""
    for item in block.get("thens") if isinstance(block.get("thens"), list) else []:
        if isinstance(item, dict) and then_number(item.get("then")) == then and item.get("outcome") in TRIAGE_DIAGNOSTIC_OUTCOMES:
            outcome = item["outcome"]
    return {"evidence": block["evidence"].strip().replace("\\", "/"), "outcome": outcome}


def _red_thens_of(manifest, case, instance, cfg=None) -> set:
    """The Thens the manifest's `contradicts_requirement` rows of `case` name as red on `instance` (an id; a row with no
    instance slice speaks for the whole case). The reader of the red Thens of a case's own row (`thens`); `set()` when
    none is named."""
    out: set = set()
    for entry in manifest_unresolved(manifest):
        if str(entry.get("reason") or "") != "contradicts_requirement":
            continue
        if not case_matches(str(entry.get("case") or ""), case, cfg=cfg):
            continue
        slice_ids: set = set()
        for key in UNRESOLVED_INSTANCE_KEYS:
            value = entry.get(key)
            for one in value if isinstance(value, list) else [value]:
                slice_ids |= id_spellings(one)
        if slice_ids and not (id_spellings(instance) & slice_ids):
            continue
        raw = entry.get(UNRESOLVED_THENS_KEY)
        out |= {n for n in (then_number(x) for x in raw) if n} if isinstance(raw, list) else set()
    return out


def _instance_failed(failures: dict, instance) -> bool:
    """The run report records a failure (a result that needs a verdict) for the test `instance` stands for."""
    return any(kind == "result" and any(same_id(instance, n) for n in failure["names"])
               for (kind, _name), failure in failures.items())


def red_blocked_rows(manifest, report, cfg=None) -> list:
    """The `blocked_by_check` rows of the manifest that name a Then which RAN and failed: the Then stands in `thens` of a
    `contradicts_requirement` row of the same case on the same instance, and the report has that instance failed
    (`_red_thens_of`). Such a row contradicts the run (the executed red Then is never read as one that waits, FR-10): it
    is not a remainder (`then_remainders` drops it) and the delivery check names it as a factory record. A row naming no
    instance is not judged (nothing says it is the same test). `[]` for an unreadable report."""
    failures, _notes = triage_failures(report)
    if not failures:
        return []
    out = []
    for row in then_remainder_rows(manifest, cfg, (BLOCKED_BY_CHECK,)):
        instance = row.get("instance_id")
        number = then_number(row.get("then"))
        if (number and isinstance(instance, str) and instance.strip() and _instance_failed(failures, instance)
                and number in _red_thens_of(manifest, str(row.get("case") or ""), instance, cfg)):
            out.append(row)
    return out


def triage_blocked_problems(row, task_root=None, rows=None, report=None) -> list:
    """The problems of one triage row's `blocked_thens` / `blocking_check` fields (R6, t-1508), `[]` when there are none.
    THE one reader of the fields (AR-13): the validator (`check_triage_v0`) and the delivery check (`triage_reasons`) both
    ask it. It judges the FORM and the facts a file or the run can show; it never reads a wording (FR-12, AR-2).

    Each entry `{then, blocking_check, detail}` is judged as a `blocked_by_check` row by `then_remainder_errors` (the one
    shape check). With a `task_root`: the Then must be a Then of the row's case (`case_then_numbers`; a case file that
    cannot be read or states no Then is a problem, not a pass), and it must NOT be a Then the row's own case ran and failed
    (`_red_thens_of` over the manifest: an executed red Then is a defect, never "blocked"). With `rows` and `report`
    (the triage rows and the run report): every blocker (an entry's `blocking_check` and the row's own) must resolve to a
    triage row bound to the CURRENT failure (`_bound_triage_rows`) - a blocker that is not red in this run is a stale
    word, and no word of the analyst turns it into a pass. A blocker that is the row's own case is a problem. Absent or
    empty fields: `[]` (an old triage reads as it did). `task_root=None` / `rows`/`report` None: the corresponding facts are
    not judged here (the caller says so). Pure, never raises."""
    if not isinstance(row, dict):
        return []
    has_row_blocker = row.get("blocking_check") is not None
    if row.get("blocked_thens") is None and not has_row_blocker:
        return []
    case = str(row.get("case") or "").strip()
    problems = []
    blockers: list = []
    if has_row_blocker:
        blocker = row.get("blocking_check")
        if not (isinstance(blocker, str) and blocker.strip() and not any(ch.isspace() for ch in blocker)):
            problems.append(f"`blocking_check` must name the case or the test whose defect this red is: one word, no spaces, got {blocker!r}")
        else:
            blockers.append(blocker.strip())
    got = row.get("blocked_thens")
    if got is not None and not isinstance(got, list):
        problems.append(f"`blocked_thens` must be a list of {{then, blocking_check, detail}} rows, not {type(got).__name__}")
        got = []
    entries = got or []
    if entries and not case:
        problems.append("`blocked_thens` needs the row to name its `case`: the Thens are the Thens of that case")
    numbers = case_then_numbers(task_root, case) if (entries and case and task_root is not None) else None
    manifest = {}
    if entries and case and task_root is not None:
        try:
            manifest = load_json(artifact(Path(task_root), "automation-manifest.json"))
        except Exception:
            manifest = {}
    instance = row.get("instance_id") if isinstance(row.get("instance_id"), str) else ""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            problems.append(f"`blocked_thens[{index}]` must be an object {{then, blocking_check, detail}}")
            continue
        errors = then_remainder_errors(_blocked_item(row, entry))
        if errors:
            problems += [f"`blocked_thens[{index}]`: {e}" for e in errors]
            continue
        then = entry["then"]
        blocker = str(entry["blocking_check"]).strip()
        blockers.append(blocker)
        if numbers is not None:
            if not numbers:
                problems.append(f"`blocked_thens[{index}]`: the case file of {case} was not found or states no Then, so Then "
                                f"{then} cannot be checked - make {case}.md readable under the story's test-cases folder")
            elif then not in numbers:
                problems.append(f"`blocked_thens[{index}]`: Then {then} is not a Then of {case} (its Thens are numbered "
                                f"{', '.join(map(str, numbers))})")
            elif instance and then in _red_thens_of(manifest, case, instance):
                problems.append(f"`blocked_thens[{index}]`: Then {then} of {case} ran and failed on {instance}; it is not "
                                "blocked - drop it from `blocked_thens` (a red Then is the row's own failure)")
        if case and case_matches(blocker, case):
            problems.append(f"`blocked_thens[{index}]`: Then {then} waits for {blocker}, which is this row's own case; a "
                            "Then does not wait for its own case")
    if case and has_row_blocker and blockers and case_matches(blockers[0], case) and isinstance(row.get("blocking_check"), str):
        problems.append(f"`blocking_check` {row['blocking_check']!r} is this row's own case; name the case whose defect it is")
    if rows is not None and report is not None and blockers:
        pool, bound = _bound_triage_rows(rows, report)
        for blocker in dict.fromkeys(blockers):
            if not _blocker_is_red(blocker, row, pool, bound):
                problems.append(f"{blocker} is named as the check this row waits for, but no triage row of the current run "
                                f"is red for it: a stale blocker waits for nothing - record the Then's own outcome, or "
                                "name the case whose red this run does show")
    return problems


def triage_reorder_problems(row) -> list:
    """The problems of one triage row that asks for a `reorder` (R7, t-1508), `[]` when it asks for none or is sound. THE one
    reader of the field (AR-13): the validator (`check_triage_v0`) and the S7 round (`s7_reorder.find_row`) both ask it.
    `reorder` must be the boolean true, and it needs `blocked_thens` - the Thens whose asserts the round moves - as a list
    with at least one object: a `reorder` with no Then to move is a request nobody can execute. `reorder: false` is NO request,
    the same as the key absent (the null-outcome view reads it so; two readers of one field agree, AR-13). Pure, never raises."""
    if not isinstance(row, dict) or row.get("reorder") is None or row.get("reorder") is False:
        return []
    if row.get("reorder") is not True:
        return [f"`reorder` must be the boolean true (got {row.get('reorder')!r}); leave the key out for a row that asks for "
                "no reorder"]
    blocked = row.get("blocked_thens")
    if not (isinstance(blocked, list) and any(isinstance(e, dict) for e in blocked)):
        return ["`reorder: true` with no `blocked_thens`: name the Thens whose asserts the author moves above the red one as "
                "`blocked_thens: [{then, blocking_check, detail}]` ('One red, one triage' of the failure analyst), or drop `reorder`"]
    return []


# Executions of the one failing test needed to call it FLAKY, counted across EVERY role
# through the manifest's runs[] — not five fresh ones per role. The pilot ran TC-005 six
# times after its fix because each role restarted the count from zero (2026-09-15).
FLAKY_MIN_RERUNS = 3

# Checks-ledger states. Some carry a colon-suffixed detail (`failed:APP_BUG`,
# `not_executed:env_blocked`, `skipped:<reason>`, `env_blocked:<owner>`); the bare prefixes
# are what a state is validated against.
LEDGER_STATE_PREFIXES = (
    "passed_green", "failed", "not_executed", "skipped", "env_blocked", "impossible",
    "pending_implementation", "deferred_by_decision", "not_verified_flaky", "review_skipped",
    "subtask_in_progress",
    # A row whose every requirement a person waived at a gate. check_traceability already
    # honoured `gate_waivers[]`; the delivery ledger did not, so on TP2-2520 the
    # requirements were closed, the tests had actually run green, and the ledger still read
    # `not_executed` with `delivery_ready: No`. The state stays honest — it says waived, not
    # passed, and it carries whose decision it was — but it no longer blocks delivery.
    "waived",
    # Words `ledger.py` already emitted while this list lacked them, and the two review words of
    # FR-35: a rejected review, one the critic could not complete (D-0013, not blocking), and a
    # verdict this vocabulary does not hold (a defect of our own record, FR-19).
    "review_rejected", "review_unverified", "review_unrecognised",
    "not_verified", "partial", "error",
)
TERMINAL_LEDGER_STATES = LEDGER_STATE_PREFIXES  # every ledger state is terminal by construction

PLAN_HEADING = "## Plan"
PLAN_COLUMNS = {
    "ts": "ts",
    # The human-facing columns come first in the table (2026-09-15): the plan is read by
    # the owner at gate A, and it used to be paired with a `plan-brief.md` that restated
    # the same rows in readable words — two files, one set of rows, guaranteed to drift.
    "what we verify": "check",
    "r": "r",
    "defect hypothesis": "hypothesis",
    "impact class": "impact",
    "priority": "priority",
    "observable": "observable",
    "oracle": "oracle",
    "disposition + reason": "disposition_cell",
    "fit": "fit",
    "level": "level",
    "technique": "technique",
}
PLAN_REQUIRED_COLUMNS = ("ts", "r", "observable", "disposition_cell", "fit")

# A requirement id is `R-n` standing alone: `R-1` inside `BR-1` or `X-R-1` is another id (GW1-1, F-1). The right edge is
# left as it was: `R-12` is read whole by the greedy `\d+`, and `R-1.2`/`R-1a` keep reading `R-1` as before.
REQ_ID_RE = re.compile(r"(?<![\w-])R-\d+")
TS_ID_RE = re.compile(r"^TS-\d+$")
# There is no case id pattern here on purpose: the id form is the project's (`config.case_id_form`),
# so it is read through `case_ids`, `is_case_id`, `case_id_forms`, `is_case_file_name` and
# `case_glob`. The default-form attribute this line used to carry was deleted with its last
# importer (B-013).


def ledger_state_prefix(state: str) -> str:
    return str(state or "").split(":", 1)[0]


def is_ledger_state(state: str) -> bool:
    return ledger_state_prefix(state) in LEDGER_STATE_PREFIXES


# --- small readers --------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


WORK_DIR = "work"


def artifact(art_dir: Path, name: str) -> Path:
    """One artifact of a story, wherever it lives: `<artifacts>/work/<name>` first, then
    `<artifacts>/<name>`.

    Only four documents are written for a person — understanding, plan, report, retro —
    and they sit at the top of the story's folder. Everything the roles pass to each other
    moved one level down into `work/` (2026-09-15: 78 files reached the human's folder on
    TP1-13958, 54 of them run logs). The lookup tolerates both so a caller that has not
    been switched yet still finds a flat artifact instead of silently deciding the file
    does not exist — the failure mode this factory has already paid for once.
    """
    art_dir = Path(art_dir)
    from artifact_registry import canonical
    candidate = canonical(art_dir, name)
    legacy = art_dir / name
    if candidate.is_file() and legacy.is_file() and candidate.read_bytes() != legacy.read_bytes():
        raise ValueError(f"conflicting canonical and legacy artifact: {name}; migrate explicitly")
    if candidate.exists():
        return candidate
    if legacy.exists():
        return legacy
    # The mirror image of the lookup above. A delivered document's canonical path IS the story
    # root; on TP1-13797 the plan was written under `work/` instead, the S8 checks read zero
    # plan rows and called 19 of 19 requirements unreachable, and the orchestrator copied the
    # file by hand (FB-10). The phase files and the charters name the bare path now, and
    # `test_artifact_registry.py` holds them to it — this fallback stays for the stories written
    # before that, so a reader tries the other level before deciding the file is not there.
    under_work = art_dir / "work" / name
    return under_work if under_work.is_file() else legacy


def artifact_write_path(art_dir: Path, name: str) -> Path:
    """Canonical location for a machine artifact.

    ``artifact`` deliberately remains a legacy-tolerant reader.  Writers must use this
    helper so a flat legacy file is never selected merely because it already exists.
    """
    from artifact_registry import canonical
    return canonical(art_dir, name)


def read_text(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def strip_cell(value: str) -> str:
    return str(value or "").strip().strip("`").strip()


def md_table(text: str, heading: str) -> list:
    """Raw cell lists of the markdown table under `heading`, header row included."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(heading):
            start = i
            break
    if start is None:
        return []
    rows = []
    for line in lines[start + 1:]:
        st = line.strip()
        if st.startswith("## "):
            break
        if not st.startswith("|"):
            continue
        cells = G.split_cells(st)  # a `\|` inside a cell is part of it (G2-10)
        if cells and set("".join(cells)) <= set("-: "):
            continue  # the separator row
        rows.append(cells)
    return rows


# --- test-plan.md ----------------------------------------------------------------------------

def parse_plan(path: Path) -> list:
    """Rows of the v0 `## Plan` table as dicts, keyed by PLAN_COLUMNS. `line` carries the raw
    row text (the anti-pattern detectors read it whole), `index` the 1-based row number."""
    text = read_text(path)
    raw = md_table(text, PLAN_HEADING)
    if not raw:
        return []
    header = [strip_cell(c).lower() for c in raw[0]]
    mapping = {i: PLAN_COLUMNS[h] for i, h in enumerate(header) if h in PLAN_COLUMNS}
    rows = []
    for n, cells in enumerate(raw[1:], start=1):
        row = {"index": n, "line": " | ".join(cells)}
        for i, cell in enumerate(cells):
            key = mapping.get(i)
            if key:
                row[key] = strip_cell(cell)
        if not TS_ID_RE.match(row.get("ts", "")):
            continue
        row["requirements"] = REQ_ID_RE.findall(row.get("r", ""))
        row["disposition"], row["reason"] = split_disposition(row.get("disposition_cell", ""))
        row["observable_source"] = observable_source(row.get("observable", ""))
        rows.append(row)
    return rows


DISPOSITION_SPLIT_RE = re.compile(r"^\s*`?([a-z-]+)`?\s*(?:[—–-]\s*(.*))?$", re.DOTALL)


def split_disposition(cell: str) -> tuple:
    """'`automate` — coverage gap' -> ('automate', 'coverage gap')."""
    m = DISPOSITION_SPLIT_RE.match(str(cell or ""))
    if not m:
        return (strip_cell(cell), "")
    return (m.group(1), (m.group(2) or "").strip())


def observable_source(cell: str) -> str:
    """'diff:src/app.py:12' -> 'diff'; a cell with no known prefix -> ''."""
    value = strip_cell(cell)
    for src in OBSERVABLE_SOURCES:
        if value == src or value.startswith(src + ":"):
            return src
    return ""


def plan_is_v0(path: Path) -> bool:
    return bool(md_table(read_text(path), PLAN_HEADING))


# --- requirements-register.md -----------------------------------------------------------------

def register_ids(path: Path) -> list:
    """R ids in register order, from the `## Register` table's first column."""
    out = []
    for cells in md_table(read_text(path), "## Register")[1:]:
        if not cells:
            continue
        m = REQ_ID_RE.fullmatch(strip_cell(cells[0]))
        if m and m.group(0) not in out:
            out.append(m.group(0))
    return out


REGISTER_HEADING = "## Register"


def register_fence_view(path) -> dict:
    """{"state": "rows" | "empty" | "unknown", "ids": [...], "why": str}: what the S3 exit fence (GW1-41) may know of
    the register. Uses `md_table` and `REQ_ID_RE`, no second table reader. `unknown` is never a pass (FR-59, AR-28):
    no file, no table, a first `## Register...` heading that is not exactly `## Register` (`md_table` would read that
    table), or a table row whose first cell is no R-n (`**R-9**`, `R-9a`, `r-9`). Rows are compared one by one, not
    by `len(ids)`: `register_ids` drops repeats and a repeated id is no error. `empty` (a header and no row) is a
    declared outcome (AR-23), not an unknown."""
    p = Path(path)
    try:
        if not p.is_file():
            return {"state": "unknown", "ids": [], "why": "work/requirements-register.md is not there, so the plan cannot be checked against the register"}
        text = read_text(p)
    except OSError as exc:
        return {"state": "unknown", "ids": [], "why": f"work/requirements-register.md could not be read ({exc})"}
    heads = [line.strip() for line in text.splitlines() if line.strip().startswith(REGISTER_HEADING)]
    if heads and heads[0] != REGISTER_HEADING:
        return {"state": "unknown", "ids": [],
                "why": f'the first heading starting "{REGISTER_HEADING}" is "{heads[0]}"; md_table would read that table'}
    table = md_table(text, REGISTER_HEADING)
    if not table:
        return {"state": "unknown", "ids": [], "why": f'requirements-register.md has no table under "{REGISTER_HEADING}"'}
    ids: list = []
    for cells in table[1:]:
        if not "".join(cells).strip():
            continue
        found = REQ_ID_RE.fullmatch(strip_cell(cells[0] if cells else ""))
        if not found:
            shown = " | ".join(strip_cell(c) for c in cells[:3])
            return {"state": "unknown", "ids": [], "why": f"the register's table has rows without an R-n id: {shown}"}
        if found.group(0) not in ids:
            ids.append(found.group(0))
    return {"state": "rows" if ids else "empty", "ids": ids, "why": ""}


def candidate_marks() -> tuple:
    """The `derived_from` marks of `handoffs/vocabulary.yaml` (`derived_from_marks`, FR-13); () when the file cannot be
    read (a package defect, no candidate then - the register is still read whole by every other reader)."""
    try:
        import handoff
        marks = handoff.vocabulary().get("derived_from_marks")
        return tuple(m for m in marks if isinstance(m, str) and m) if isinstance(marks, list) else ()
    except Exception:  # noqa: BLE001
        return ()


def derived_from_segments(cell) -> list:
    """The `;`-separated segments of a `derived_from` cell, stripped."""
    return [part.strip() for part in str(cell or "").split(";") if part.strip()]


BUG_TRACKER_ID_RE = re.compile(r"[A-Z][A-Z0-9]*-\d+")


def derived_from_legal(cell) -> bool:
    """Is at least one `;` segment of a `derived_from` cell a lawful source? A segment is lawful when it matches the grammar
    (`G.DERIVED_FROM_RE`) and, if it starts with `bug:`, its tail is a tracker id (`BUG-12`, `TP1-123`) or exactly a
    candidate mark. `bug:none-recorded` alone is a misspelling of a mark (it would lose the requirement's road to a test) but
    `bug:none-recorded; invariant:x` is lawful through its second segment."""
    marks = candidate_marks()
    for seg in derived_from_segments(cell):
        if not G.DERIVED_FROM_RE.match(seg):
            continue
        if not seg.startswith("bug:") or BUG_TRACKER_ID_RE.fullmatch(seg[4:]) or seg in marks:
            return True
    return False


def candidate_defects(text: str) -> list:
    """[{r, requirement, file, line}] of the register rows whose `derived_from` has a SEGMENT equal to a candidate mark
    (exactly: `bug:candidate-defects` and `Bug:Candidate-Defect` are not the mark). `observable` of the form
    `current-code:<file>:<line>` gives file and line, anything else `file: None` (the brief then says the place is not
    named, FR-41). No register, no table, no mark: []. The mark is read from a row with or without `source: derived`."""
    marks = candidate_marks()
    if not marks:
        return []
    out = []
    for row in register_rows(text):
        if not any(seg in marks for seg in derived_from_segments(row.get("derived_from"))):
            continue
        requirement = row.get("requirement", "")      # the reader's own key, never a position
        file, line = None, None
        observable = row.get("observable") or ""
        if observable.startswith("current-code:"):
            where = observable[len("current-code:"):]
            head, _, tail = where.rpartition(":")
            if head and tail.isdigit():
                file, line = head, int(tail)
        out.append({"r": row["r"], "requirement": requirement, "file": file, "line": line})
    return out


def case_set_aside(case, disposition, manifest, report) -> bool:
    """True when `disposition` is one of `branch_accounting.PLAN_EXCLUDING` and the case never ran: no result in
    `run_results(report)`, not in `run_impossible(report)`, linked by no `manifest_tests` row and no
    `manifest_unresolved` row. A case that RAN is never set aside (an error here goes toward the gap, never toward
    hiding a red run)."""
    from branch_accounting import PLAN_EXCLUDING
    if disposition not in PLAN_EXCLUDING:
        return False
    # Both spellings of the case: `a/TC-001` (two areas hold TC-001) and the bare `TC-001`, which is what the links and
    # most results carry. A bare id keeps BOTH areas' cases: the error goes toward the gap (t-604 F-2).
    # D2-B3: by the identity lookup, not a raw key set (the bare spelling of an area key is no longer a stored alias)
    spellings = {case, split_case_key(case)[1]} - {""}
    if (case_lookup(run_results(report), case, rollup=False) is not None
            or case_lookup(run_impossible(report), case, rollup=False) is not None):
        return False
    for entry in [*manifest_tests(manifest), *manifest_unresolved(manifest)]:
        if spellings & set(manifest_test_links(entry)):
            return False
    return True


# --- test-cases/<area>/TC-NNN.md ---------------------------------------------------------------

CASE_REQ_LINE_RE = re.compile(r"^\s*Requirements:\s*(.+)$", re.MULTILINE)
CASE_PLAN_ROW_RE = re.compile(r"^\s*Plan row:\s*(TS-\d+)", re.MULTILINE)


GATE_ORDER = ("A", "B")

# One field, two vocabularies. Until the controller existed the orchestrator wrote
# `gates.A.decision = "approve"` by hand, and the fixtures and the contract document still
# show that spelling; `controller.py` projects its own decision record as
# `decision = "approved"` with `status = "approved"` beside it. On TP1-15045 the person
# said "approve", the controller recorded it, and `stage_guard.rule_gate_a` — which compared
# against the single string "approve" — refused S5 anyway. Nobody caught it because no test
# ran a decision through the controller and then through a reader. So there is exactly one
# reader of "is this gate approved", and it knows every spelling the factory has ever written.
GATE_APPROVED_WORDS = {"approve", "approved"}
# Gate B is a delivery decision: "deliver with known gaps" IS an approval to write out, and
# the two readers that knew it spelled it differently (`deliver_with_risk` in
# external_writes.py, `deliver_with_risks` on the dashboard). Both stay accepted.
GATE_B_APPROVED_WORDS = {"deliver", "deliver_with_risk", "deliver_with_risks"}


def _gate_record(pipeline: dict, gate: str) -> dict:
    gates = (pipeline or {}).get("gates")
    record = (gates or {}).get(str(gate)) if isinstance(gates, dict) else None
    return record if isinstance(record, dict) else {}


def gate_approved(pipeline: dict, gate: str) -> bool:
    """The ONE reader of `gates.<gate>` — did a person approve this gate?

    Either field is enough, because they are the same answer in two hands: `status` is the
    controller's own word on its decision record (approved | declined | deferred), `decision`
    is what the orchestrator wrote by hand before the controller existed, and for gate B also
    the deliver-with-risks variants. Deliberately generous rather than strict — a story
    already in flight, written by an older version, must never be refused by a reader that got
    tidier. `edit`, `declined`, `deferred`, an empty record and no record at all are all
    "not approved"."""
    record = _gate_record(pipeline, gate)
    if str(record.get("status") or "").strip().lower() == "approved":
        return True
    allowed = set(GATE_APPROVED_WORDS)
    if str(gate).upper() == "B":
        allowed |= GATE_B_APPROVED_WORDS
    return str(record.get("decision") or "").strip().lower() in allowed


def gate_risk_reason(pipeline: dict) -> str:
    """The reason of the person's decision to deliver with known gaps, as the gate B record keeps it (`deliver_with_risks.reason`,
    written by `controller.py --operation gate-decision --gate B` - HF8-23), or "" (AR-13: the one reader of the field, through
    `_gate_record`). It reads ONLY: a refusal's text selector, never a door. ERROR DIRECTION: toward "" - no gate B record, a
    gate B that is not approved (declined, deferred, edit), a field that is no object, a reason that is blank or no text, all read
    as no decision (the guard then says so and opens nothing)."""
    if not gate_approved(pipeline, "B"):
        return ""
    risks = _gate_record(pipeline, "B").get("deliver_with_risks")
    reason = risks.get("reason") if isinstance(risks, dict) else None
    return reason if isinstance(reason, str) and reason.strip() else ""


def risk_journal_door(ticket: str) -> str:
    """The command that writes the journal line the delivery guard reads when a decision to deliver with known gaps is recorded and the
    line is not (a person's reason goes by file, never inline: cmd.exe cuts inline words at the first line break). One text for the
    controller's answer and the guard's refusal (AR-13)."""
    return f"log_append.py --event deliver_with_risks --task {ticket} --reason-file <file with their reason>"


def gate_answered(pipeline: dict, gate: str) -> bool:
    """A different question from `gate_approved`, and archive_task.py asks this one: was the
    person put in front of this gate at all? A decline is an answer."""
    record = _gate_record(pipeline, gate)
    return bool(str(record.get("decision") or record.get("status") or "").strip())


def waivers_by_requirement(pipeline: dict) -> dict:
    """requirement -> the waiver that governs it, from pipeline.json's `gate_waivers[]`.

    A gap the human accepted at a gate is a decision like any other, and a decision that
    cannot be read by code does not survive to the next gate: on TP2-2381 gate A
    accepted R-9's missing coverage in prose, gate B recomputed it from the artifacts, and
    the story went round the whole pipeline to ask the same person again. The later gate
    wins — a requirement waived at A and revisited at B carries B's words."""
    out: dict = {}
    for entry in (pipeline or {}).get("gate_waivers") or []:
        if not isinstance(entry, dict):
            continue
        req = str(entry.get("requirement") or "").strip()
        if not req:
            continue
        current = out.get(req)
        if current is None or _gate_rank(entry) >= _gate_rank(current):
            out[req] = entry
    return out


def _gate_rank(entry: dict) -> int:
    gate = str((entry or {}).get("gate") or "")
    return GATE_ORDER.index(gate) if gate in GATE_ORDER else -1


def story_waivers(artifacts: Path) -> dict:
    """The same reading, for a caller that has the story folder and not the pipeline."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    return waivers_by_requirement(load_json(art / "pipeline.json"))


_CONTROLLER_ROOT_CACHE: dict = {}
_CASE_CONFIG_CACHE: dict = {}


def _stat_key(path: Path) -> tuple:
    st = path.stat()
    return (str(path), st.st_mtime_ns, st.st_size)


def _controller_project_root(controller_path: Path):
    """The project a story belongs to, resolved ONCE per (path, mtime, size) of its controller.json (B-013: `case_ids`
    asks on every call, and controller.json is the largest file there), or None when no project holds the story.

    The `known_paths.project_root` the state stored at `initialize` is only the HINT of `runtime_paths.project_for_task`
    (t-304 N1, reader #1): a story copied to another worktree kept the old root, and reading it as a location sent
    `cases_root` and every config read into the other project. A state that carries no hint (absent, `{}`, a legacy list)
    is resolved from the story's own place, as before."""
    key = _stat_key(controller_path)
    if key not in _CONTROLLER_ROOT_CACHE:
        if len(_CONTROLLER_ROOT_CACHE) > 64:
            _CONTROLLER_ROOT_CACHE.clear()
        state = json.loads(controller_path.read_text(encoding="utf-8"))
        stored = state.get("known_paths") if isinstance(state, dict) else None
        hint = stored.get("project_root") if isinstance(stored, dict) else None
        try:
            found = runtime_paths.project_for_task(controller_path.parent.parent, hint=hint)
        except ValueError:
            found = None          # no project holds it: `_config_location` goes on to the walk and the hook layer
        _CONTROLLER_ROOT_CACHE[key] = found
    return _CONTROLLER_ROOT_CACHE[key]


def _config_location(artifacts=None) -> tuple:
    """(config.json path, project root, strict) — where `_project_config` reads, without reading.

    `strict` says an unreadable file raises (the story-anchored routes always did); the hook
    layer's own route answers {} instead. The path is None when there is no hook layer to ask."""
    if artifacts is not None:
        task = Path(artifacts).resolve()
        controller_path = task / "state/controller.json"
        if controller_path.exists():
            root = _controller_project_root(controller_path)
            if root is not None:
                return root / "qa-factory/config.json", root, True
        for root in (task, *task.parents):
            cfg_path = root / "qa-factory/config.json"
            if cfg_path.is_file():
                return cfg_path, root, True
    try:
        from hooklib import config_path, project_root
        return config_path(), project_root(), False
    except Exception:
        return None, Path("."), False


def _project_config(artifacts=None) -> tuple:
    """(config, project root) when the hook layer is importable, ({}, '.') otherwise.

    A soft dependency on purpose: contract.py must stay usable from a bare `python
    contract.py` in a directory that is not a project at all."""
    path, root, strict = _config_location(artifacts)
    if path is None:
        return {}, root
    if strict:
        return json.loads(path.read_text(encoding="utf-8")), root
    try:
        return json.loads(path.read_text(encoding="utf-8")), root
    except Exception:
        return {}, root


def _case_config(artifacts=None) -> dict:
    """The project config as the case-id helpers read it. NEVER raises: whatever cannot be read
    (no project, no file, broken JSON, not an object) is {} — the default form only, which is what
    every caller outside a project has always got.

    Two layers, both for speed (B-013): the file is read at most once per (resolved path, mtime_ns,
    size), and the RESOLUTION itself (which config, and its stat) is redone at most once per
    `CASE_CONFIG_WINDOW_S` seconds per anchor (the story folder, or the process's own project) on a
    monotonic clock. Before the window a call cost a location walk plus a stat, ~125 us quiet and
    ~1.2 ms on a loaded disk against ~3 us for the old `TC-\\d+` findall, so any loop over tests x
    cases (manifest_put's merge, traceability, the ledger) was 7-15x slower.

    TRADE-OFF: a config rewritten by ANOTHER process is seen by this process within 2 s, not on the
    next call. Hooks and the driver's children are separate processes with an empty memo, so they
    read the file on their first call and always see the current form; only a long-lived process that
    rewrites its own config (a test) must call `case_config_reset()`. A rewrite that keeps both
    mtime_ns and size within one clock tick would also be served stale by the read cache; a person
    editing the config is far slower than that."""
    try:
        anchor = _case_config_anchor(artifacts)
        now = _CASE_CONFIG_CLOCK()
        memo = _CASE_CONFIG_MEMO.get(anchor)
        if memo is not None and now - memo[0] < CASE_CONFIG_WINDOW_S:
            return memo[1]
        found = _read_case_config(artifacts)
        if len(_CASE_CONFIG_MEMO) > 256:
            _CASE_CONFIG_MEMO.clear()
        _CASE_CONFIG_MEMO[anchor] = (now, found)
        return found
    except Exception:
        return {}


CASE_CONFIG_WINDOW_S = 2.0
_CASE_CONFIG_CLOCK = time.monotonic  # a test injects its own clock here
_CASE_CONFIG_MEMO: dict = {}


def _case_config_anchor(artifacts) -> tuple:
    """What one memo entry answers for: the story folder, or the process's own project (its root
    is part of the key, so a process that moves between projects never reads the other's memo)."""
    if artifacts is not None:
        return (str(artifacts), "")
    try:
        from hooklib import project_root
        return ("", str(project_root()))
    except Exception:
        return ("", "")


def _read_case_config(artifacts) -> dict:
    path, _root, _strict = _config_location(artifacts)
    if path is None:
        return {}
    try:
        key = _stat_key(path)
        if key not in _CASE_CONFIG_CACHE:
            if len(_CASE_CONFIG_CACHE) > 64:
                _CASE_CONFIG_CACHE.clear()
            data = json.loads(path.read_text(encoding="utf-8"))
            _CASE_CONFIG_CACHE[key] = data if isinstance(data, dict) else {}
        return _CASE_CONFIG_CACHE[key]
    except Exception:
        return {}


def case_config_reset() -> None:
    """Forget every memoised resolution and read at once. For a process that rewrites a config it
    then asks about (tests); a hook or a child process never needs it."""
    _CASE_CONFIG_MEMO.clear()
    _CASE_CONFIG_CACHE.clear()


def case_config(artifacts=None) -> dict:
    """The project config as the case-id helpers read it, resolved ONCE for a caller that is about
    to ask many questions and hands the result back as `cfg=` (B-013, performance).

    Every public case helper below takes `artifacts=` (which story's project decides) and resolves
    the config on each call: a stat of the config file, ~125 us quiet and ~1.2 ms on a loaded
    disk, against ~3 us for the old `TC-\\d+` findall. Inside a loop over tests x results that
    was 5-10 s for a story of a hundred tests; a function holding the story resolves here once and
    passes `cfg=`, and the loop pays the regex only. Never raises: `{}` is the default form."""
    return _case_config(artifacts)


def _cfg_of(artifacts, cfg) -> dict:
    """`cfg` when the caller resolved it (a dict, even an empty one), else the config of `artifacts`."""
    return cfg if isinstance(cfg, dict) else _case_config(artifacts)


def case_id_forms(artifacts=None) -> tuple:
    """The case id templates in force for this project: its `config.case_id_form`, then `TC-{nnn}`."""
    return case_forms.forms(_case_config(artifacts))


def is_case_id(value, artifacts=None, cfg=None) -> bool:
    """Is the whole value one case id, in any form in force?"""
    return case_forms.is_id(value, _cfg_of(artifacts, cfg))


def is_case_file_name(name, artifacts=None, cfg=None) -> bool:
    """Is this the file name of a case document (`<id>.md`, or `<id>-<title>.md`)?"""
    return case_forms.is_case_file_name(name, _cfg_of(artifacts, cfg))


def case_id_example(ticket, artifacts=None, n: int = 1) -> str:
    """A well-formed id in the project's first form, for a text that shows one to a role or a person."""
    return case_forms.example(ticket, _case_config(artifacts), n)


def cases_root(artifacts: Path) -> Path:
    """Where this story's case documents live.

    The project's own case store when onboarding recorded one (`config.cases_root`), else
    the story's own `work/test-cases/`. Discovery has always LOOKED for an existing store —
    `test-cases/`, directories of `TC-*` ids, a TMS link — and the finding went into no
    config key, so every case the factory wrote landed in its own per-story tree beside the
    project's real library. The factory brings a process, not a filing scheme: where a
    project keeps its cases is a fact about the project.

    An unset key is today's behaviour, so a config written before this existed keeps
    working and nothing on disk moves."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    cfg, root = _project_config(art)
    raw = str(cfg.get("cases_root") or "").strip()
    return (Path(root) / raw) if raw else artifact(art, "test-cases")


def story_case_links(artifacts: Path) -> list:
    """Pinned immutable CaseVersions for this task, or an empty list for legacy stories."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    data = load_json(art / "state" / "story-case-links.json")
    return [link for link in data.get("links") or [] if isinstance(link, dict)]


def case_link_issues(artifacts: Path) -> list:
    """Dangling or modified pinned versions are delivery blockers, never silently repaired."""
    issues = []
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    for link in story_case_links(art):
        raw = str(link.get("path") or "")
        path = (art / raw).resolve() if raw else Path()
        # The key, not the number: with two areas pinned, "case link TC-001/..." twice over
        # names no file a person could go and look at.
        cid = case_link_key(link) or str(link.get("case_id") or "?")
        version = str(link.get("version") or "?")
        if not raw or Path(raw).is_absolute() or not path.is_relative_to(art.resolve()):
            issues.append(f"case link {cid}/{version} has a non-portable or escaping snapshot path")
            continue
        if not path.exists():
            issues.append(f"case link {cid}/{version} is missing its immutable version")
            continue
        expected = str(link.get("content_hash") or "")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not expected or actual != expected:
            issues.append(f"case link {cid}/{version} content hash does not match its pinned version")
        elif version != "cv_" + actual[:20]:
            issues.append(f"case link {cid}/{version} is not the content-addressed version of its pinned bytes")
    return issues


def case_glob(root, artifacts=None, cfg=None) -> list:
    """Every case document under `root`, sorted: each `.md` whose name is a case file name in the
    project's id form (`is_case_file_name`). `[]` when `root` is not a directory.

    The one glob every scanner uses in place of a name pattern for the default form (B-013, FR-17):
    that pattern was written into eleven scripts, so a project-form store was an empty store to each of them.
    `artifacts` names the story or project whose config decides (default: `root` itself, whose
    parents lead to its project); `cfg` is that config when the caller already resolved it."""
    root = Path(root)
    if not root.is_dir():
        return []
    cfg = _cfg_of(root if artifacts is None else artifacts, cfg)
    # `hooklib.sorted_paths`: the posix string, i.e. code point order, the same on every platform
    # (`sorted(Path)` is case-folded on Windows - the order of a joint refusal built from this walk
    # changed with the filesystem flavour, t-887). Imported here, as the other `hooklib` names of this
    # module are: `import contract` does not run hooklib's stdio setup.
    from hooklib import sorted_paths
    return sorted_paths(f for f in root.rglob("*.md") if case_forms.is_case_file_name(f.name, cfg))


def case_files(artifacts: Path) -> list:
    """This story's case files, wherever the project keeps cases.

    `artifacts` may be the story folder or its `work/`. In a shared store the files of
    other stories live beside these, so the story's own are selected by the `task` field
    every case carries — an index that swept the whole library would hand this story
    somebody else's coverage."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    links = story_case_links(art)
    if links:
        # A pinned story must read its recorded versions, even when a later story edits
        # the shared authoring copy. Invalid links are exposed through case_link_issues;
        # silently falling back would make historical reports depend on today's case text.
        out = []
        for link in links:
            raw = str(link.get("path") or "")
            path = (art / raw).resolve() if raw and not Path(raw).is_absolute() else None
            if path and path.is_relative_to(art.resolve()) and path.exists():
                out.append(path)
        return out
    root = cases_root(art)
    if not root.exists():
        return []
    # Every .md, then the id form decides: the glob used to be `TC-*.md`, so a store written in
    # the project's own form (`TP1-13877_TC_001.md`) was an empty store (B-013).
    files = case_glob(root, art)
    if root == artifact(art, "test-cases"):
        return files
    return [f for f in files if case_task(f) == art.name]


CASE_TASK_RE = re.compile(r"^\s*task:\s*(\S+)", re.MULTILINE)


def case_task(path: Path) -> str:
    """The story a case was written for, from its frontmatter ('' when it has none)."""
    text = read_text(path)
    parts = text.split("---", 2)
    head = parts[1] if text.lstrip().startswith("---") and len(parts) > 2 else text
    m = CASE_TASK_RE.search(head)
    return m.group(1).strip().strip('"\'') if m else ""


def _case_id(path: Path, cfg: dict) -> str:
    found = case_forms.ids_in(Path(path).name, cfg)
    return found[0] if found else Path(path).stem


def case_id(path: Path) -> str:
    """The id a case file's NAME carries (the first form match), else its stem."""
    return _case_id(path, _case_config(path))


def declared_case_id(path: Path) -> str:
    """Return the frontmatter case id, independently from the filename identity."""
    text = read_text(path)
    parts = text.split("---", 2)
    if not (text.lstrip().startswith("---") and len(parts) > 2):
        return ""
    match = re.search(r"^\s*id:\s*([^\s#]+)", parts[1], re.MULTILINE)
    return match.group(1).strip().strip('"\'') if match else ""


# --- case identity: `<area>/TC-NNN` ------------------------------------------------------------
# A case number is unique inside its AREA, not inside the story: the store is
# `test-cases/<area>/TC-NNN.md`, and `speakers/` and `speaker-detail/` both start at TC-001.
# TP2-2536 ran with both, and everything that merged by the bare id — `unresolved[]`,
# the pinned case links — read `speakers/TC-001` and `speaker-detail/TC-001` as one record, so a
# recovery kept one of each pair and two approved entries were simply gone (FB-2428-1).
# The identity is `<area>/TC-NNN` when an area is known and the bare `TC-NNN` when it is not; a
# bare id keeps matching any area, because that is how every record 0.7.x wrote spells a case.
CASE_KEY_SEP = "/"
CASE_AREA_RE = re.compile(r"^\s*area:\s*([^\s#]+)", re.MULTILINE)
# Directories that are the store's own layout and never an area: `<store>/cases/TC-NNN/cv_*.md`
# is a content-addressed version and `state/case-versions/TC-NNN/` a story's own snapshot.
_STORE_DIRS = {"test-cases", "cases", "case-versions"}


# The id is the project's form (`config.case_id_form`, then `TC-{nnn}`), so every helper below
# has an internal `_x(..., cfg)` that takes the config dict and a public `x(...)` that resolves it.
# The internal one is what a function holding a story folder calls: the config of THAT story's
# project, never of whichever project the process happens to be standing in.
CASE_STORE_DIRS = _STORE_DIRS


# (key text, forms in force) -> the split. The split is a pure function of those two, and a loop over
# tests x cases asks the same few keys thousands of times (B-013 performance).
_SPLIT_MEMO: dict = {}


def _split_case_key(key, cfg) -> tuple:
    text = str(key or "").strip().replace("\\", CASE_KEY_SEP)
    memo_key = (text, case_forms.forms(cfg))
    found = _SPLIT_MEMO.get(memo_key)
    if found is None:
        area, _, tail = text.rpartition(CASE_KEY_SEP)
        if not case_forms.is_id(tail, cfg) or case_forms.ids_in(area, cfg):
            found = ("", text)
        else:
            found = (area.strip().strip(CASE_KEY_SEP), tail)
        if len(_SPLIT_MEMO) > 4096:
            _SPLIT_MEMO.clear()
        _SPLIT_MEMO[memo_key] = found
    return found


def split_case_key(key, artifacts=None, cfg=None) -> tuple:
    """`("speakers", "TC-001")` / `("", "TC-001")` — the area and the case id of one key.

    Only a canonical case id (a form in force: the project's, then `TC-NNN`) is read as the
    tail, so the compound cell `"TC-001/TC-002/TC-003"` (TP1-14501: three cases chained
    into one test) is not mistaken for area `TC-001`. It comes back whole and its caller falls
    back to `case_ids`.
    """
    return _split_case_key(key, _cfg_of(artifacts, cfg))


def _case_key(case_id: str, area: str, cfg) -> str:
    known, cid = _split_case_key(case_id, cfg)
    if not case_forms.is_id(cid, cfg):
        return cid
    found = known or str(area or "").replace("\\", CASE_KEY_SEP).strip().strip(CASE_KEY_SEP)
    return f"{found}{CASE_KEY_SEP}{cid}" if found else cid


def case_key(case_id: str, area: str = "", artifacts=None, cfg=None) -> str:
    """The identity of one case — `speakers/TC-001` with an area, `TC-001` without one.

    Idempotent, and the `area` argument only fills in one that is missing: a caller never has
    to know which of the two spellings it was handed. A value that is not a canonical case id
    is returned untouched, because inventing `speakers/TC-001/TC-002` out of a compound cell
    would name a case nothing has ever written."""
    return _case_key(case_id, area, _cfg_of(artifacts, cfg))


def _case_matches(key, case_id, area: str, cfg) -> bool:
    key_area, key_id = _split_case_key(key, cfg)
    want_area, want_id = _split_case_key(_case_key(case_id, area, cfg), cfg)
    if not case_forms.is_id(key_id, cfg) or not case_forms.is_id(want_id, cfg):
        return str(key or "").strip() == str(case_id or "").strip()
    if key_id != want_id:
        return False
    return not key_area or not want_area or key_area == want_area


def case_matches(key: str, case_id: str, area: str = "", artifacts=None, cfg=None) -> bool:
    """Does `key` name this case? A bare id on either side matches any area.

    That generosity IS the compatibility rule: `unresolved[]` rows, ledger cells, scopes and
    pinned links written by 0.7.x carry no area at all, and a reader that demanded one would
    stop seeing the records this factory wrote last week."""
    return _case_matches(key, case_id, area, _cfg_of(artifacts, cfg))


def _case_area(path, cfg) -> str:
    path = Path(path)
    text = read_text(path)
    parts = text.split("---", 2)
    head = parts[1] if text.lstrip().startswith("---") and len(parts) > 2 else text
    m = CASE_AREA_RE.search(head)
    if m:
        return m.group(1).strip().strip('"\'')
    parent = path.parent.name
    if not parent or parent in _STORE_DIRS or case_forms.is_id(parent, cfg):
        return ""
    return parent


def case_area(path) -> str:
    """The area of a case file: its front matter `area:`, else the directory holding it when
    that directory is an area and not part of the store's own layout."""
    return _case_area(path, _case_config(path))


def case_link_key(record, cfg=None) -> str:
    """The case identity of a pinned link, a store record or a `case_version_links[]` entry.

    `case_id` stays the bare number on every one of them — readers that match a manifest row
    against a ledger cell spell cases the way 0.7.x did — and the area travels beside it."""
    cfg = _cfg_of(None, cfg)
    if not isinstance(record, dict):
        return _case_key(record, "", cfg)
    return _case_key(record.get("case_id") or record.get("case") or "", record.get("area") or "", cfg)


def _case_keys(value, area: str = "", artifacts=None, cfg=None) -> list:
    """Every case one cell names, each carrying the area it declared or the one handed in."""
    cfg = _cfg_of(artifacts, cfg)
    found, cid = _split_case_key(value, cfg)
    if case_forms.is_id(cid, cfg):
        return [_case_key(cid, found or area, cfg)]
    return [_case_key(one, area, cfg) for one in case_forms.ids_in(value, cfg)]


def case_requirements(path: Path) -> list:
    m = CASE_REQ_LINE_RE.search(read_text(path))
    return REQ_ID_RE.findall(m.group(1)) if m else []


def case_plan_row(path: Path) -> str:
    m = CASE_PLAN_ROW_RE.search(read_text(path))
    return m.group(1) if m else ""


CASE_STATUS_RE = re.compile(r"^\s*status:\s*(\S+)", re.MULTILINE)
CASE_AUTOMATED = "Automated"


def case_status(path: Path) -> str:
    """The lifecycle status from a case's frontmatter, '' when it has none.

    Read from the frontmatter block only: a `status:` line in the body is a step of the
    case, not its state. The whole lifecycle hangs on this one field — the coverage map
    counts `Automated` from it, so a case nobody transitioned reports as uncovered work
    beside a green suite (TP2-2386)."""
    text = read_text(path)
    parts = text.split("---", 2)
    head = parts[1] if text.lstrip().startswith("---") and len(parts) > 2 else text
    m = CASE_STATUS_RE.search(head)
    return m.group(1).strip() if m else ""


class CaseIndex(dict):
    """`case_index` by identity, readable by either spelling.

    A reader that holds only the bare `TC-001` — a manifest row written by 0.7.x, a scope a
    person typed — still finds the case as long as no second area claims that number. When two
    do, the bare id names two different cases, so `.get` answers with its default instead of
    guessing one of them, `[]` says which areas to choose between, and `matching()` names them
    all (that is how `stage-scope` learns it must hand out `<area>/TC-NNN`)."""

    # The config of the story this index was built for, set by `case_index`; None resolves the
    # process's own project at call time.
    _cfg = None

    def matching(self, case_id, area: str = "") -> list:
        wanted = str(case_id or "").strip()
        if dict.__contains__(self, wanted):
            return [wanted]
        cfg = self._cfg if self._cfg is not None else _case_config(None)
        return [key for key in self if _case_matches(key, wanted, area, cfg)]

    def get(self, key, default=None):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        found = self.matching(key)
        return dict.__getitem__(self, found[0]) if len(found) == 1 else default

    def __contains__(self, key) -> bool:
        return dict.__contains__(self, key) or bool(self.matching(key))

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        found = self.matching(key)
        if len(found) == 1:
            return dict.__getitem__(self, found[0])
        if found:
            raise KeyError(f"{key} names {len(found)} cases ({', '.join(sorted(found))}) — name the area")
        raise KeyError(key)


def case_index(artifacts: Path) -> CaseIndex:
    """The story's cases -> {'path', 'requirements', 'plan_row', 'area'}, keyed by identity.

    `TC-NNN` while that number belongs to one area, `<area>/TC-NNN` when two areas both hold
    it (FB-2428-1). Two areas coexisting used to raise `case identity collision` here and take
    every reader of the index down with it — the delivery check, the ledger, the controller's
    scope — so the number alone stops being the identity exactly when it stops being unique,
    and not a story earlier."""
    art = Path(artifacts)
    if art.name == WORK_DIR:
        art = art.parent
    versions = {str((art / str(link.get("path"))).resolve()): link
                for link in story_case_links(art) if str(link.get("path") or "") and not Path(str(link.get("path"))).is_absolute()}
    cfg = _case_config(art)
    origins, entries, problems = {}, [], []
    for path in case_files(artifacts):
        link = versions.get(str(path)) or {}
        cid = str(link.get("case_id") or _case_id(path, cfg))
        declared = declared_case_id(path)
        expected_id = str(link.get("case_id") or _case_id(path, cfg))
        if declared and declared != expected_id:
            problems.append(f"case identity mismatch: {path} declares {declared} but source identity is {expected_id}")
        area = str(link.get("area") or "") or _case_area(path, cfg)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = _case_key(cid, area, cfg)
        if key in origins and origins[key] != (str(path), digest):
            prior_path, prior_hash = origins[key]
            problems.append(f"case identity collision {key}: {prior_path} ({prior_hash}) and {path} ({digest})")
        origins[key] = (str(path), digest)
        entries.append((cid, area, path, link))
    if problems:
        # K1: every file's identity problem in ONE refusal, in file order - the two checks of
        # one file and the checks of the next do not read one another, and the first-failure
        # raise cost a round per file. Same class (`ValueError`), the combined form of
        # `detector_verdict.compound`; one problem is its own sentence, unchanged.
        from detector_verdict import compound
        raise ValueError(compound(problems))
    areas: dict = {}
    for cid, area, _, _ in entries:
        areas.setdefault(cid, set()).add(area)
    out = CaseIndex()
    out._cfg = cfg
    for cid, area, path, link in entries:
        out[_case_key(cid, area, cfg) if len(areas[cid]) > 1 else cid] = {
            "path": path,
            "requirements": case_requirements(path),
            "plan_row": case_plan_row(path),
            "version": str(link.get("version") or ""),
            "case_id": cid,
            "area": area,
        }
    return out


def scope_member_resolution(members, index, pinned_only: bool = False, cfg=None) -> list:
    """`[(member, keys, why)]`, one per member, in order: which index keys a scope member names (CX1-11).

    THE rule that turns a spelling of a case into the keys the index holds (the scope writer, rework, dispatch and
    the Gate A pin check all read it, FR-17). A string is read by `_split_case_key` (strip, `\\` -> `/`, nested areas):
    exactly a case id, or `<area>/<id>`. A bare id names EVERY key of that number (a number two areas hold is two
    keys, F-1); a qualified one names the keys of that number whose area is the one named, never another area's
    (`billing/TC-001` is not `TC-001`). `why` is "" when `keys` is non-empty, else "not a string" / "not a case id" /
    "no such case" / "pinned in: <areas>" (the number exists, the area named does not hold it). The error direction is
    REFUSAL (I3): nothing is widened here, an unknown member names nothing. `pinned_only` skips index entries whose
    link carries no version (an unpinned case is no pinned case). The reverse map is built ONCE per call
    (O(members + index), E8)."""
    cfg = cfg if isinstance(cfg, dict) else _cfg_of(None, getattr(index, "_cfg", None))
    held: dict = {}
    for key, entry in index.items():
        if pinned_only and not (entry or {}).get("version"):
            continue
        area = str((entry or {}).get("area") or "").replace("\\", CASE_KEY_SEP).strip().strip(CASE_KEY_SEP)
        held.setdefault(str((entry or {}).get("case_id") or key), []).append((str(key), area))
    out = []
    for member in members:
        if not isinstance(member, str):
            out.append((member, [], "not a string"))
            continue
        area, number = _split_case_key(member, cfg)
        if not case_forms.is_id(number, cfg):
            out.append((member, [], "not a case id"))
            continue
        entries = held.get(number) or []
        keys = sorted(key for key, held_area in entries if not area or held_area == area)
        if keys:
            out.append((member, keys, ""))
        elif entries:
            out.append((member, [], "pinned in: " + ", ".join(sorted({a or "no area" for _, a in entries}))))
        else:
            out.append((member, [], "no such case"))
    return out


# --- automation-manifest.json ------------------------------------------------------------------

def manifest_tests(manifest: dict) -> list:
    return [t for t in (manifest.get("tests") or []) if isinstance(t, dict)]


def manifest_unresolved(manifest: dict) -> list:
    return [u for u in (manifest.get("unresolved") or []) if isinstance(u, dict)]


# --- the provisional registry (t-2181 PC-3, §2.2): `provisional[]` and `tests[].provisional` -------------------------
#
# Everything a test ASSUMES rather than observed. `manifest_provisional` is the one reader of both fields (AR-13); like
# `story_sides` it never raises: a row it cannot read is skipped and NAMED in the return value (FR-41), and an absent
# field reads as `[]` (AR-23) - manifests written before the registry existed carry neither field. The home of a row is
# found by its marker, never by `line_hint` (S9), so the marker rule and the hash of the marked line live here too: the
# writer (`manifest_put`) stamps `home_hash` with the same function the settling check will compare it with.
PROVISIONAL_ID_RE = re.compile(r"^P-\d+$")


def provisional_id(row) -> str:
    """The `id` of a `provisional[]` row as text ("" for a row that is no object): the one extractor the writer
    (`manifest_put`) and the reader (`manifest_provisional`) both call."""
    return str(row.get("id") or "").strip() if isinstance(row, dict) else ""


def provisional_marker_re(pid: str):
    """The comment `qa-provisional: P-n` of one row. `P-1` never matches inside `P-12` (the id ends at a non-word
    character), so a row's marker is exactly its own."""
    return re.compile(r"qa-provisional:\s*" + re.escape(str(pid)) + r"(?![\w-])")


def marked_line_hash(project, file, pid) -> tuple:
    """(sha256 of the marked line, "") or ("", why it could not be hashed). The marked line is the first line of `file`
    (relative to `project`, inside it) that carries the marker of `pid`, WHEREVER it is: an edit above it moves the line and
    changes nothing here (E-P2). The hash is of the line stripped of surrounding whitespace, so re-indenting a moved line is
    not an edit of it; the error direction is "not matched", never a false match. Never raises."""
    name = str(file or "").strip()
    if not PROVISIONAL_ID_RE.match(str(pid or "")):
        return "", f"{str(pid or '')!r} is not an id of the form P-<n>"   # an empty id would match every marker
    if not name:
        return "", "the row names no home file"
    try:
        root = Path(project).resolve()
        path = (root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(root):
            return "", f"{name} is not a path inside the project"
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError) as exc:
        return "", f"{name} cannot be read ({type(exc).__name__})"
    marker = provisional_marker_re(pid)
    for line in text.splitlines():
        if marker.search(line):
            return hashlib.sha256(line.strip().encode("utf-8")).hexdigest(), ""
    return "", f"{name} holds no line with the marker `qa-provisional: {pid}`"


FIRST_LOOK_REF_RE = re.compile(r"^first_look:R-\d+$")
PROVISIONAL_SETTLED = ("settled_matched", "settled_edited")     # the two statuses of a row whose placeholder was settled by a run


def first_look_row(row) -> bool:
    """The accounting row of joint plan J-C5 (t-2277): a `placeholder_locator` that stands for an element the first look saw missing.
    THE one predicate of it (AR-13): the S5 exit (`s5_precheck`) and the ledger (`ledger._placeholder_reading`) both call it. A row
    that is no object is none."""
    return (isinstance(row, dict) and str(row.get("kind") or "") == "placeholder_locator"
            and bool(FIRST_LOOK_REF_RE.match(str(row.get("assumed_from") or "").strip())))


def manifest_provisional(manifest) -> dict:
    """{"rows": [the `provisional[]` rows], "by_test": {instance id: [P-n]}, "skipped": [sentences]}.

    `rows`: every dict row with an id of the form `P-<n>`, first row of an id wins. `by_test`: EVERY `tests[]` instance of the
    manifest is a key; its value is the P-n of its `provisional` field, `[]` when it has none (absent reads empty). A field
    that is not a list, a row that is no object, an id that is not `P-<n>` and a repeated id are skipped and named in
    `skipped`; nothing here judges whether a P-n names a row or whether a kind is known (the checks of the S5 exit)."""
    rows, skipped, seen = [], [], set()
    body = manifest if isinstance(manifest, dict) else {}
    raw = body.get("provisional")
    if raw is not None and not isinstance(raw, list):
        skipped.append(f"`provisional` is {type(raw).__name__}, not a list")
    for at, row in enumerate(raw if isinstance(raw, list) else []):
        pid = provisional_id(row)
        if not isinstance(row, dict):
            skipped.append(f"provisional[{at}] is not an object")
        elif not PROVISIONAL_ID_RE.match(pid):
            skipped.append(f"provisional[{at}] has the id {pid!r}, which is not of the form P-<n>")
        elif pid in seen:
            skipped.append(f"provisional[{at}] repeats the id {pid}")
        else:
            seen.add(pid)
            rows.append(row)
    by_test: dict = {}
    for entry in manifest_tests(body):
        iid = test_instance_id(entry)
        if not iid:
            continue
        ids = by_test.setdefault(iid, [])
        value = entry.get("provisional")
        if value is not None and not isinstance(value, list):
            skipped.append(f"tests[] {iid}: `provisional` is {type(value).__name__}, not a list")
            continue
        for item in value or []:
            if isinstance(item, str) and PROVISIONAL_ID_RE.match(item.strip()):
                if item.strip() not in ids:
                    ids.append(item.strip())
            else:
                skipped.append(f"tests[] {iid}: `provisional` holds {item!r}, which is not of the form P-<n>")
    return {"rows": rows, "by_test": by_test, "skipped": skipped}


def canonical_parameters(value) -> dict:
    """A deterministic parameter map; collection/display ordering has no identity role."""
    if not isinstance(value, dict):
        return {}
    return {str(k): value[k] for k in sorted(value, key=lambda key: str(key))}


INSTANCE_SEP = "::"
_FUNCTION_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def function_name(value: str) -> str:
    """The test function out of whatever spelling names it: a pytest node id, a dotted
    C# name, a bare function, or a selector that already carries `[parameters]`."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split("[", 1)[0]
    for separator in (INSTANCE_SEP, "/", "\\", "#"):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    if "." in text and " " not in text:
        text = text.rsplit(".", 1)[-1]
    return text.strip()


# The old private spelling, kept because a project pinned to an older build imports it.
_function_name = function_name


def instance_parameter(value) -> str:
    """The parameter part of an instance id: a pytest param id, or a canonical k=v join."""
    if value is None:
        return ""
    if isinstance(value, dict):
        canonical = canonical_parameters(value)
        return ",".join(f"{k}={canonical[k]}" for k in canonical)
    return str(value).strip().strip("[]")


def instance_id(test_function: str, param: str | None = None) -> str:
    """THE definition of "one test" — `test_validate_per_partition[missing-assistant]`.

    identity used to be a hash of the mutable `selector` string, so splitting one
    parametrized test into per-partition instances ADDED four manifest rows instead of
    replacing one, and the automator repaired `automation-manifest.json` by hand. A name a
    person can read is also a name a person can check: the manifest, `stage-scope`, the stage
    guard, RunRequests and `then_bindings` all spell an instance the same way here.

    0.7.7 prefixed the id with ONE case, which made the identity of a test the name of a
    single case and pushed the automator to write one test per case. A case is a
    coverage specification, not a test method: the cases an instance proves are `covers` /
    `case_version_links` on its manifest entry, and one instance may prove three of them.
    Ids written with the prefix stay readable — `instance_id_aliases` matches them.
    """
    function = function_name(test_function)
    suffix = instance_parameter(param)
    return f"{function}[{suffix}]" if function and suffix else function


def instance_case(instance, covers=()) -> str:
    """The case an instance belongs to, or `""` — never raises, never guesses.

    The first case the instance COVERS, because a consolidated test has no single owning
    case any more; falling back to the legacy `TC-012::` prefix so an id a 0.7.7 manifest
    wrote still answers. `instance` may be an id or the manifest entry itself.
    """
    if isinstance(instance, dict):
        covers = covers or manifest_test_links(instance)
        instance = test_instance_id(instance)
    for case in covers or ():
        if str(case or "").strip():
            return str(case).strip()
    text = str(instance or "")
    return text.split(INSTANCE_SEP, 1)[0].strip() if INSTANCE_SEP in text else ""


_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def instance_file_stem(instance_id: str) -> str:
    """A file name for an instance id. `::` is legal in JSON and illegal on Windows.

    An id is an identity, not a path: `TC-012::test_x[eu]` names a test everywhere in the
    artifacts and `TC-012--test_x--eu` names the file that holds its receipt. Two ids that
    sanitise to the same stem get a short hash of the FULL id appended, so the mapping stays
    one-to-one. Readers accept the old spelling too — files written before 0.7.7 keep theirs.
    """
    text = str(instance_id or "").strip()
    if not text:
        return "instance"
    stem = _UNSAFE_NAME_RE.sub("--", text.replace(INSTANCE_SEP, "--")).strip("-.") or "instance"
    stem = stem[:120]
    if stem != text:
        stem += "-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return stem


def legacy_test_instance_id(entry: dict) -> str:
    """The 0.7.x selector-hash identity, kept so a manifest written before 0.7.7 still
    matches its own run blocks instead of growing a duplicate row beside them.

    When the entry carries none of the legacy identity fields the hash is computed from the CASE
    alone (`legacy_case`), which makes it the same for every instance of that case —
    `legacy_identity_is_the_case` answers that, and `instance_id_aliases` leaves such a hash out
    rather than handing readers a case identity dressed as an instance one."""
    if not isinstance(entry, dict):
        return ""
    identity = {
        "repository_id": entry.get("repository_id") or entry.get("repo") or "",
        "profile_id": entry.get("profile_id") or entry.get("profile") or "",
        "test": entry.get("test") or "",
        "selector": entry.get("selector") or entry.get("marker") or "",
        "parameters": canonical_parameters(entry.get("parameters") or entry.get("parameter_map")),
    }
    if not any(identity.values()):
        identity["legacy_case"] = str(entry.get("case") or "")
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "ti_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def test_instance_id(entry: dict) -> str:
    """Stable identity for one executable test/profile/parameter combination.

    Explicit IDs win to support imported records.  The derived form intentionally omits
    case links beyond the owning case: one instance may prove many case versions and
    changing that relationship must not create a different execution history.
    """
    if not isinstance(entry, dict):
        return ""
    explicit = str(entry.get("instance_id") or entry.get("test_instance_id") or "").strip()
    if explicit:
        return explicit
    function = function_name(entry.get("test_function") or entry.get("function")
                             or entry.get("test") or entry.get("selector") or entry.get("marker"))
    if function and _FUNCTION_RE.fullmatch(function):
        parameter = entry.get("parameter")
        if parameter is None:
            parameter = entry.get("parameters") or entry.get("parameter_map")
        derived = instance_id(function, parameter)
        if derived:
            return derived
    identity = {
        "repository_id": entry.get("repository_id") or entry.get("repo") or "",
        "profile_id": entry.get("profile_id") or entry.get("profile") or "",
        "test": entry.get("test") or "",
        "selector": entry.get("selector") or entry.get("marker") or "",
        "parameters": canonical_parameters(entry.get("parameters") or entry.get("parameter_map")),
    }
    # Legacy manifests did not have test identity.  Retain the old case key only for
    # those entries, rather than treating it as the identity of new records.
    if not any(identity.values()):
        identity["legacy_case"] = str(entry.get("case") or "")
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "ti_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def legacy_identity_is_the_case(entry: dict) -> bool:
    """True when the legacy hash cannot tell two instances of one case apart.

    It then names the CASE while wearing an instance's name: the same value for every instance of
    that case. Useless as an alias and dangerous as one — two parameterized tests of one case read
    as two spellings of a single row, and `manifest_put._retract_aliases` collapses them and drops
    the evidence of one. Found by the FR-40 walk on 28.09: `test_a[x]` and `test_a[y]` of one case
    hashed alike, and retracting the second took the first with it.

    What distinguishes instances of one case in those legacy fields is `test`, `parameters`, or a
    `selector` that is something other than the case's own marker. `repository_id` and
    `profile_id` are facts about the run, and a `marker` is the case id — every instance of the
    case carries the same one.
    """
    if not isinstance(entry, dict):
        return True
    selector = str(entry.get("selector") or entry.get("marker") or "").strip()
    case = str(entry.get("case") or "").strip()
    return not any((entry.get("test") or "",
                    canonical_parameters(entry.get("parameters") or entry.get("parameter_map")),
                    selector and selector != case))


def instance_id_aliases(entry: dict, cfg=None) -> list:
    """Every spelling ONE instance answers to, canonical first. A loop over many entries passes
    the `cfg` it resolved once (`case_config`): each call otherwise stats the config (B-013).

    A manifest written by 0.7.7 spells the same test `TC-012::test_x[eu]` and a fragment
    written after 0.7.7 spells it `test_x[eu]`; a manifest written by 0.7.4 carries the
    selector hash. All three name the same row, so a merge that only knew the canonical one
    would add a second row beside the first instead of replacing it — the very failure that
    made the automator repair `automation-manifest.json` by hand on TP1-15045.
    """
    if not isinstance(entry, dict):
        return []
    canonical = test_instance_id(entry)
    out = [canonical] if canonical else []
    bare = canonical.split(INSTANCE_SEP, 1)[-1] if INSTANCE_SEP in canonical else canonical
    # A hash identity has no case prefix to strip and no function to prefix: prefixing it
    # would invent `TC-1::ti_ab…`, a name nothing has ever written.
    if bare.startswith("ti_"):
        bare = ""
    for case in manifest_test_links(entry, cfg):
        prefixed = f"{case}{INSTANCE_SEP}{bare}" if case and bare else ""
        if prefixed and prefixed not in out:
            out.append(prefixed)
    if bare and bare not in out:
        out.append(bare)
    # The legacy hash is an alias only when it was computed from this instance's own identity.
    # Computed from the case alone it is the same for every instance of that case, and a reader
    # that treats it as an alias merges two different tests into one row.
    legacy = "" if legacy_identity_is_the_case(entry) else legacy_test_instance_id(entry)
    if legacy and legacy not in out:
        out.append(legacy)
    return out


def manifest_test_links(entry: dict, cfg=None) -> list:
    """The cases one instance proves — `covers[]`, the pinned `case_version_links[]`, or the
    former singular ``case``. `covers` is the plain list a person reads; the pinned links are
    the same relationship with a version on each case, and neither replaces the other."""
    if not isinstance(entry, dict):
        return []
    cfg = _cfg_of(None, cfg)
    links = list(entry.get("covers") or []) + list(
        entry.get("case_version_links") or entry.get("case_links") or entry.get("cases") or [])
    out = []
    if isinstance(links, list):
        for link in links:
            value = link.get("case_id") if isinstance(link, dict) else link
            for case in case_ids(value, cfg=cfg):
                if case not in out:
                    out.append(case)
    for case in case_ids(entry.get("case"), cfg=cfg):
        if case not in out:
            out.append(case)
    return out


def manifest_test_keys(entry: dict, cfg=None) -> list:
    """The same cases as `manifest_test_links`, each with its area when a writer knew one.

    `manifest_test_links` keeps answering in bare ids on purpose: every reader that matches a
    manifest row against a scope, a ledger cell or a result row spells cases the way 0.7.x did,
    and a `covers: ["speakers/TC-001"]` still reads there as `TC-001`. Merging is the one place
    where the area has to survive — two areas holding TC-001..008 lost two approved entries on
    recovery because the merge could not tell them apart (FB-2428-1)."""
    if not isinstance(entry, dict):
        return []
    cfg = _cfg_of(None, cfg)
    entry_area = str(entry.get("area") or "").strip()
    links = list(entry.get("covers") or []) + list(
        entry.get("case_version_links") or entry.get("case_links") or entry.get("cases") or [])
    out: list = []
    for link in [*links, entry.get("case")]:
        value, area = link, entry_area
        if isinstance(link, dict):
            value, area = link.get("case_id"), (str(link.get("area") or "").strip() or entry_area)
        for key in _case_keys(value, area, cfg=cfg):
            if key and key not in out:
                out.append(key)
    return out


def entries_for_case(entries, case, cfg=None) -> list:
    """The manifest entries that answer one ASKED case — the one predicate, in the asker's own spelling.

    A qualified ask (`feedback-api/TC-003`: `split_case_key` finds an area) matches an entry whose
    `manifest_test_keys` hold that key; a bare ask (`TC-003`) matches an entry whose
    `manifest_test_links` hold it, as 0.7.x rows and bare scopes always did. Order is the entries'.
    An empty ask answers nothing and an entry that is not a dict is skipped.

    TP2-2406 S5-5 and S5-6 (FB-19, 19.10.2026): the dispatch scope kept the area
    (`TC-001, TC-002, TC-004, feedback-api/TC-003`) while every reader compared it with the BARE
    links, so the row `covers: ["feedback-api/TC-003"]` answered nobody - `--mine` refused it (t-042,
    fixed in `execution_request`) and `s5_precheck` then reported OB-3 unbound although the binding
    named the instance exactly (t-044). This is the matcher alone: no ambiguity rule, no case-store
    gate, no raise - the strict path of `execution_request._entries_of_case` keeps those, and every
    other reader gets today's non-strict answer (a bare ask over a number two areas hold returns
    both rows).

    This is the other side of `scope_keys` (which see - the map's ONE rule for which scope keys a
    manifest CELL answers to, `docs/SIBLING_MAP.md`): `scope_keys` goes from a cell to the keys it
    answers, this goes from an asked case to the entries that answer it, and the two are
    deliberately NOT the same relation, and it differs on three inputs: a bare ask `TC-009` against
    a cell `speakers/TC-009` (`scope_keys`: no, an area key answers its exact text only; here: yes,
    the bare links of a row are what a 0.7.x scope compares); a compound cell
    `TC-001/TC-002/TC-003` against an ask `TC-001` (`scope_keys`: yes, its window lists the ids
    separately; here: no, `manifest_test_keys` keeps the compound whole); a qualified ask
    `speakers/TC-009` against an entry `{case: TC-009, area: speakers}` (`scope_keys` of the cell
    text: no; here: yes, `manifest_test_keys` joins the area field). A qualified ask is also STRICTER
    than `case_matches`: a bare row never answers it here (the case-store gate of the strict caller
    decides that compatibility). The convergence of the two rules is CX2-17's, not this reader's.
    A qualified ask is compared in the spelling `split_case_key` yields (the backslash form
    `feedback-api\\TC-003` reads as `feedback-api/TC-003`, as every other reader of the key does)."""
    asked = str(case or "").strip()
    if not asked:
        return []
    cfg = _cfg_of(None, cfg)
    area, tail = split_case_key(asked, cfg=cfg)
    if area:
        asked = f"{area}{CASE_KEY_SEP}{tail}"
    read = manifest_test_keys if area else manifest_test_links
    return [entry for entry in entries or [] if isinstance(entry, dict) and asked in read(entry, cfg)]


def manifest_instance_links(manifest: dict, cfg=None) -> dict:
    """instance id -> the case ids that instance proves, for every manifest test."""
    cfg = _cfg_of(None, cfg)
    links: dict = {}
    for entry in manifest_tests(manifest):
        links.setdefault(test_instance_id(entry), set()).update(manifest_test_links(entry, cfg))
    return links


def superseding_terminal_result(report: dict, manifest: dict, cases=(), instance_ids=(), cfg=None) -> dict:
    """The current terminal result that makes an environment block for these identities
    stale — `{}` when nothing does.

    An environment block states that at THAT moment the stand could not answer. A later
    attempt of the SAME instance that did run answers it, and from then on the block is
    history, not the story's final state. Until 0.7.5 nothing could clear one: a stale
    `blocked_by_env` in the manifest short-circuited the ledger before any result was read,
    so a green re-run of that very instance still reached gate B as `env_blocked` and only a
    role rewriting the manifest could undo it (0.6.0 feedback on TP2-2530, item 2).
    Identity is the one identity function, `test_instance_id`, never a name match.
    """
    wanted = {str(value) for value in instance_ids if value}
    wanted_cases = {str(value) for value in cases if value}
    cfg = _cfg_of(None, cfg)
    links = manifest_instance_links(manifest, cfg)
    for instance, linked in links.items():
        if wanted_cases & linked:
            wanted.add(instance)
    for instance, row in current_instance_results(report).items():
        if row.get("stale") or result_status(row) not in TERMINAL_RESULT_STATUSES:
            continue
        if instance in wanted or (wanted_cases & (set(case_ids(row.get("case"), cfg=cfg)) | links.get(instance, set()))):
            return row
    return {}


def unresolved_reason_ok(reason: str) -> bool:
    r = str(reason or "")
    return r in UNRESOLVED_REASONS or r.startswith(UNRESOLVED_DECIDED_PREFIX + ":")


def unresolved_decided(reason: str) -> bool:
    return str(reason or "").startswith(UNRESOLVED_DECIDED_PREFIX)


# --- run-report.json ----------------------------------------------------------------------------

# One row of run-report.json `results[]` has been written two ways: `{test, result}` (what
# artifact-contract-json.md said) and `{test_id, status}` (what the dashboard read, and what
# run_suite.py emits). Both are accepted here and `test_id`/`status` is canonical from 0.3.0 —
# the disagreement is why TP2-2290 showed nine rows with no name and a "?" status.
RESULT_ALIASES = {"pass": "passed", "fail": "failed", "failure": "failed", "error": "error",
                  "skip": "skipped", "skipped": "skipped", "not run": "not_run"}


def result_id(row: dict) -> str:
    """The row's test identity, whichever spelling it was written in."""
    if not isinstance(row, dict):
        return ""
    return str(row.get("test_id") or row.get("test") or "").strip()


def result_status(row: dict) -> str:
    """The row's status, normalized into RESULT_STATUS. Empty string = none recorded."""
    if not isinstance(row, dict):
        return ""
    raw = str(row.get("status") or row.get("result") or "").strip().lower()
    return RESULT_ALIASES.get(raw, raw)


def case_ids(value, artifacts=None, cfg=None) -> list:
    """Every case id named in one cell, in order, without repeats.

    An id is any form the project records (`config.case_id_form`, e.g. `TP1-13877_TC_001`)
    or the default `TC-NNN`; `artifacts` names the story whose project decides, and None is the
    process's own project — outside any project, the default form only (B-013). A loop passes
    `cfg=case_config(artifacts)` resolved once instead of `artifacts` on every call.

    A cell holding one id is the contract (`check_result_rows` rejects anything else on
    write). This reads a compound one — `"TC-001/TC-002/TC-003"`, written on TP1-14501
    for three cases chained into a single test — because `ledger.py` matches by exact
    equality and such a cell matched nothing at all: three green tests reached gate B as
    `not_executed`."""
    return case_forms.ids_in(value, _cfg_of(artifacts, cfg))


def scope_keys(value, artifacts=None, cfg=None) -> list:
    """The scope keys one manifest cell answers to: what a window (or a dispatch scope) may call this cell.

    A second question next to `case_ids`, not a replacement: `case_ids` says which cases a cell NAMES
    (the ledger and `check_result_rows` match by it and are unchanged); this says which KEY the
    controller holds for it. The controller's scope keys are exact (`speakers/TC-009`, `window_record`
    writes them as they stand), and `case_ids('speakers/TC-009')` is `['TC-009']`: a stray check that
    compared the two refused every area-keyed case with no instance.

    The cell is read once, whole and trimmed, and the rule is:
      - the exact text is ALWAYS a key (`speakers/TC-009` -> `['speakers/TC-009']`, `TC-009` -> `['TC-009']`);
      - a COMPOUND of ids only - every `/`-separated part is an id form per `case_ids`'s own rule
        (`TC-001/TC-002/TC-003`, written on TP1-14501) - answers to the exact text AND to each bare id,
        because its window lists TC-001, TC-002 and TC-003 separately;
      - anything else with a `/` is an AREA key (`speakers/TC-009`, `a/b/TC-1`, `speakers/`): the exact
        text only, never a bare id - a bare id would also match another area's case.
    That is the ambiguity it resolves: `speakers/TC-009` and `TC-001/TC-002` have the same shape, and
    only the form of the parts tells an area from a compound. An empty or None cell has no key: `[]`.

    `artifacts` / `cfg` are `case_ids`'s: the project's own id form (`TP1-13877_TC_001`) counts as an
    id, and outside any project (`cfg` None, no story) only the default `TC-NNN` does - so
    `TP1-13877_TC_001/TP1-13877_TC_002` is an AREA key there, not a compound."""
    text = value.strip() if isinstance(value, str) else str(value or "").strip()
    if not text:
        return []
    forms = _cfg_of(artifacts, cfg)
    parts = text.split("/")
    if all(case_forms.is_id(part, forms) for part in parts):
        return list(dict.fromkeys([text, *parts]))
    return [text]


def product_result_rows(report: dict) -> list:
    """Execution rows that may contribute to product outcome.

    Review and red-probe evidence stay in the report but are explicitly excluded from
    product counters.  Raw statuses are preserved on each returned row.  A `diagnostic` or
    `flaky_diagnostic` run (a preflight, S7's isolated reruns of one test) is kept the same way: it
    is evidence about the harness or one failure, never a product outcome, and until it was excluded
    here a diagnostic row joined the manifest like a product row (FB-43).  Only those two purposes
    are added: a row can leave the product set only to "not run", never to "passed" (FR-18).
    """
    rows = []
    for row in report.get("results") or []:
        if not isinstance(row, dict):
            continue
        if row.get("evidence_phase") == "baseline" or row.get("red_probe") or row.get("is_red_probe") or str(row.get("purpose") or "").lower() in {"diagnostic", "flaky_diagnostic", "red_probe", "review_probe", "sensitivity_probe"}:
            continue
        rows.append(row)
    return rows


def instance_results(report: dict) -> dict:
    """instance id -> all product result rows, never a last-write-wins projection."""
    out: dict = {}
    for row in product_result_rows(report):
        key = str(row.get("instance_id") or row.get("test_instance_id") or "").strip()
        if not key:
            key = test_instance_id(row)
        out.setdefault(key, []).append(row)
    return out


def current_instance_results(report: dict) -> dict:
    """Current product row per TestInstance, retaining history in ``instance_results``.

    A later targeted repair supersedes an earlier outcome for the same instance; a row
    marked stale never becomes current merely because it was appended later.  Explicit
    flaky-series markers remain partial so a final pass cannot erase that diagnosis.
    """
    authoritative = report.get("current_results")
    if isinstance(authoritative, list):
        # B-310 (a), F-7: a dict comprehension let the LATER row of a colliding key overwrite the earlier one, so a red
        # row could vanish behind a green one. A `test_id`-only row (no instance_id, test or selector) has the same
        # computed identity as any other such row of its case (`test_id` is not part of the identity), so collisions
        # are real there. The later row is re-keyed - `<key>|<test_id>` when that is free, else `<key>#<n>` - and no
        # key that did not collide changes (a real story reads as it did: B-310 found 0 collisions in 482 rows).
        out: dict = {}
        for row in authoritative:
            if not isinstance(row, dict):
                continue
            key = str(row.get("instance_id") or test_instance_id(row))
            if key in out:
                rid = result_id(row)
                alt = f"{key}|{rid}" if rid else ""
                if not alt or alt in out:
                    n = 2
                    while f"{key}#{n}" in out:
                        n += 1
                    alt = f"{key}#{n}"
                key = alt
            out[key] = row
        return out
    current = {}
    for identity, rows in instance_results(report).items():
        usable = [row for row in rows if not row.get("stale")]
        if not usable:
            continue
        latest = usable[-1]
        if (result_status(latest) in {"passed", "pass"}
                and any(row.get("flaky") or row.get("flaky_series") for row in usable)):
            latest = dict(latest, status="partial", current_reason="flaky_series")
        current[identity] = latest
    return current


# HF3-7 (M3): the ONE vocabulary of a run word the contract and its readers know - the result statuses, their aliases, the
# `partial` a flaky series or a rollup makes, and the two words a manual check or a blocked run may carry. A word outside it
# has no producer (the run-report validator refuses it) and reads "not executed, the run recorded <word>" everywhere:
# `rollup_status` below keeps it from folding into `partial`, `ledger._unknown_run_word` classifies by it (AR-1, AR-13).
RUN_WORDS_KNOWN = frozenset(RESULT_STATUS) | frozenset(RESULT_ALIASES) | frozenset(RESULT_ALIASES.values()) | {
    "partial", "inconclusive", "blocked"}


RUN_WORD_JOIN = ", "   # HF4-3: joins the unknown words of one rollup; no word of RUN_WORDS_KNOWN contains it, so the join stays unknown


def rollup_words(word) -> list:
    """HF4-3 (AR-13): the ONE reader of a `rollup_status` value as a list of words, for PRINTING and de-duplication only.
    A string value is split at `RUN_WORD_JOIN`, parts stripped, empty parts dropped; a non-string or empty value is `[]`.
    A single word that itself contains the join string (`passed, failed`) is split too - the error direction is text only:
    classification (`ledger._unknown_run_word`) always reads the WHOLE value, never these parts."""
    if not isinstance(word, str):
        return []
    return [part for part in (p.strip() for p in word.split(RUN_WORD_JOIN)) if part]


def rollup_status(statuses: list) -> str:
    """Conservative projection of several attempts/instances for legacy consumers: per-instance projection; Then outcomes
    are read from then_bindings by ledger and traceability. A case that one failed instance and one passed instance
    both cover rolls up to `failed` HERE, and `ledger.plan_row_state` / `traceability.then_outcome` decide, from the
    Then bindings, whether that red belongs to the case or to a neighbour that shares the test (HF2-3). The body is not
    the place to decide it (pinned by test_ledger).

    HF3-7: a word outside `RUN_WORDS_KNOWN` (one no runner writes and the validator refuses) is NOT a failure here. With a failed or error instance beside it the red stays (never hidden); beside
    passed instances only it is returned AS IT STANDS, not folded into `partial` - the reader then says "not executed,
    the run recorded <word>" (B3): a half-known case never reads as a half-green one."""
    vals = [result_status({"status": value}) for value in statuses if value]
    if not vals:
        return ""
    if any(v == "failed" for v in vals):
        return "failed"
    if any(v == "error" for v in vals):
        return "error"
    verified = {"passed", "pass"}
    unknown = [v for v in vals if v not in RUN_WORDS_KNOWN]
    if unknown and all(v in verified or v in unknown for v in vals):
        # HF4-3: every unknown word, once, in first-seen order; a blank word is not a word (all blank -> "", no result)
        return RUN_WORD_JOIN.join(dict.fromkeys(v for v in unknown if v))
    if any(v in verified for v in vals) and any(v not in verified for v in vals):
        return "partial"
    if all(v in verified for v in vals):
        return "passed"
    if len(set(vals)) > 1:
        return "partial"
    return vals[-1]


def _link_values(entry: dict) -> list:
    """The raw cells `manifest_test_links` reads the cases of (`covers[]` and the pinned links), area spelling kept."""
    links = list(entry.get("covers") or []) + list(
        entry.get("case_version_links") or entry.get("case_links") or entry.get("cases") or [])
    return [link.get("case_id") if isinstance(link, dict) else link for link in links]


def run_results(report: dict, cfg=None) -> dict:
    """Legacy test/case -> conservative status projection.

    New consumers use ``instance_results`` and retain every row.  This compatibility
    view deliberately returns ``partial`` for pass+skip instead of hiding a required
    unverified parameter behind whichever result was written last.
    """
    cfg = _cfg_of(None, cfg)
    grouped: dict = {}
    for row in current_instance_results(report).values():
        status = result_status(row)
        # `case_version_links` as well as `case`: Since 0.7.7 an instance id spells no case,
        # so a consolidated result row's only statement about TC-004 is its links, and a
        # projection reading `case` alone would report that case as never executed.
        # D2-B3 (E-B3, AR-13, AR-28): the bare id an AREA row names is an ALIAS and a bare key matches any area, so it is
        # NOT stored (the red of `api/TC-4` would read as the result of `web/TC-4`); readers go through `case_lookup`. A source
        # that names no area (a bare row, a compound cell) keeps its plain key as before.
        area_of = {}
        for source in (row.get("case"), *_link_values(row)):
            ids = case_ids(source, cfg=cfg)
            area = _split_case_key(source, cfg)[0] if len(ids) == 1 else ""
            for one in ids:
                area_of.setdefault(one, area)
        keys = (*case_ids(row.get("case"), cfg=cfg), row.get("case"), result_id(row), *manifest_test_links(row, cfg),
                *(v for v in _link_values(row) if v and _split_case_key(v, cfg)[0]))      # a link that spells its area stays a key
        for key in keys:
            if not key:
                continue
            key = str(key)
            if area_of.get(key):
                continue        # the bare id of an AREA row is no key at all (D2-B3, Lead Q1 a): readers go through `case_lookup`
            grouped.setdefault(key, []).append(status)
    current_manual = {}
    for row in (report.get("current_manual_checks") if isinstance(report.get("current_manual_checks"), list)
                else report.get("manual_checks") or []):
        if isinstance(row, dict) and row.get("case"):
            current_manual[str(row["case"])] = row
    for case, row in current_manual.items():
        grouped.setdefault(case, []).append(str(row.get("result") or ""))
    return {key: rollup_status(values) for key, values in grouped.items()}


def case_lookup(mapping, case, cfg=None, rollup: bool = True, exact_wins: bool = True):
    """RD1-2 (AR-15): the ONE lookup of a case in a mapping whose keys mix spellings (`run_results`, `run_impossible`:
    `TC-002` and `web/TC-002` side by side). An exact key wins; otherwise every key that names this case by
    `case_matches` (the identity match: a bare id on either side matches any area, two different areas never match) is
    read, and with `rollup` their values are rolled up by `rollup_status` - a red stays red, a green alias never hides
    it (E-B2). `rollup=False` (a mapping of reasons, not run words) returns the first matching value. No match: None.
    A blank case or a blank key matches nothing - two blanks are not one case (E-B1). The error direction is the
    matcher's own documented generosity (bare id <-> area key); `TC-1` vs `TC-10` and `web/TC-7` vs `api/TC-7` stay
    unmatched.

    `exact_wins=False` (D2-B3 Q2, where RESULTS are judged): the exact key does not short-cut the roll-up, so a bare row
    `TC-4: passed` beside red area rows reads red (E-B2: a green never hides a red). The default is unchanged."""
    text = str(case or "").strip()
    if not text or not isinstance(mapping, dict):
        return None
    if exact_wins and text in mapping:
        return mapping[text]
    cfg = _cfg_of(None, cfg)
    hits = [value for key, value in mapping.items()
            if str(key or "").strip() and _case_matches(key, text, "", cfg)]
    if not hits:
        return None
    return rollup_status(hits) if rollup else hits[0]


def names_case(keys, case, cfg=None) -> bool:
    """F3 t-1753 (AR-13, AR-15): does ANY of `keys` (a set, a list or the keys of a dict) name `case` by the identity match
    `case_matches`? The ONE predicate behind every "is this case among these keys" read (the links of a manifest row, a
    handed or stricter set, the world's gaps, a report's accounted lanes, a gap's cases): a bare id matches any area, two
    different areas never match, `TC-1` is not `TC-10`. A blank case, or a blank key, names nothing (E-B1); an empty
    `cfg` is resolved per call (E-B5). The match is `case_lookup`'s, so no second matcher exists."""
    return case_lookup(dict.fromkeys(keys or (), True), case, cfg or None, rollup=False) is not None


def run_impossible(report: dict) -> dict:
    out = {}
    for row in report.get("impossible") or []:
        if isinstance(row, dict) and row.get("case"):
            out[str(row["case"])] = str(row.get("reason") or "")
    return out


def manual_human_evidence(report: dict) -> dict:
    """Cases handed to the human whole: the runner never executes them, but S6 must still
    record the evidence package that was handed over."""
    out = {}
    for row in report.get("manual_human") or []:
        if isinstance(row, dict) and row.get("case"):
            out[str(row["case"])] = str(row.get("evidence") or "")
    return out


# --- triage.json ------------------------------------------------------------------------------

def triage_rows(triage: dict) -> list:
    return [t for t in (triage.get("triage") or []) if isinstance(t, dict)]


# t-323 F4: `triage_by_test` / `triage_by_instance_attempt` are gone - every reader binds through `bind_triage`.

def id_spellings(value) -> set:
    """Every spelling one test id answers to: itself, and - when it ends in a `[param]` group - itself without
    that group, stripped ONCE from the LAST `[` (`a::b[x][y]` -> `a::b[x]`). The id the analyst writes
    (`..[chromium]`) and the id the run report keeps (no suffix) are the same failure (t-309, cmp2r: five triage
    rows archived as "not bound to current failure"). An empty or non-string id has no spelling - it never
    matches anything. A case id has no `[` and stands for itself."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return set()
    out = {text}
    cut = text.rfind("[")
    if cut > 0 and text.endswith("]") and text[:cut].strip():
        out.add(text[:cut].strip())
    return out


def row_names(row) -> list:
    """The names a triage row answers to: its instance id and its test, else - a manual check has neither - its
    case. A case id does NOT stand for the instances of that case: one case named would otherwise cover several
    rows nobody named. ONE reading for every site that matches a triage row to a failure (t-319: `handoff_check`,
    `finalize_task`, `check_delivery` each had a copy). A row that is not an object has no name."""
    if not isinstance(row, dict):
        return []
    names = [str(row.get(key)).strip() for key in ("instance_id", "test") if str(row.get(key) or "").strip()]
    if not names and str(row.get("case") or "").strip():
        names = [str(row["case"]).strip()]
    return names


def same_id(a, b) -> bool:
    """Two ids name the same failure when they are equal, or one is the other without its `[param]` group
    (`id_spellings`: the analyst writes `..[chromium]`, the run report keeps no suffix). ONE side is widened,
    never both: `x[json]` and `x[multi]` share the base `x` and are two failures, so a row `x[multi]` is NOT the
    verdict of a failure `x[json]`. INVARIANT: a failure nobody triaged is never called triaged, so a stale row of
    a sibling never keeps (`finalize_task.refresh`), never covers (`handoff_check`) and never binds
    (`check_delivery`, `ledger`) a failure it did not name. Error direction: a refusal to match costs the role one
    corrected id; a match too wide hides a failure. Not ids -> False: an empty or non-string id matches nothing,
    not even another empty one."""
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    a, b = a.strip(), b.strip()
    return bool(a and b) and (a == b or b in id_spellings(a) or a in id_spellings(b))


def triage_targets(report) -> dict:
    """The ONE definition of "a failure that needs triage", read from a run report (t-309).

    Three places had their own (`finalize_task.refresh`: manual `failed`/`error` only; `story_run.
    failures_to_triage`: manual `fail`/`inconclusive` only; `handoff_check`: ids by instance/test/case), so a
    manual `inconclusive` was a failure to the driver and not to the reducer, which archived its triage row.
    Here: a `current_results` row whose status is failed/error, and a `current_manual_checks` row (legacy
    `manual_checks` when the current list is absent or empty) whose result is fail/failed/error/inconclusive.
    Returns sets of strings (and one list):
      `all`      every spelling (`id_spellings` of instance_id, test_instance_id, test_id, test, case) of every
                 such failure - what a triage row is matched against by the WIDE reading (kept for callers that
                 only ask "is this id a failure's"; a row is matched to a failure through `names` and `same_id`);
      `names`    one list per failure (a failing result row, a failing manual check): every raw name it carries,
                 in order - the per-failure matching unit of `same_id` (t-319: the union of spellings let a stale
                 row of a sibling `x[multi]` stand for the failure `x[json]`). A RESULT failure's names are its
                 instance / test ids only - a result row with none of them is `unnamed`, whatever `case` it
                 carries; a manual check keeps its `case` (t-323 A1: `bind_triage` below is the one binding that
                 reads them);
      `results`  one name per failing result row, `manual` one per failing manual check (for a sentence);
      `unnamed`  a note for each failing result row or manual check that carries no name at all - it is a
                 failure with no id, never silently dropped (t-319: results had no such note, so a nameless
                 failed row was no failure to `reduce`, which HEAD had counted); `unnamed_manual` is the subset
                 of those notes that belong to manual checks.
      `observations` (P26, RN1-10) one `<case>#obs<n>` per entry of a manual check's `observations[]` (n from 1, in the record's
                 order), WHATEVER the check's own result - a green check keeps its doubts (E7); a check with observations and no
                 name is a note in `unnamed`. Not part of `all` / `names`: `triage_failures` turns each into a failure of the
                 kind `observation`, which `bind_triage` binds like any other (a row naming `<case>#obs<n>`). Also (t-1765 X8-3, AR-22,
                 AR-27) one `<case>#sur-<id>` per entry of the check's `surprises[]` that no observation cites with `"surprise": "<id>"`,
                 the first `surprise.max_per_attempt` of them, and ONE `<case>#sur-overflow` for the rest (`_surprise_split`); a check
                 with no `surprises` yields what it did before. Code lists the lines; whether one is a bug is the analyst's (AR-29).
    A manual check with no `case` and no `instance_id` is named by its `test` when it has one. A report with
    no `current_results` LIST (a legacy one with `results[]`) is read through `current_instance_results`, the
    contract's own projection; a `current_results` list, even an empty one, always wins over the legacy
    `results[]` (an empty current view is "everything repaired", never "fall back to the history"). A report
    that is not an object, or a list of checks that is not a list, yields empty sets (the caller's own shape
    check says so); a row that is not an object is ignored."""
    out = {"all": set(), "results": set(), "manual": set(), "unnamed": set(), "unnamed_manual": set(),
           "names": [], "observations": set()}
    if not isinstance(report, dict):
        return out
    results = report.get("current_results")
    if not isinstance(results, list):
        results = list(current_instance_results(report).values())
    for index, row in enumerate(results):
        if not isinstance(row, dict) or result_status(row) not in ("failed", "error"):
            continue
        # t-323 A1 (critic t-322 probe 2) + BL-2 (critic t-327): the names a triage row is matched against are the
        # instance / test ids and NOTHING else. A case id stands for every automated failure of the case, so a row
        # `{case: C1}` would answer `t::a` and `t::b` both; and a failed result row that carries only a `case` has no
        # name a row could answer to - it is a failure with no id (fail-closed: S7 and gate B refuse it through
        # `unnamed`), never a failure named by its case.
        names = [str(row.get(key) or "").strip() for key in ("instance_id", "test_instance_id", "test_id", "test")]
        names = [name for name in names if name]
        if not names:
            out["unnamed"].add(f"failed result row #{index + 1} has no instance_id, test_instance_id, test_id or test")
            continue
        out["results"].add(names[0])
        out["names"].append(names)
        for name in names:
            out["all"] |= id_spellings(name)
    manual = report.get("current_manual_checks") or report.get("manual_checks")
    for index, row in enumerate(manual if isinstance(manual, list) else []):
        if not isinstance(row, dict):
            continue
        # F5 (S7): an unprepared walk has no result and is still a target - what it observed is the analyst's call (P26, FR-22)
        failing = result_status({"status": row.get("result") or row.get("status")}) in (
            "failed", "error", "inconclusive")
        failing = failing or row.get("unprepared") is not None
        names = [str(row.get(key) or "").strip() for key in ("case", "instance_id", "test")]
        names = [name for name in names if name]
        # P26 / RN1-10: what the runner doubted at ANY step is a target of triage beside a red Then, whatever the check's own
        # result (a green check with an observation keeps it, E7): `<case>#obs<n>`, n from 1 in the record's `observations[]`.
        # A check with observations and no name is a note (an observation is never silently dropped), unless it already is one.
        found = row.get("observations")
        found = [n for n, entry in enumerate(found, 1) if isinstance(entry, dict)] if isinstance(found, list) else []
        # t-1765 X8-3: a surprise line of the recorder that no observation cites is a target of its own, `<case>#sur-<id>` (at most
        # `surprise.max_per_attempt` of them; the rest are ONE `<case>#sur-overflow`) - a cited line is judged inside its observation
        shown, extra = _surprise_split(row)
        sur = [f"#sur-{one['id']}" for one in shown] + (["#sur-overflow"] if extra else [])
        if (found or sur) and names:
            out["observations"] |= {f"{names[0]}#obs{n}" for n in found} | {f"{names[0]}{tail}" for tail in sur}
        elif (found or sur) and not failing:
            note = f"manual check #{index + 1} has observations or surprises and no case, instance_id or test"
            out["unnamed"].add(note)
            out["unnamed_manual"].add(note)
        if not failing:
            continue
        if not names:
            note = f"manual check #{index + 1} has no case, instance_id or test"
            out["unnamed"].add(note)
            out["unnamed_manual"].add(note)
            continue
        out["manual"].add(names[0])
        out["names"].append(names)
        for name in names:
            out["all"] |= id_spellings(name)
    return out


def triage_failures(report) -> tuple:
    """`({(kind, name): {"names": [...], "attempts": {...}}}, [notes])` - every failure that needs a verdict, as
    `triage_targets` reads it, ready for `bind_triage` (t-323 A1: moved here from `check_delivery`, so every reader
    binds the same units).
    `kind` is `result`, `manual` or `observation` (P26: one per `<case>#obs<n>` of a manual check, whatever its result, and, X8-3,
    one per uncited surprise line `<case>#sur-<id>` plus the `<case>#sur-overflow` of the lines past the cap);
    `name` is the failure's first name; `names` every name a row may answer it by
    (merged over the rows that share the key); `ids` the subset the EXACT step of `bind_triage` reads - a result
    failure's instance_id / test_instance_id / test_id, never its `test` (t-323 F7: two siblings `x[json]` and
    `x[multi]` that both carry the base `test: x` were both bound EXACTLY by a row naming that base), a manual
    check's names whole (its `case` matching is untouched); `attempts` the attempt ids of its result rows and of its
    manual records (CD2; `""` when a row or record names none - such a failure answers any row's attempt); `old` the subset of `attempts` that is NOT the latest attempt
    the report records for that instance (its `results[]` history; t-323 F3: a row with no attempt never answers an
    old one). The notes are the failures that carry no name a row could answer to - a failed result row with only a
    `case` is one of them, and two such rows are two notes (their indices differ), never one failure. Each row is
    read ALONE through `triage_targets`, so a failure keeps its own name and attempt. A report with no
    `current_results` list (a legacy `results[]` one) is read through `current_instance_results`, so its failures
    are never invisible. A report that is not an object has no failures."""
    if not isinstance(report, dict):
        return {}, []
    if not isinstance(report.get("current_results"), list):
        report = dict(report, current_results=list(current_instance_results(report).values()))
    failures: dict = {}
    history = instance_results(report)

    def add(kind: str, names: list, ids: list, attempt: str, old: bool = False) -> None:
        got = failures.setdefault((kind, names[0]), {"names": [], "ids": [], "attempts": set(), "old": set()})
        got["names"] += [name for name in names if name not in got["names"]]
        got["ids"] += [name for name in ids if name not in got["ids"]]
        got["attempts"].add(attempt)
        if old:
            got["old"].add(attempt)

    for row in report["current_results"]:
        for names in triage_targets({"current_results": [row]})["names"]:
            attempt = str(row.get("attempt_id") or "").strip()
            ident = str(row.get("instance_id") or row.get("test_instance_id") or "").strip() or test_instance_id(row)
            recorded = [r for r in history.get(ident, []) if isinstance(r, dict) and not r.get("stale")]
            latest = str(recorded[-1].get("attempt_id") or "").strip() if recorded else ""
            # t-323 F7: the instance ids alone - a result row's `test` is the base its siblings share, so the EXACT
            # step of `bind_triage` never binds by it
            ids = [str(row.get(key) or "").strip() for key in ("instance_id", "test_instance_id", "test_id")]
            add("result", names, [i for i in ids if i], attempt, old=bool(attempt and latest and attempt != latest))
    manual = report.get("current_manual_checks") or report.get("manual_checks")
    for row in manual if isinstance(manual, list) else []:
        for names in triage_targets({"current_manual_checks": [row]})["names"]:
            # CD2: a manual record carries the attempt it was checked in (`manual_evidence` writes
            # `attempt_id`), and that attempt travels with the failure so a triage row written for an
            # OLDER attempt of the same case never answers the current one. A record with no attempt
            # keeps answering any row, as before. Two current records of one case in different attempts
            # share one key: a row of either answers it, a row of a third attempt does not.
            add("manual", names, names, str(row.get("attempt_id") or "").strip())
        # P26 / RN1-10 (AR-28): what the runner doubted is a target of triage beside a red Then, whatever its check's result - an
        # unanswered observation never passes. Kind `observation`, name `<case>#obs<n>`, the record's attempt (CD2, as above).
        # A report with no observation yields exactly the failures it did before.
        # (t-1765 X8-3: the same kind holds `<case>#sur-<id>` and `<case>#sur-overflow`; `target_parts` is the one reading of the name)
        for name in sorted(triage_targets({"current_manual_checks": [row]})["observations"], key=_target_order):
            add("observation", [name], [name], str(row.get("attempt_id") or "").strip())
    return failures, sorted(triage_targets(report)["unnamed"])


def _attempt_fits(failure: dict, row: dict) -> bool:
    """A row of another attempt never answers a failure: its `attempt_id` must be one the failure has, unless the
    failure's own attempt is not recorded. A row with NO attempt answers a failure only when one of the failure's
    attempts is the latest the report records for its instance (t-323 F3: a legacy row stays valid for the current
    failure and never answers an older attempt). A manual check is held to the same rule (CD2): its failure carries
    the attempt of the manual record, so a row naming another attempt does not answer it; a row naming no attempt
    does (a manual check records no `old` attempts).

    R7 (t-1508, AR-22): a row may CARRY attempts - `carried_attempts: [<attempt id>]`, written by `s7_reorder.py finish` when
    a `reorder` round moved the asserts of a test and its repair run stayed red. Such a row answers a failure of the NEW
    attempt too, but only through an attempt id the failure itself has (a carried id of another instance is not among its
    attempts): the row's own `attempt_id` evidence is kept, nothing is stripped. A row without the list binds exactly as
    before."""
    said = str(row.get("attempt_id") or "").strip()
    if said:
        if "" in failure["attempts"] or said in failure["attempts"]:
            return True
        carried = row.get("carried_attempts")
        return isinstance(carried, list) and any(
            isinstance(one, str) and one.strip() and one.strip() in failure["attempts"] for one in carried)
    return not failure["attempts"] or bool(failure["attempts"] - failure.get("old", set()))


def bind_triage(failures: dict, rows: list) -> dict:
    """THE ONE binding of triage rows to failures (t-323 A1, critic t-322 B1): S7's null outcome
    (`handoff_check`), gate B (`check_delivery`), the reducer's keep/archive (`finalize_task.refresh`), the ledger,
    the traceability table and the dashboard all read it - before it each had its own ladder over the same two
    predicates and the three probes of t-322 got three different answers.

    `failures` is `triage_failures`' first value. Returns `{"matched": {failure key: [rows]}, "ambiguous":
    [(row names, [failure keys])], "ambiguous_rows": [the same rows, as given], "multiple": {result failure key:
    [rows]}}` - `multiple` is the ONE class "more than one row answers one result failure" (t-323 F1: S7 and gate B
    both refuse it, "N rows answer <failure>; keep one"; `matched` still holds the rows). INVARIANT: a failure nobody
    named is never bound, and one row is never the verdict of two failures it did not name exactly. Error direction: a refusal to bind costs the analyst one
    corrected id; a bind too wide hides a failure. Rules, per row, in this order:
      (1) EXACT: the row binds to every failure one of whose instance ids (`ids`) is one of its names verbatim
          (`row_names`: its instance_id / test - its `case` only when it has neither), and to no other - so a row
          `x[json]` never also covers a failure `x`, a `case` row never covers an automated failure that has
          instance ids, and a result row's base `test` never binds (t-323 F7: siblings sharing `test: x`);
      (2) NEAR: a row with no exact failure binds to the ONE failure that shares a spelling with it (`same_id`: the
          analyst's `x[chromium]` answers the run report's `x`, and the reverse);
      (3) AMBIGUOUS: a row that shares a spelling with TWO failures or more (`x` over `x[json]` and `x[multi]`) binds
          to none of them and is returned in `ambiguous`, never silently dropped.
    The attempt rule is everyone's: a row of another attempt than the failure's never binds (`_attempt_fits`); of
    several rows bound to one failure, those that name its attempt come first. An empty `rows` binds nothing; a row
    that is not an object, or names nothing, binds nothing."""
    matched: dict = {key: [] for key in failures}
    ambiguous: list = []
    ambiguous_rows: list = []
    for row in rows if isinstance(rows, list) else []:
        names = row_names(row)
        if not names:
            continue
        near = [key for key, failure in failures.items() if _attempt_fits(failure, row)
                and any(same_id(n, f) for n in names for f in failure["names"])]
        exact = [key for key in near if any(n == f for n in names for f in failures[key].get("ids", failures[key]["names"]))]
        if exact or len(near) == 1:
            for key in exact or near:
                matched[key].append(row)
        elif near:
            ambiguous.append((names, near))
            ambiguous_rows.append(row)
    for key, bound in matched.items():
        named = [r for r in bound if str(r.get("attempt_id") or "").strip() in failures[key]["attempts"]]
        matched[key] = named or bound
    multiple = {key: rows_ for key, rows_ in matched.items() if key[0] == "result" and len(rows_) > 1}
    return {"matched": matched, "ambiguous": ambiguous, "ambiguous_rows": ambiguous_rows, "multiple": multiple}


OBSERVATION_TARGET_RE = re.compile(
    r"^(?P<case>.+)#(?:obs(?P<n>[1-9][0-9]*)|sur-(?P<overflow>overflow)|sur-(?P<sid>[A-Za-z0-9][A-Za-z0-9._-]*-S[1-9][0-9]*))$")
SURPRISE_CAP_FALLBACK = 30      # only when `manual-capture-steps.json` cannot be read; its `surprise.max_per_attempt` is the number


def target_parts(name):
    """The ONE reading of the name of a manual check's target of triage (AR-13): `(case, kind, key)`, or None when `name` is none.
    `<case>#obs<n>` -> `(case, "obs", n)` (n an int); `<case>#sur-<id>` -> `(case, "sur", id)` (id as the recorder writes it,
    `a2-ui-S3`); `<case>#sur-overflow` -> `(case, "sur-overflow", "")`. Every reader of such a name asks this function
    (`is_observation_target`, `observation_entry`, the order of `triage_failures`); no other place splits it (X8-3, F-4). A case
    name that holds `#` is read whole: the suffix is the last `#...` that matches. Pure, never raises."""
    found = OBSERVATION_TARGET_RE.match(name.strip()) if isinstance(name, str) else None
    if not found:
        return None
    if found["n"]:
        return found["case"], "obs", int(found["n"])
    return (found["case"], "sur-overflow", "") if found["overflow"] else (found["case"], "sur", found["sid"])


def is_observation_target(name) -> bool:
    """`<case>#obs<n>`, `<case>#sur-<id>` or `<case>#sur-overflow` - the names `triage_targets` gives what a manual check's runner
    doubted or the recorder surprised it with (P26, RN1-10; t-1765 X8-3)."""
    return target_parts(name) is not None


def _target_order(name) -> tuple:
    """The order of targets of one case in `triage_failures`: observations by number, then surprise lines in the order the recorder
    wrote them (`S2` before `S10`), then the overflow target."""
    case, kind, key = target_parts(name) or (str(name), "", "")
    if kind == "obs":
        return case, 0, "", key
    if kind == "sur":
        prefix, _, number = key.rpartition("-S")
        return case, 1, prefix, int(number or 0)
    return case, 2, "", 0


def _surprise_cap() -> int:
    """`surprise.max_per_attempt` of `manual-capture-steps.json` - the number is data (AR-1); the fallback holds only for an
    install whose file cannot be read."""
    try:
        import manual_capture as MC
        return max(1, int(MC.spec()["surprise"]["max_per_attempt"]))
    except Exception:
        return SURPRISE_CAP_FALLBACK


def _surprise_split(row) -> tuple:
    """`(shown, extra)` of one manual check: the entries of its `surprises[]` that no observation cites (`observations[].surprise`),
    in the record's order - `shown` the first `_surprise_cap()` of them (each is a target of its own), `extra` the rest (ONE
    `#sur-overflow` target). An entry that is no object, has no id, or repeats an id already listed counts for nothing; a record
    with no `surprises` yields `([], [])`. A cited line is judged inside its observation; citing an id the record does not hold
    cites nothing (the id is no line). Pure, never raises."""
    if not isinstance(row, dict) or not isinstance(row.get("surprises"), list):
        return [], []
    cited = {str(one.get("surprise")).strip() for one in row.get("observations") or []
             if isinstance(one, dict) and isinstance(one.get("surprise"), str)}
    seen, loose = set(), []
    for one in row["surprises"]:
        ident = str(one.get("id") or "").strip() if isinstance(one, dict) else ""
        if ident and ident not in seen and ident not in cited:
            loose.append(one)
        seen.add(ident)
    cap = _surprise_cap()
    return loose[:cap], loose[cap:]


def _overflow_words(extra) -> str:
    """The words of the `#sur-overflow` target: how many lines it stands for and the first five ids (the lines themselves are in the
    record's `surprises[]`)."""
    ids = [str(one.get("id")) for one in extra]
    return f"{len(ids)} more surprises: {', '.join(ids[:5])}" + (", ..." if len(ids) > 5 else "")


def observation_duplicates(rows, report=None) -> dict:
    """`{<case>#obs<n>: [rows]}` for every observation answered by MORE than one triage row - the ONE rule of "one row per
    observation" (AR-13), attempt-aware like the binder (t-1747 F5). With a `report` it is `bind_triage`'s own binding of the
    observation failures (a row of another attempt than the observation's answers nothing, so a stale row of attempt a1 never
    competes with the analyst's row of a2); without one the rows are grouped by name AND `attempt_id` (the nearest reading,
    never a name alone). Rows are the objects of `rows`; never raises."""
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if isinstance(report, dict):
        bound = bind_triage(triage_failures(report)[0], rows)["matched"]
        return {name: found for (kind, name), found in bound.items() if kind == "observation" and len(found) > 1}
    grouped: dict = {}
    for row in rows:
        for name in row_names(row):
            if is_observation_target(name):
                grouped.setdefault((name, str(row.get("attempt_id") or "").strip()), []).append(row)
    out: dict = {}
    for (name, _attempt), found in grouped.items():
        if len(found) > 1:
            out.setdefault(name, []).extend(found)
    return out


QUOTED_WORDS_RE =re.compile(r'"([^"]+)"|“([^”]+)”|«([^»]+)»|`([^`]+)`')


def quoted_words(reason) -> list:
    """The words inside quotation marks of `reason`: `"..."`, curly double quotes, guillemets or backticks. The ASCII apostrophe
    and the curly single quotes are NOT quotation marks here - they are the apostrophe of a contraction (`it's`, `the app's`)
    and a pair of them would let a reason with no quote at all pass (t-1747 F3, AR-28). A mark that opens and is never closed
    quotes nothing."""
    return [next(g for g in m.groups() if g is not None).strip() for m in QUOTED_WORDS_RE.finditer(str(reason or ""))
            if any(g is not None and g.strip() for g in m.groups())]


def surprise_line(entry) -> str:
    """The words of one `surprises[]` entry of a record, as a target of triage shows them: `surprise: <id> step <n> <kind>: <fact>`
    (the recorder's own line, `manual_capture._surprise_line`, holds the step's word in parentheses before the kind: an entry that
    carries `word` gives that exact line, one built before `word` the form without it). The text a `NO_DEFECT` on that target
    quotes from (X8-3, F-13)."""
    word = entry.get("word")
    if isinstance(word, str) and word.strip():
        import manual_capture as MC
        return MC._surprise_line({"id": entry.get("id"), "step": entry.get("step"), "word": word, "kind": entry.get("kind"),
                                  "fact": entry.get("fact")})
    return f"surprise: {entry.get('id')} step {entry.get('step')} {entry.get('kind')}: {entry.get('fact')}"


def observation_entry(report, name, attempt="") -> dict | None:
    """The recorded observation `<case>#obs<n>` of a run report (`current_manual_checks[]` row named `<case>`, entry n of its
    `observations[]`), else None. Two records of one case: the one of `attempt` wins. For `<case>#sur-<id>` the entry is made from the
    record's `surprises[]` line: `{step, expected: "", seen: <fact>, evidence: "", quote: <the line>}` - there is NO evidence capture, so a
    `NO_DEFECT` quote must stand in THAT line (a word of the file's other lines is not it, F-13); `<case>#sur-overflow` stands for the
    uncited lines past the cap: its quote is the overflowed lines (`surprise_line` each) and its `seen` the counter words `_overflow_words`, which are no quote. A line the record does not hold (or one an observation cites: it is
    no target) gives None. Pure, never raises."""
    parts = target_parts(name)
    manual = report.get("current_manual_checks") or report.get("manual_checks") if isinstance(report, dict) else None
    if parts is None or not isinstance(manual, list):
        return None
    case, kind, key = parts
    found = []
    for row in manual:
        if not isinstance(row, dict):
            continue
        names = [str(row.get(field) or "").strip() for field in ("case", "instance_id", "test")]
        names = [n for n in names if n]
        if not names or names[0] != case:
            continue
        said = str(row.get("attempt_id") or "").strip()
        if kind == "obs":
            index = key - 1
            if isinstance(row.get("observations"), list) and 0 <= index < len(row["observations"]) \
                    and isinstance(row["observations"][index], dict):
                found.append((said, row["observations"][index]))
            continue
        shown, extra = _surprise_split(row)
        if kind == "sur":
            line = next((one for one in shown if str(one.get("id")).strip() == key), None)
            if line is not None:
                found.append((said, {"step": line.get("step"), "expected": "", "seen": str(line.get("fact") or ""),
                                     "evidence": "", "quote": surprise_line(line)}))
        elif extra:
            found.append((said, {"step": extra[0].get("step"), "expected": "", "seen": _overflow_words(extra), "evidence": "",
                                 "quote": "\n".join(surprise_line(one) for one in extra)}))
    for said, entry in found:
        if attempt and said == attempt:
            return entry
    return found[0][1] if found else None


def _counter_words(words, entry) -> bool:
    """True when `words` stand inside the counter words of an overflow entry (`seen`): code's own count, not a fact of a hidden line."""
    try:
        import manual_evidence as ME
        wanted = ME._squash(words)
        return bool(wanted) and wanted in ME._squash(str(entry.get("seen") or ""))
    except (ImportError, AttributeError):
        return False


def _quote_is_recorded(words, entry, task_root) -> bool:
    """True when `words` stand in the evidence the observation `entry` recorded: its verified `quote`, or the text of its
    `evidence` capture read by the ONE verified-quote reader (`manual_evidence._quote_in`, AR-13). Error direction: a failure to
    read the capture is a quote not found."""
    try:
        import manual_evidence as ME
        wanted = ME._squash(words)
        if wanted and wanted in ME._squash(str(entry.get("quote") or "")):
            return True
        evidence = str(entry.get("evidence") or "").strip()
        return bool(task_root is not None and evidence and ME._quote_in(Path(task_root).resolve(), {"path": evidence}, words))
    except (ImportError, OSError, ValueError, AttributeError):
        return False


def triage_no_defect_problems(row, report=None, task_root=None) -> list:
    """The problems of one triage row of the verdict `NO_DEFECT` (P26), `[]` when there are none; a row of another verdict is not
    judged here. THE one reader (AR-13): the delivery check and the triage validator ask it. The row must name an observation
    target and ONLY observation targets (every name of `row_names` is one of `target_parts`: `<case>#obs<n>`, `<case>#sur-<id>` or
    `<case>#sur-overflow` - a row that also names a red test is a Then's verdict, which this word is not for) - on a Then target the
    word is refused with the existing words as the door - and carry a `reason` (`triage_reason`) with quoted words (`quoted_words`: a
    quotation mark pair, never an apostrophe). The judgment of the words is the analyst's (FR-12, FR-47), but with a `report` the
    quoted words must STAND in the target's recorded evidence (`_quote_is_recorded`: for an observation its `quote` and its `evidence`
    capture; for a surprise target its OWN line only, X8-3); without one only the form is checked. Pure, never raises."""
    if not isinstance(row, dict) or row.get("verdict") != "NO_DEFECT":
        return []
    names = row_names(row)
    if not names or not all(is_observation_target(name) for name in names):
        bad = next((n for n in names if not is_observation_target(n)), None)
        return [f"verdict NO_DEFECT is for an observation of a manual check (`<case>#obs<n>`) or a surprise of the recorder "
                f"(`<case>#sur-<id>`) and nothing else, and the row names "
                f"{bad or 'no target'}: a failed Then is judged with APP_BUG, TEST_BUG, ENV_ISSUE, FLAKY, "
                "APP_CHANGED, CASE_DEFECT or ASSERT_STRICTER - change the verdict, or name only the observation or the surprise"]
    reason = triage_reason(row)
    words = quoted_words(reason)
    if not words:
        return ["verdict NO_DEFECT needs a `reason` that quotes the recorded evidence of the observation (the words in "
                "double quotes, copied from its capture; an apostrophe is not a quote): write the row again with the quote, "
                "or give another verdict (`APP_BUG` when the observation shows a defect)"]
    entry = observation_entry(report, names[0], str(row.get("attempt_id") or "").strip()) if report is not None else None
    if entry is not None and (target_parts(names[0]) or ("", "", ""))[1] == "sur-overflow":
        words = [w for w in words if not _counter_words(w, entry)]           # code's own counter words are no evidence (M-1)
    if entry is not None and not any(_quote_is_recorded(w, entry, task_root) for w in words):
        if (target_parts(names[0]) or ("", "", ""))[1] == "sur-overflow":
            return [f"verdict NO_DEFECT: no quoted word of the `reason` stands in a fact of the lines {names[0]} stands for (the count "
                    f"\"{entry.get('seen')}\" is the tool's own, not evidence): quote the words of one of those lines "
                    "(`surprises/NNN-surprises.txt` holds them), or give another verdict (`APP_BUG` when a surprise shows a defect)"]
        if (target_parts(names[0]) or ("", "", ""))[1] != "obs":
            return [f"verdict NO_DEFECT: no quoted word of the `reason` stands in the line of {names[0]} (\"{entry.get('quote')}\"): "
                    "quote that line, not another line of the surprises file, or give another verdict (`APP_BUG` when the "
                    "surprise shows a defect)"]
        return [f"verdict NO_DEFECT: no quoted word of the `reason` stands in the recorded evidence of {names[0]} (its `quote` "
                "and its `evidence` capture): copy the words as the capture holds them, or give another verdict (`APP_BUG` when "
                "the observation shows a defect)"]
    return []


def _drops_param_of(alias: str, own: str) -> bool:
    """`alias` is `own` without its `[param]` group, in any prefix spelling: `t` and `file::t` for `t[json]`. An
    `own` with no `[param]` group drops nothing; `own` never drops itself."""
    cut = [s for s in id_spellings(own) if s != own]
    if not cut or id_spellings(alias) != {alias}:
        return False
    return alias.rsplit("::", 1)[-1] == cut[0].rsplit("::", 1)[-1]


def triage_row_for(failures: dict, rows: list, names: list, attempt: str = "", status: str = "") -> dict | None:
    """The ONE triage row that answers the test `names` stand for, else None - the single-test reading of
    `bind_triage` for the readers that ask about one test (ledger, traceability table, dashboard).

    The test is looked up among `failures` first (exact name, else the one failure it shares a spelling with, the
    attempt rule applying); a test that is no failure of the report (a FLAKY row on a green test, a report-less
    ledger call) is bound as one more failure beside the report's, so a sibling's row is still never its verdict.
    A name that stands for SEVERAL failures (`x` over `x[json]` and `x[multi]`), a row that is ambiguous, and
    several rows for one test all answer None - never the first.
    BL-1 (critic t-327, live on cmp2r: two PASSED instances read `failed:APP_BUG` through their failing sibling
    `[json]` because the manifest's base `test`, no `[param]`, was among the names): (a) a name that is the asked
    instance's OWN id (`names[0]`, the first non-empty name) WITHOUT its `[param]` group is dropped before anything
    is matched - the NEAR step never crosses the `[param]` boundary of the asked instance's own id; `names[0]` itself
    is never dropped, and when it has no `[param]` group nothing is (BL-3, critic's control pass: the rule applied
    between EVERY pair of names dropped the UI test's own id `t` beside the report's `f.py::t[chromium]`, and a
    FLAKY row naming `t` exactly was lost on a green test); (b) a test whose own current result is not failed
    (`status` given and not failed/error) is never moved onto a failure key: it is its own key, so only a row that
    names it can answer it."""
    names = list(dict.fromkeys(n.strip() for n in names if isinstance(n, str) and n.strip()))
    if not names:
        return None
    names = [n for n in names if n == names[0] or not _drops_param_of(n, names[0])]
    attempt = str(attempt or "").strip()
    pool = dict(failures)
    asked = {"names": names, "attempts": {attempt}, "old": set()}
    word = str(status or "").strip().lower()
    own_green = bool(word) and result_status({"status": word}) not in ("failed", "error")
    near = [] if own_green else [
        key for key, failure in failures.items() if key[0] != "manual"
        and (not attempt or "" in failure["attempts"] or attempt in failure["attempts"])
        and any(same_id(n, f) for n in names for f in failure["names"])]
    # t-329 (B-270 a): the EXACT step reads `ids` like `bind_triage`'s own (t-323 F7) - a failure's `names` carry the
    # `test` base its siblings share, so a name that is only that base was "exact" for the one sibling that listed it
    # and the answer picked a sibling nobody named; now it is ambiguous (None), the error direction of this module
    exact = [key for key in near if any(n == f for n in names for f in failures[key].get("ids", failures[key]["names"]))]
    if len(exact or near) > 1:
        return None
    key = (exact or near or [("ask", names[0])])[0]
    if key[0] == "ask":
        pool[key] = asked
    got = bind_triage(pool, rows)["matched"][key]
    return got[0] if len(got) == 1 else None


PROOF_FIELDS = ("instance_id", "case_version", "test_content_hash", "source_revision",
                "build_id", "mutation", "expected_assertion_failure", "actual_failure",
                "assertion_location", "restoration_evidence")


def sensitivity_proof_receipt(entry: dict, artifacts: Path | None = None) -> tuple[dict, list]:
    """Resolve a canonical proof ref, or an evidence-complete legacy inline receipt."""
    proof = entry.get("sensitivity_proof") if isinstance(entry, dict) else None
    if not isinstance(proof, dict):
        return {}, ["sensitivity_proof must be a typed receipt object"]
    ref = proof.get("receipt_ref")
    if ref is None:
        if artifacts is not None:
            state = load_json(Path(artifacts) / "state" / "controller.json")
            if state.get("plan_contract_mode") == "new":
                return {}, ["new-contract sensitivity_proof requires an immutable receipt_ref"]
        return proof, []  # legacy inline receipt; full semantic checks still apply below
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not ref.get("path") or not ref.get("sha256"):
        return {}, ["sensitivity_proof.receipt_ref requires task-relative path and sha256"]
    if artifacts is None:
        return {}, ["sensitivity_proof receipt cannot be verified without the task root"]
    root = Path(artifacts).resolve()
    raw = Path(ref["path"])
    path = (root / raw).resolve() if not raw.is_absolute() else raw
    if raw.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        return {}, ["sensitivity_proof receipt path is missing, absolute or escapes the task"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != ref["sha256"]:
        return {}, ["sensitivity_proof receipt hash does not match"]
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["sensitivity_proof receipt is not valid JSON"]
    return (receipt, []) if isinstance(receipt, dict) else ({}, ["sensitivity_proof receipt must be an object"])


def sensitivity_proof_issues(entry: dict, artifacts: Path | None = None) -> list:
    """Validate a canonical immutable sensitivity receipt referenced by a manifest row."""
    proof, errors = sensitivity_proof_receipt(entry, artifacts)
    if errors:
        return errors
    errors = [f"sensitivity_proof.{key} is required" for key in PROOF_FIELDS if not proof.get(key)]
    if proof.get("instance_id") != test_instance_id(entry):
        errors.append("sensitivity_proof.instance_id does not match the manifest instance")
    versions = {str(link.get("version") or "") for link in entry.get("case_version_links") or []
                if isinstance(link, dict)}
    if versions and str(proof.get("case_version") or "") not in versions:
        errors.append("sensitivity_proof.case_version is not a linked content-addressed version")
    if str(proof.get("case_version") or "") and not str(proof.get("case_version")).startswith("cv_"):
        errors.append("sensitivity_proof.case_version must be content-addressed")
    if proof.get("failure_kind") in {"collection", "import", "setup", "product_bug"}:
        errors.append("sensitivity proof must show the controlled assertion failure")
    if proof.get("immutable") is not True or not proof.get("receipt_hash"):
        errors.append("sensitivity proof must identify an immutable receipt")
    return errors


# --- obligation identity, receipts, reducer supersession, delivery (TP2-2553) --------
#
# One run, four bookkeeping failures that read to the person as product gaps: the plan wrote
# `TS-1-O1` and the manifest `OB-1`, so no obligation ever joined; the red probe wrote the
# receipt into `obligation_bindings[]` while delivery read `tests[].sensitivity_proof`; a
# first run block under a case-shaped instance id left four `partial` ghosts no rerun could
# supersede; and the delivery manifest hashed records the factory itself rewrites afterwards.

# The spelling every manifest of that run used for an obligation nobody had named.
LEGACY_OBLIGATION_RE = re.compile(r"^OB-(\d+)$")

# The reducer's `current_reason` for an unjoined result row that a later terminal attempt of
# the same case answered. It stays in `results[]` for diagnosis and leaves `current_results`.
SUPERSEDED_BY_RERUN = "superseded_by_rerun"

# Compact records the factory rewrites by definition AFTER S8 assembled the delivery
# manifest: acceptance appends events, waivers and the ledger rewrite theirs, a late
# `manifest_put` bumps the manifest. Listed in the manifest as `volatile: true`, checked for
# presence and not for the hash it had the moment somebody happened to run `build`.
DELIVERY_VOLATILE_PATHS = (
    "state/events.jsonl", "work/automation-manifest.json", "work/ledger.json",
    "work/ledger.md", "work/run-report.json", "work/triage.json",
    "work/finalization-receipt.json", "work/waivers.json",
)


def _plan_rows_of(task_root) -> list:
    path = Path(task_root) / WORK_DIR / "test-plan.json"
    if not path.is_file():
        path = Path(task_root) / "test-plan.json"
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    rows = value.get("rows", []) if isinstance(value, dict) else value
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def plan_obligations(task_root) -> list:
    """`[(plan row id, obligation), ...]` in plan order, schema-2 rows only; `[]` for a
    legacy plan, so a story onboarded before coverage obligations existed is never refused
    for an id its plan could not have named."""
    out = []
    for row in _plan_rows_of(task_root):
        if row.get("schema_version", 1) != 2:
            continue
        for ob in row.get("coverage_obligations") or []:
            if isinstance(ob, dict) and ob.get("obligation_id"):
                out.append((str(row.get("id") or ""), ob))
    return out


def plan_obligation_ids(task_root) -> list:
    return list(dict.fromkeys(str(ob["obligation_id"]) for _row, ob in plan_obligations(task_root)))


def unknown_obligation_ids(ids, task_root) -> list:
    """The ids no obligation of the plan carries, in the order given; `[]` when the plan has
    no schema-2 obligations at all (nothing to join, nothing to refuse)."""
    known = set(plan_obligation_ids(task_root))
    if not known:
        return []
    return [str(i) for i in dict.fromkeys(str(i) for i in ids or []) if str(i) not in known]


def legacy_obligation_map(task_root) -> dict:
    """`OB-n` -> the n-th obligation id of the plan (1-based, plan order) — the only reading
    under which the `OB-1..OB-9` bindings of TP2-2553 name anything. An `OB-n` beyond
    the plan's count maps to nothing and is left for a person."""
    ids = plan_obligation_ids(task_root)
    return {f"OB-{index + 1}": oid for index, oid in enumerate(ids)
            if not LEGACY_OBLIGATION_RE.match(oid)}


def binding_receipt_ref(manifest: dict, entry: dict, artifacts) -> dict:
    """`{"path", "sha256", "obligation_id"}` from the proven `obligation_bindings[]` row that
    lists this instance (any spelling of its id), the hash taken from the file on disk; `{}`
    when no such binding exists or the receipt file is gone. The probe of TP2-2553
    wrote four such bindings and delivery read none of them.

    One instance can be listed by several bindings. Which one is its receipt (B-313: a stale
    sibling's green-run receipt, listed first, hid the probe receipt of the obligation the
    instance declares): the candidates are filtered as before, then
    - an entry that declares obligations (`obligation_refs[].obligation_id`, `obligation_ids`;
      a legacy `OB-n` on either side is read through `legacy_obligation_map`) gets a candidate
      of one of them: the one at its `sensitivity_proof.receipt_ref.path`, else the first in
      manifest order; when none is of its obligations it gets `{}` — a sibling's proof is not
      this instance's proof (FR-18);
    - an entry that declares none keeps first-wins, so a story written before obligations
      existed still reads its receipt."""
    if not isinstance(manifest, dict) or not isinstance(entry, dict):
        return {}
    aliases = set(instance_id_aliases(entry))
    root = Path(artifacts).resolve() if artifacts is not None else None
    legacy = legacy_obligation_map(artifacts) if artifacts is not None else {}

    def spelled(oid) -> str:
        oid = str(oid or "")
        return legacy.get(oid, oid)

    declared = [ref.get("obligation_id") for ref in entry.get("obligation_refs") or []
                if isinstance(ref, dict)]
    ids = entry.get("obligation_ids")
    declared += list(ids) if isinstance(ids, (list, tuple)) else []
    expected = {spelled(oid) for oid in declared if oid}
    candidates = []
    for binding in manifest.get("obligation_bindings") or []:
        if not isinstance(binding, dict) or binding.get("sensitivity") != "proven":
            continue
        if not aliases & {str(i) for i in binding.get("instance_ids") or []}:
            continue
        raw = str(binding.get("probe_receipt_ref") or "")
        if not raw or root is None or Path(raw).is_absolute():
            continue
        path = (root / raw).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        candidates.append({"path": raw, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "obligation_id": str(binding.get("obligation_id") or "")})
    if not expected:
        return candidates[0] if candidates else {}
    exact = [ref for ref in candidates if spelled(ref["obligation_id"]) in expected]
    if not exact:
        return {}
    proof = entry.get("sensitivity_proof")
    pinned = proof.get("receipt_ref") if isinstance(proof, dict) else None
    proof_path = str(pinned.get("path") or "") if isinstance(pinned, dict) else ""
    return next((ref for ref in exact if proof_path and ref["path"] == proof_path), exact[0])


def with_binding_receipt(entry: dict, manifest: dict, artifacts) -> tuple:
    """The manifest row with `sensitivity_proof.receipt_ref` filled from its obligation
    binding when the row carries none: `(row, obligation_id)`, the id `""` when nothing was
    filled. The caller still runs `sensitivity_proof_issues` on the result — the binding
    names a file, it does not vouch for what is in it."""
    if not isinstance(entry, dict):
        return entry, ""
    proof = entry.get("sensitivity_proof")
    if isinstance(proof, dict) and proof.get("receipt_ref"):
        return entry, ""
    ref = binding_receipt_ref(manifest, entry, artifacts)
    if not ref:
        return entry, ""
    filled = dict(proof) if isinstance(proof, dict) else {}
    filled["receipt_ref"] = {"path": ref["path"], "sha256": ref["sha256"]}
    return dict(entry, sensitivity_proof=filled), ref["obligation_id"]


# --- S5 window record and stage closure (TP2-2553) ---------------------------------------
#
# `acceptance.validate_window` demanded a record no script wrote: the orchestrator learned its
# shape by rejection, one field per refusal, and the critic's last interval ran two hours.
# The shape is stated here once, checked all at once, and `window_record.py` writes it.

WINDOW_FIELDS = ("schema_version", "author_dispatch_id", "reviewer_dispatch_id", "input_hash",
                 "scope_instances", "instances", "required_quality_checks", "quality_receipts")
WINDOW_INSTANCE_FIELDS = ("instance_id", "input_hash", "outcome", "execution_fingerprint",
                          "obligation_refs", "obligation_ids", "obligation_hash", "assertion_id",
                          "defect_location", "change_disposition", "change_basis_ref",
                          "evidence_refs", "review")
# `blocked_by_env` (t-219): the stand stopped the instance before any Then; the same word as the manifest's
# `unresolved[].reason` (FR-10). `acceptance.blocked_instances` decides it; this tuple only says it is a word.
WINDOW_OUTCOMES = ("passed", "failed", "handed_to_person", "blocked_by_env", PENDING_IMPLEMENTATION)

# HF1-14 (EP1-10, TP1-12586): a probe that could not run here, accepted by the person, closes the S5 window as a
# NAMED gap. The unit is a `probe_gap` block on the window item BESIDE `probe` (never inside it: `probe` keeps meaning
# "a proof"); the person's word joins it by the instance's IDENTIFIER (FR-12), through `probe_gap_words`, the ONE reader.
# Downstream the gap is D-0013's `review_unverified` (S8 "Left with you"): nothing there changes.
PROBE_GAP_MATCH_PREFIX = "probe gap:"
PROBE_GAP_VERDICTS = ("not_executed", "incomplete", "not_run")
PROBE_MISSING_ERROR = "probe is missing for a new_or_changed instance"
PROBE_GAP_WHY_LIMIT = 300

# HF2-4 (GW1-23, TP1-12586): a RED instance that a manifest row `contradicts_requirement` explains closes its window
# with that row, not with a probe. A probe cannot be asked of a red test: whether the mutated run fails at the intended
# assert depends on the order of the asserts in the test (F-20), so the window records WHY none is owed. The unit is a
# `probe_not_applicable` block on the window item BESIDE `probe` (never inside it: `probe` keeps meaning "a proof"). The
# writer is `window_record.build`, only for an instance `acceptance.red_by_requirement` names (the one reader of
# red-ness, AR-13), carrying EVERY row that named it; the readers are `window_shape_errors` below (the third way to
# satisfy a new_or_changed instance) and the print of `window_record.run`. `acceptance.validate_window` never trusts the
# block: it re-derives the red from the manifest and the run blocks under the task.
PROBE_NOT_APPLICABLE_KEY = "probe_not_applicable"
PROBE_NOT_APPLICABLE_WHY = ("red",)
PROBE_NOT_APPLICABLE_REASON = "contradicts_requirement"


def probe_gap_words(pipeline) -> dict:
    """{value: {"words", "at"}} — the instances (or cases) whose probe gap the person accepted, from their own words.

    Read from `stage_overrides[]` like every block a person's word passes (`waiver.py --stage S5 --block "probe gap:
    <case key>"`; an instance id works only when it is one token): a live (not revoked) S5 record with non-empty words, whose `match` is the prefix and
    ONE token (`prefix_value`). A word joins an item by IDENTIFIER equality only, case kept: never a substring, never
    `*`, never `not receipted` (FR-12; `waiver.split_overridden` is deliberately NOT this reader: `*` matches
    everything there). Error direction: toward NO entry, which leaves the gap refused. Never raises: a pipeline that
    is no object, a `stage_overrides` that is no list, another stage, a revoked record, empty words and a value that
    is not one token give none."""
    return {value: {"words": " ".join(str(entry.get("decision") or "").split()), "at": str(entry.get("at") or "")}
            for value, entry in stage_override_values(pipeline, PROBE_GAP_MATCH_PREFIX)}


# t-1968 N5: the person's own word about a test whose probe the code reviewer could not judge (`cannot_judge`). A SEPARATE prefix,
# with no `class` (one word never widens), so a `probe gap:` word about tooling never names such a test (the owner's word 05.11.2026).
PROBE_NOT_PROVED_PREFIX = "probe not proved:"


def probe_not_proved_words(pipeline) -> dict:
    """{case key: {"words", "at"}} - the cases whose "not proved" the person accepted, from their own words (t-1968 N5).

    `probe_gap_words`' reading with the prefix `PROBE_NOT_PROVED_PREFIX` (`waiver.py --stage S5 --block "probe not proved: <case key>"`):
    a live S5 record with non-empty words whose `match` is the prefix and ONE token, joined to an item by IDENTIFIER equality only
    (never `*`, never a substring; FR-12). Whether the word is newer than the judgment it answers is the reader's
    (`window_record.not_proved_name`). Error direction: toward NO entry (the person is asked again). Never raises."""
    return {value: {"words": " ".join(str(entry.get("decision") or "").split()), "at": str(entry.get("at") or "")}
            for value, entry in stage_override_values(pipeline, PROBE_NOT_PROVED_PREFIX)}


PROBE_GAP_CLASS = "probe_gap_accepted"                    # the `class` of a record of a `probe gap:` word (`references/block-names.json`)
PROBE_GAP_CLASS_KEY = "class:" + PROBE_GAP_CLASS          # the `named_by` of a window item covered by the class word
PROBE_GAP_TOOLING_PREFIX = "tooling:"                     # the value of a word about one language (`proof_level.TOOLING_GAP_PREFIX` is this one), not a class word


def probe_gap_class_word(pipeline, keys=()) -> dict | None:
    """`{"words", "at", "key"}` - the person's decision about a probe gap, read as the answer for EVERY test of the story whose
    probe the tool could not read (GW1-43), or None. The ONE reader (AR-13) of that class, in the acceptance and in the window.

    The class is in force while the story holds a LIVE S5 record that `waiver.apply_stage_override` marked `class:
    probe_gap_accepted` (the data row of `references/block-names.json` says which blocks carry it; a record written before the
    mark, or with another value, does not). The latest such record by `(at, position)` gives the words; an empty or unreadable
    `at` is the oldest. REVOCATION (FR-40): the word is not applied to an instance when one of its `keys` (its id, its case keys)
    names a revoked `probe gap: <key>` record with no live record of the same key - the person took that word back; one revoked
    record puts out its instance, not the class; a revoke of `*` revokes every record, and so the class. This function only
    reads the word: whether the instance's probe could not run is `proof_level.probe_could_not_run`'s, and the equality of the
    instance's own word (`probe_gap_words`) is asked first by the callers. Error direction: None (the person is asked again).
    Never raises: a pipeline that is no object, no `stage_overrides`, a record that is no object give None."""
    try:
        # a `tooling:<language>` value is a word about ONE language: `proof_level.tooling_gap_key` joins it by equality, so it is
        # never the class word of the whole story (a word about one language does not close another's probe)
        classed = [(_answer_moment(entry.get("at")), position, entry)
                   for position, (value, entry) in enumerate(stage_override_values(pipeline, PROBE_GAP_MATCH_PREFIX))
                   if entry.get("class") == PROBE_GAP_CLASS and not str(value).startswith(PROBE_GAP_TOOLING_PREFIX)]
        if not classed:
            return None
        live = {value for value, _entry in stage_override_values(pipeline, PROBE_GAP_MATCH_PREFIX)}
        named = {str(key) for key in keys or () if str(key or "").strip()}
        for entry in pipeline.get("stage_overrides") or []:
            if isinstance(entry, dict) and entry.get("stage") == "S5" and entry.get("revoked_at"):
                value = prefix_value(entry.get("match"), PROBE_GAP_MATCH_PREFIX)
                if value and value in named and value not in live:
                    return None
        _moment, _position, entry = max(classed, key=lambda row: (row[0], row[1]))
        return {"words": " ".join(str(entry.get("decision") or "").split()), "at": str(entry.get("at") or ""),
                "key": PROBE_GAP_CLASS_KEY}
    except Exception:
        return None


def probe_gap_errors(item) -> list:
    """Why a window item's `probe_gap` block is malformed: one FR-1 sentence per problem, [] when it is well formed
    (or absent). SHAPE only; whether a person's word names the instance is `acceptance.validate_window`'s, which
    reads `probe_gap_words`. `verdict` is one of PROBE_GAP_VERDICTS; `why`, `named_by` and `words` are non-empty
    strings; `record` a string or null; the item RAN GREEN (`outcome: passed`: a word never turns a red or an unrun
    test into a passed window, FR-18) and carries no `probe` beside the block (the two are never both).

    A RED instance therefore never carries a `probe_gap`: the word of a person does not close a red window. What closes
    it is the manifest's `contradicts_requirement` row, recorded as `probe_not_applicable`
    (`probe_not_applicable_errors`, HF2-4); the rule above is unchanged and a red item with a gap is still refused."""
    if not isinstance(item, dict) or "probe_gap" not in item:
        return []
    gap = item.get("probe_gap")
    if not isinstance(gap, dict):
        return ["probe_gap must be an object {verdict, record, why, named_by, words, at}"]
    errors = []
    verdict = gap.get("verdict")
    if not (isinstance(verdict, str) and verdict in PROBE_GAP_VERDICTS):
        errors.append(f"verdict must be one of {', '.join(PROBE_GAP_VERDICTS)}, got {verdict!r}")
    for field in ("why", "named_by", "words"):
        value = gap.get(field)
        if not (isinstance(value, str) and value.strip()):
            errors.append(f"{field} must be a non-empty string")
    record = gap.get("record")
    if record is not None and not isinstance(record, str):
        errors.append(f"record must be a path string or null, got {record!r}")
    if item.get("outcome") != "passed":
        errors.append("a probe gap is carried only by an instance that ran green (outcome passed); "
                      f"this one is {item.get('outcome')!r}")
    if "probe" in item:
        errors.append("probe_gap and probe are both present: an instance has a proof or a named gap, not both")
    return errors


def probe_not_applicable_errors(item) -> list:
    """Why a window item's `probe_not_applicable` block is malformed: one FR-1 sentence per problem, [] when it is well
    formed (or absent). SHAPE only; whether the instance IS red by a manifest row is `acceptance.red_by_requirement`'s,
    asked by `acceptance.validate_window` again over the manifest. The block is
    `{why, reason, rows}`: `why` one of PROBE_NOT_APPLICABLE_WHY, `reason` PROBE_NOT_APPLICABLE_REASON, `rows` a
    NON-EMPTY list of objects each with a non-empty string `case` (the slice keys and `thens` of the row travel beside
    it, as the manifest holds them, and are not judged here). The item RAN RED (`outcome: failed`: a test that passed,
    never ran or was handed over owes its probe or its own gap, FR-18) and carries neither `probe` nor `probe_gap`
    beside the block (the three are never together). Empty outcome (AR-23): no key -> []; an empty `rows` is an error,
    never "nothing to record"."""
    if not isinstance(item, dict) or PROBE_NOT_APPLICABLE_KEY not in item:
        return []
    block = item.get(PROBE_NOT_APPLICABLE_KEY)
    if not isinstance(block, dict):
        return [f"{PROBE_NOT_APPLICABLE_KEY} must be an object {{why, reason, rows}}"]
    errors = []
    if not (isinstance(block.get("why"), str) and block["why"] in PROBE_NOT_APPLICABLE_WHY):
        errors.append(f"why must be one of {', '.join(PROBE_NOT_APPLICABLE_WHY)}, got {block.get('why')!r}")
    if block.get("reason") != PROBE_NOT_APPLICABLE_REASON:
        errors.append(f"reason must be {PROBE_NOT_APPLICABLE_REASON}, got {block.get('reason')!r}")
    rows = block.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows must be a non-empty list: one object {case, ...} for every unresolved[] row that makes "
                      "this instance red (window_record.py writes them from the manifest)")
    else:
        for index, row in enumerate(rows):
            if not (isinstance(row, dict) and isinstance(row.get("case"), str) and row["case"].strip()):
                errors.append(f"rows[{index}] must be an object with a non-empty string `case`")
    if item.get("outcome") != "failed":
        errors.append("a probe_not_applicable block is carried only by an instance that ran red (outcome failed); "
                      f"this one is {item.get('outcome')!r}")
    for other in ("probe", "probe_gap"):
        if other in item:
            errors.append(f"probe_not_applicable and {other} are both present: a red instance closes its window with "
                          "its manifest row, and a proof or a named gap beside it says two things")
    return errors


def window_shape_errors(window) -> list:
    """Every structural gap of an S5 window record in one list — never the first one only.
    Semantic checks (hash binding, probe verdicts, evidence on disk) stay with
    `acceptance.validate_window`; this is the form, so a writer can be told what it forgot."""
    if not isinstance(window, dict):
        return ["window is not an object"]
    errors = [f"{field} is missing" for field in WINDOW_FIELDS if field not in window]
    if window.get("schema_version") not in (None, 1, 2):
        errors.append("schema_version must be 1 or 2")
    scope = window.get("scope_instances")
    # An EMPTY list for one case is not a shape error: a case the manifest carries as
    # `impossible` or `handed_to_person` has no instance to name, and the controller decides
    # that with the manifest and the completion in front of it (FB-10, TP1-13797). This
    # check owns the SHAPE - a map, of lists - and leaves that judgment where it belongs;
    # without this the earlier refusal fires first and the exception can never be reached.
    if "scope_instances" in window and (not isinstance(scope, dict) or not scope
                                        or any(not isinstance(v, list) for v in scope.values())):
        errors.append("scope_instances must map every case of the scope to a list of instance ids "
                      "(empty only for a case the manifest carries as `impossible` or "
                      "`handed_to_person`, and the completion repeats in `unresolved` with a `reason`)")
    for field in ("required_quality_checks", "quality_receipts", "quality_not_run", "instances"):
        if field in window and not isinstance(window.get(field), list):
            errors.append(f"{field} must be a list")
    seen = set()
    for index, item in enumerate(window.get("instances") or []):
        if not isinstance(item, dict):
            errors.append(f"instances[{index}] is not an object")
            continue
        label = str(item.get("instance_id") or f"instances[{index}]")
        if label in seen:
            errors.append(f"{label} appears twice")
        seen.add(label)
        if item.get("schema_version", window.get("schema_version", 1)) == 2:
            missing = [f for f in WINDOW_INSTANCE_FIELDS if f not in item]
        else:
            missing = [f for f in ("instance_id", "input_hash", "outcome", "change_disposition",
                                   "change_basis_ref", "evidence_refs", "review") if f not in item]
        errors.extend(f"{label}: {f} is missing" for f in missing)
        if "outcome" in item and item.get("outcome") not in WINDOW_OUTCOMES:
            errors.append(f"{label}: outcome must be one of {', '.join(WINDOW_OUTCOMES)}")
        if "probe_gap" in item:
            errors.extend(f"{label}: probe_gap: {e}" for e in probe_gap_errors(item))
        if PROBE_NOT_APPLICABLE_KEY in item:
            errors.extend(f"{label}: {PROBE_NOT_APPLICABLE_KEY}: {e}" for e in probe_not_applicable_errors(item))
        elif "probe_gap" not in item and item.get("change_disposition") == "new_or_changed" \
                and item.get("outcome") not in ("handed_to_person", "blocked_by_env", PENDING_IMPLEMENTATION) \
                and "probe" not in item:
            # three ways to satisfy a new_or_changed instance: a probe, a named gap (green only), a red's row
            errors.append(f"{label}: {PROBE_MISSING_ERROR}")
    if scope and isinstance(scope, dict) and isinstance(window.get("instances"), list):
        expected = {str(i) for ids in scope.values() if isinstance(ids, list) for i in ids}
        actual = {str(i.get("instance_id") or "") for i in window["instances"] if isinstance(i, dict)}
        if expected != actual:
            errors.append("instances do not exactly cover scope_instances: missing "
                          + (", ".join(sorted(expected - actual)) or "none") + "; extra "
                          + (", ".join(sorted(actual - expected)) or "none"))
    return errors


def _stage_entry(stage: str, path=None) -> dict:
    """The row of `stage` in `references/stages.json` (`path` names another table, for a test), `{}` when there is none.
    THE private reader of that table for `stage_roles` and `rework_mode` (SIBLING_MAP axis 16: the file goes through
    `hooklib.read_json`, with `kind=dict`). Nothing here raises: a table that is absent or not JSON, whose root is not an
    object, whose `stages` is not a list, a row that is not an object and a stage the table does not name all read as `{}`."""
    from hooklib import read_json   # late, as the other `hooklib` names of this module: `import contract` does not run its stdio setup
    table = Path(path) if path else Path(__file__).resolve().parent.parent / "references" / "stages.json"
    stages = read_json(table, {}, kind=dict).get("stages")
    for entry in stages if isinstance(stages, list) else []:
        if isinstance(entry, dict) and entry.get("id") == stage:
            return entry
    return {}


def stage_roles(stage: str) -> list:
    """The stage's roles in dispatch order, from `references/stages.json`; `[]` for a stage
    that has none (S0) or is not in the model."""
    return [str(r) for r in _stage_entry(stage).get("roles") or []]


REWORK_MODES = ("fresh", "resume")
DEFAULT_REWORK_MODE = "fresh"


def request_agent_id(packet: dict) -> str:
    """The `agent_id` a rework request CAME WITH (the parent's agent, at `resume`), or "". THE one reader of the bind rule: an
    `agent_id` that `bind` set on the dispatch RECORD (it carries `agent_bound_seq`) is the id of a fresh agent the conductor
    launched, not the parent's - it is a bind, not a resume. Error direction: any doubt is "" (fresh), never a resume."""
    if not isinstance(packet, dict) or packet.get("agent_bound_seq") is not None:
        return ""
    return str(packet.get("agent_id") or "").strip()


def rework_mode(stage: str, path=None) -> str:
    """How accepted work of this stage goes back to its role, from the stage's `rework_mode` in
    `references/stages.json` (`path` names another table, for a test): `fresh` is a NEW agent that
    reads only the findings and the lines it needs (a role that grows a big context is not resumed
    for a mechanical repair, B-070), `resume` is `SendMessage` into the dispatch that still holds
    the work, with the delta. THE one reader of the field: the S3 remark line, the refusal of
    `stage_done --status running` and the texts of SKILL.md say "by the stage's rework_mode" and
    carry no rule of their own (AR-1, SC1-1).

    The default, `fresh`, is the answer for: a stage the table does not name, a stage with no `rework_mode`, and a
    table that cannot be used (absent, not JSON, a root that is not an object, `stages` that is not a list, a row that
    is not an object); none of these raises (P1: a reader of data the plugin ships never stops the stage's exit). The
    one exception is deliberate: a `rework_mode` that is neither word raises `ValueError` saying which words are
    expected and where (FR-1), because a typo in the data read as either mode would send a repair the wrong way;
    `stage_done.rework_launch_text` turns that into a sentence."""
    mode = _stage_entry(stage, path).get("rework_mode", DEFAULT_REWORK_MODE)
    if mode not in REWORK_MODES:
        raise ValueError(f"{Path(path).name if path else 'stages.json'}: stage {stage} has rework_mode {mode!r}; expected one of "
                         + ", ".join(REWORK_MODES) + f" (or no key: {DEFAULT_REWORK_MODE})")
    return mode


def stage_closes_with(stage: str, role: str) -> bool:
    """Is this role the last of the stage — the one whose acceptance leaves no role to close
    it? TP2-2553 accepted the S4 critic with `stage_complete: false`, and no operation
    could close S4 afterwards but a duplicate dispatch over unchanged evidence."""
    roles = stage_roles(stage)
    return bool(roles) and roles[-1] == role


# --- evidence references: a refusal names the path, the root and the spelling that works ----
# TP2-2553 section 1: the controller refused an acceptance with the bare words
# "missing or outside-task evidence" — no path, no task root, no hint that the reference was
# absolute — and the orchestrator spent a resume, a retry and two receipts finding out which
# of its five refs was the one. Every check of a {path, sha256} reference against a task root
# goes through this helper so the refusal is one sentence a person can act on.

def evidence_ref_issue(task_root, ref, what: str = "evidence", require_hash: bool = True, under: str = "") -> str:
    """'' when `ref` = {path, sha256} names a file under `task_root` whose hash matches;
    otherwise one sentence naming what is wrong, the path as written, the task root and — for
    an absolute path that does lie under the root — the task-relative spelling that works.
    The hash is checked only when the file is there, so "missing" and "stale" never blur.
    `require_hash=False` (HF2-18: a triage `control.evidence` is a bare path) judges the path alone:
    the same absolute / escapes / not-a-file refusals, no sha256 asked for and none compared.
    `under` (HF2-18, t-1339 F2): a task-relative directory the file must lie in, after symlinks and `..` are resolved -
    the one place that prefix is judged; '' = anywhere under the root, as it always was."""
    root = Path(task_root).resolve()
    if not isinstance(ref, dict):
        return f"{what} reference must be an object with path and sha256 (task root {root})"
    raw_text = str(ref.get("path") or "").strip()
    if not raw_text:
        return f"{what} reference has no path (task root {root})"
    raw = Path(raw_text)
    if raw.is_absolute():
        candidate = raw.resolve()
        if candidate.is_relative_to(root):
            return (f"{what} path {raw_text} is absolute; the task-relative spelling is "
                    f"{candidate.relative_to(root).as_posix()} (task root {root})")
        return f"{what} path {raw_text} is outside the task root {root}"
    path = (root / raw).resolve()
    if not path.is_relative_to(root):
        return f"{what} path {raw_text} escapes the task root {root}"
    if under and not path.is_relative_to((root / under).resolve()):
        return f"{what} path {raw_text} is not under {under}/ of the task root {root}"
    if not path.is_file():
        return f"{what} path {raw_text} is not a file under the task root {root}"
    if not require_hash:
        return ""
    if not ref.get("sha256"):
        return f"{what} path {raw_text} has no sha256 (task root {root})"
    if hashlib.sha256(path.read_bytes()).hexdigest() != str(ref.get("sha256")):
        return f"{what} path {raw_text} has changed since it was referenced (stale sha256, task root {root})"
    return ""


# --- sides of the product and the story held for code (t-2181 PC-1a) ------------------------------------------------
#
# A side is a part of the product a story's checks can meet; its reality words and the default side are DATA
# (`references/side-realities.json`, AR-1), the side NAMES are open (AR-2). `story_sides` is the one reader of the
# story's record of them (AR-13); the registry leg joins it in PC-1b. Every reader here returns a value and never raises:
# a record it cannot read is never read as `real` - the reality of such a side reads as "" (unknown), which no reader
# counts as real (AR-28).
SIDE_REALITIES_PATH = Path(__file__).resolve().parent.parent / "references" / "side-realities.json"
AWAITING_DEFAULT_CAUSE = "s5_absent_side"   # a record written before the cause existed was held for an absent side ...
AWAITING_DEFAULT_HELD_FROM = "S6"           # ... from the first stage after S5
PARKING_REALITY = "absent"                  # the one reality word code acts on (a deliverable absent side parks the story); it must be in the data file's `realities`


def story_sides(pipeline, cfg=None, env_name=None, root=None) -> dict:
    """{side name: {reality, deliverable, settles_by, reference, source}} of the story.

    `pipeline.sides` first - a readable record always wins; an entry's missing `deliverable` reads true, a missing `settles_by`
    reads "" and a missing `reality` reads "" (unknown, never real). Then (t-2181 PC-1b, only when `root` - the project - is given)
    the registry (`registry_sides`): its sides carry `source: registry` and `registry_key`, the key of the row that set them. An
    unreadable registry reads the default side with reality "" (unknown, never real); a malformed side row reads that side unknown.
    Then the default side of `references/side-realities.json` with `source: default`. The data file unreadable as well: {} - no
    side is invented in code. `cfg` is not read here; `env_name` picks the stand whose `environments.sides` rows count."""
    import sys   # late: the note below is the only use
    record = pipeline.get("sides") if isinstance(pipeline, dict) else None
    if isinstance(record, dict) and record:
        return {str(name): _side_row(entry, entry.get("reference") if isinstance(entry, dict) else None,
                                     entry.get("source") if isinstance(entry, dict) else None)
                for name, entry in record.items()}
    default = side_realities().get("default")
    if not isinstance(default, dict) or not default:
        print("sides: references/side-realities.json could not be read; no side is read for the story", file=sys.stderr)
        return {}
    out = {str(name): _side_row(side, None, "default") for name, side in default.items()}
    if root is not None:
        read = registry_sides(root, env_name)
        if read["unreadable"]:
            print("sides: " + read["problem"] + "; the sides read as unknown", file=sys.stderr)
            return {name: {**row, "reality": ""} for name, row in out.items()}
        if read["sides"]:
            if not product_implied(read["sides"]):
                out = {}                                # a real side of this team is named: `product` is not implied (PC2-7)
            for name, row in read["sides"].items():
                out[name] = {**row, "deliverable": True if row["deliverable"] is None else row["deliverable"]}
            return out
    if not isinstance(pipeline, dict):
        print("sides: the story's pipeline.json could not be read; the sides read as the default ("
              + ", ".join(out) + ")", file=sys.stderr)
    return out


def product_implied(sides) -> bool:
    """THE one condition under which the implicit side `product` (real, deliverable, source default) is carried beside a story's sides
    (PC2-7, t-043; the owner's word 12.11.2026): when NO entry of `sides` (`{name: {reality, deliverable, ...}}`, as the registry, the
    launch and the person's answers merge them) is real AND this team's - `deliverable` true or absent (reads true: only `False` is
    another team's). An entry whose reality is empty or missing (unknown) is not real, and neither is an entry
    that is not a dict. It never reads history or provenance. Called by `story_sides`, `Driver.s0_sides_sets` and `Driver.sides_reread`,
    so the three say the same thing (axis 35). Error direction: it decides a name, not a proof - a wrong True adds a name beside sides
    that are all non-real or unknown (their proofs stay `on_substitute`, an unknown side keeps `sides_unknown`), a wrong False leaves
    the real part unnamed (more items left with the person). `product_implied({})` is True; no caller reaches it with no record owed."""
    entries = sides.values() if isinstance(sides, dict) else ()
    return not any(isinstance(entry, dict) and entry.get("reality") == "real" and entry.get("deliverable") is not False
                   for entry in entries)


def registry_sides(root, env_name=None) -> dict:
    """The registry leg of the sides, read ONLY through `project_knowledge.subjects` and `state` (never the file):
    `{"sides": {name: {reality, deliverable (None = no row says), settles_by, reference, source: registry, registry_key}},
    "names": [every side name any row of the three keys holds, all stands], "problem": str, "unreadable": bool}`. `product.sides` rows
    give the project's sides (`reality: real` unless a stand row says otherwise),
    `environments.sides` rows of the stand `env_name` (exact; none when None) give the reality, `environments.reference_for` rows of
    ALL stands give the reference. A side's `registry_key` is the key that set its reality (the stand row), else `product.sides`,
    else `environments.reference_for`. A row that is not of its key's shape or not `known` reads that side with reality ""
    (unknown) and fills `problem`; two stands naming one side's reference do the same. Never raises, never writes."""
    out = {"sides": {}, "names": [], "problem": "", "unreadable": False}
    try:
        import project_knowledge as PK
        words = side_realities().get("realities")
        problems, names = [], set()

        def rows_of(key, environment=None):
            listed = PK.subjects(root, key, environment)
            if listed["problem"]:
                raise LookupError(listed["problem"])
            return [(env, element, PK.state(root, key, env, element)) for env, element in listed["subjects"]]

        def side(name):
            return out["sides"].setdefault(name, {"reality": "real", "deliverable": None, "settles_by": "", "reference": None,
                                                  "source": "registry", "registry_key": None})
        for env, element, got in rows_of(PK.SIDES_KEY):
            names.add(element)
            row, value = got["row"], (got["row"] or {}).get("value")
            entry = side(element)
            if (got["state"] != PK.KNOWN or not isinstance(value, dict) or not isinstance(value.get("deliverable"), bool)
                    or not isinstance(value.get("settles_by", ""), str) or env != "" or _keyless(element)):
                entry["reality"] = ""
                problems.append(f"the row {row and row.get('id')} of {PK.SIDES_KEY} for `{element}` is malformed")
                continue
            entry.update(deliverable=value["deliverable"], settles_by=value.get("settles_by", ""))
            entry["registry_key"] = entry["registry_key"] or PK.SIDES_KEY
        if env_name:
            for env, element, got in rows_of(PK.STAND_SIDES_KEY, str(env_name)):
                names.add(element)
                row, value = got["row"], (got["row"] or {}).get("value")
                entry = side(element)
                if (got["state"] != PK.KNOWN or not isinstance(value, dict) or not isinstance(words, list)
                        or value.get("reality") not in words or _keyless(element)):
                    entry["reality"] = ""
                    problems.append(f"the row {row and row.get('id')} of {PK.STAND_SIDES_KEY} for `{element}` is malformed")
                    continue
                entry["reality"], entry["registry_key"] = value["reality"], PK.STAND_SIDES_KEY
        for env, element, got in rows_of(PK.STAND_SIDES_KEY):
            names.add(element)                          # every stand's names count for the case check (C15)
        stands = {}
        for env, element, got in rows_of(PK.REFERENCE_KEY):
            names.add(element)
            row = got["row"] or {}
            if got["state"] != PK.KNOWN or row.get("value") != {"reference": True} or _keyless(element):
                side(element)["reality"] = ""
                problems.append(f"the row {row.get('id')} of {PK.REFERENCE_KEY} for `{element}` is malformed")
                continue
            stands.setdefault(element, []).append(env)
        for element, held in stands.items():
            entry = side(element)
            if len(held) > 1:
                entry["reality"] = ""
                problems.append(f"`{element}` has more than one reference stand ({', '.join(sorted(held))})")
                continue
            entry["reference"] = held[0]
            entry["registry_key"] = entry["registry_key"] or PK.REFERENCE_KEY
        out["names"] = sorted(names)
        out["problem"] = "; ".join(problems)
        for entry in out["sides"].values():             # a side named by a malformed row alone keeps a key too
            entry["registry_key"] = entry["registry_key"] or PK.SIDES_KEY
    except Exception as exc:    # the registry could not be read at all: never `real` (S12)
        out.update(sides={}, names=[], unreadable=True,
                   problem=f"the project's record of sides could not be read ({str(exc)[:160]})")
    return out


def _keyless(name) -> bool:
    """A side name that cannot be a key of the story's record (`sides.<name>.<attribute>=<value>`): it holds a dot or an equals sign.
    An old or hand-edited registry row with such a name reads malformed (unknown), so S0 records `sides_unknown` instead of refusing."""
    return "." in str(name) or "=" in str(name)


def side_realities() -> dict:
    """THE reader of `references/side-realities.json` (AR-1, AR-13): the parsed table, or {} when it cannot be read.
    BOM-safe, because it is `hooklib.read_json`; `story_sides` and `stage_done.coerce_value` both read through it."""
    from hooklib import read_json   # late, as the other `hooklib` names of this module
    return read_json(SIDE_REALITIES_PATH, {}, kind=dict)


PROVISIONAL_KINDS_PATH = Path(__file__).resolve().parent.parent / "references" / "provisional-kinds.json"


def provisional_kinds():
    """THE reader of `references/provisional-kinds.json` (AR-1, AR-13): the list of kind names (the keys of its `kinds` object), or
    None when the file cannot be read (absent, not JSON, no `kinds` object) - None is "unknown", never "no kinds". BOM-safe,
    because it is `hooklib.read_json`; the S5 exit check and the S5 brief both read through it."""
    from hooklib import read_json   # late, as `side_realities`
    kinds = read_json(PROVISIONAL_KINDS_PATH, {}, kind=dict).get("kinds")
    return [str(k) for k in kinds] if isinstance(kinds, (dict, list)) else None


def provisional_kind_on_real(kind) -> str:
    """The `on_real` of a provisional kind, read through the same file as `provisional_kinds` (AR-13): `first_look_only` or `never`.
    A kind without the field, with another word, an unknown kind, a kinds file shaped as a list or an unreadable file reads `never` -
    what cannot be shown legal on a real side is not legal (J-C5, AR-28)."""
    from hooklib import read_json   # late, as `provisional_kinds`
    kinds = read_json(PROVISIONAL_KINDS_PATH, {}, kind=dict).get("kinds")
    body = kinds.get(str(kind or "")) if isinstance(kinds, dict) else None
    return "first_look_only" if isinstance(body, dict) and body.get("on_real") == "first_look_only" else "never"


def _side_row(entry, reference, source) -> dict:
    """One side as the readers return it; a missing or non-dict part reads unknown / true / "" and never `real`."""
    entry = entry if isinstance(entry, dict) else {}
    return {"reality": str(entry.get("reality") or ""),
            "deliverable": entry["deliverable"] if isinstance(entry.get("deliverable"), bool) else True,
            "settles_by": str(entry.get("settles_by") or ""),
            "reference": reference or None,
            "source": str(source or "")}


def parks_after_s5(pipeline) -> bool:
    """True when a side of the story is `absent` AND `deliverable`: the code this story delivers does not exist yet, so the
    story is held after S5. A `substituted` side (deliverable or not) and an `absent` side that is not this story's deliverable
    never park it (S6)."""
    return any(side["reality"] == PARKING_REALITY and side["deliverable"] is True for side in story_sides(pipeline).values())


def awaiting(pipeline) -> dict:
    """The hold of a story waiting for code, from `pipeline.awaiting`: {"state": "none" | "awaiting" | "stopped", "cause",
    "held_from", ...the record as written}. No record: {"state": "none", "cause": "", "held_from": ""}. A record with
    `stopped` is "stopped", any other record is "awaiting". A record without `cause` / `held_from` (written before they
    existed) reads `s5_absent_side` / `S6`; a record that carries them is returned as given."""
    record = pipeline.get("awaiting") if isinstance(pipeline, dict) else None
    if not isinstance(record, dict) or not record:
        return {"state": "none", "cause": "", "held_from": ""}
    return {**record, "state": "stopped" if record.get("stopped") else "awaiting",
            "cause": str(record.get("cause") or AWAITING_DEFAULT_CAUSE),
            "held_from": str(record.get("held_from") or AWAITING_DEFAULT_HELD_FROM)}
