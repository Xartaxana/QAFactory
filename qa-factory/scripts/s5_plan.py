#!/usr/bin/env python3
"""The S5 automation plan: ONE plan for every case of the stage, written before any window (SC1-14).

On the 22.10 run S5 took 3 h 08 min for 8 cases in 3 windows: every window re-judged coverage and re-learned
the repository, and the critic found shape and level defects only after the code was written. The owner's form
(25.10.2026): the automator writes one plan of tests for ALL cases, the code critic checks that plan once, and
the windows are written against it. This module is the plan's one reader and its skeleton, hash and stamp:

  s5_plan.py --task T --init     write the skeleton `work/s5-plan.json` (cases, S3 row, Then clauses)
  s5_plan.py --task T --mode     print which form this story's S5 has: `planned` or `legacy`
  s5_plan.py --task T --check    name every gap of the plan at once (the detector's form: `REJECT — N finding(s)`; exit 0/1)
  s5_plan.py --task T --window N [--out FILE]   the plan's slice for window N as markdown (printed, or written to FILE)

  load(task_root)                THE reader of `work/s5-plan.json` (AR-13); `PlanUnreadable` when it cannot be read
  init(task_root, controller)    the skeleton; an existing plan on the same cases and plan is kept (E38)
  refresh(task_root, controller) a REWORK of the plan: rows kept, rows of new cases added, both hashes current; no `.prev`
  rows_sha(plan)                 {case: hash of the case's row and of every test that touches it}
  test_adjacency(plan, cases)    {case: the other cases a test of the plan ties to it}: THE one builder of "which cases a test ties"
  case_groups(plan, cases, is_ui)   the groups of cases the window cut keeps whole (the connected components), with their surface
  test_neighbours(plan, cases)   the cases that share a test with `cases` (the rows a rework of the plan may touch)
  mode(task_root, state, ...)    `(planned | legacy, why)`: the form of this history, fixed by its first S5 dispatch (E21)
  stamp_review(task_root, id)    the receipt of the plan the critic judged: `work/s5-plan-reviews.json` (E11): bytes, rows, tests
  check(task_root, controller)   every gap of the plan, all at once (`check_report` adds what could not be checked)
  grouping_hints(plan) / hint_rows(task_root)   advice, never a gate: tests at one level in one file that each prove their own case
  window_slice(task_root, n | cases)   the plan's part for window n (or for the cases of a dispatch), as the controller cut the
                                 windows (the plan holds no window), with the review's remarks for it
  reviews(task_root, state)      THE reader of the chain of plan reviews: form + receipt of every accepted critic dispatch
  remarks_of(task_root, state)   the remarks the windows are written against: every `remark`, the LAST review's `blocker`s,
                                 and the case critic's carried concerns (`case_concerns`, CC-n)
  remark_rows_missing(remarks, rows)   the ids without exactly one `plan_remarks` row: the one implementation of that fact
  review_of(task_root, id)       one critic dispatch's review, accepted or not (the accept reads its own before the chain does)
  current_hashes(task_root, c)   the `scope_hash` / `gate_a_plan_hash` as they stand now (what `init` writes)
  looks / next_look / blocker_cases / moved_cases   the chain's caps (R1) and the rows a rework may touch (E1)

The plan is the author's artifact (AR-14): the role fills `tests[]`, `remainders`, `fixtures` and `refactor`; this
module writes only the skeleton and the receipt. The words of the plan live in `handoffs/vocabulary.yaml`
(`test_shapes`, `fit_to_shapes`, `plan_verdicts`, `plan_remark_kinds`, `plan_remark_rows`, `data_strategies`,
`plan_deviation_kinds`; AR-1). Which dispatch is a plan dispatch is `controller.s5_part_of`, and nothing here
reads that word any other way.

Exit 0 done; 2 a refusal (the message names the file, what was expected and the door).
"""
import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import detector_verdict as DV  # noqa: E402
import hooklib  # noqa: E402
from event_store import StateConflict, atomic_json, content_hash  # noqa: E402

EXIT_REFUSED = 2
SCHEMA = 1
# Task-relative; the writers are `init` (the skeleton, then the author) and `stamp_review` (the receipt).
PLAN_REL = "work/s5-plan.json"
PREV_REL = "work/s5-plan.prev.json"
REVIEWS_REL = "work/s5-plan-reviews.json"
# The two forms of an S5 history. `planned`: a plan is owed before the windows. `legacy`: the windows of the earlier form
# (0.10.2, the driver, or a person's word) - no plan is owed and none is judged.
PLANNED = "planned"
LEGACY = "legacy"
# A sentinel for "the file was there and could not be parsed": `hooklib.read_json` answers its `default` for an absent
# file and a broken one alike, and the two are told apart here by `is_file()` first.
_BAD = object()


class PlanUnreadable(ValueError):
    """The plan, its receipt or the state it is read with cannot be read. The caller REFUSES (AR-28): an unknown is
    never a pass, and the message names the file, what was expected and the door."""


def _path(task_root, rel) -> Path:
    return Path(task_root) / rel


def _door(task_root) -> str:
    """The way back from an unreadable plan: repair the JSON, or set the file aside and let `--init` write a fresh
    skeleton (the author keeps what still holds from `work/s5-plan.prev.json`)."""
    return (f"repair the JSON, or move the file to {PREV_REL} and run "
            f"`python scripts/s5_plan.py --task {Path(task_root).resolve().name} --init` for a fresh skeleton")


def load(task_root):
    """The plan as a dict, or None when `work/s5-plan.json` does not exist. THE one reader of that file (AR-13).

    A file that exists and is empty, is not JSON, is not an object, has no `schema` or has a `schema` other than the one
    this release reads is `PlanUnreadable` - never None: "no plan" and "a plan nobody can read" are different answers
    and only the first lets a caller carry on (AR-28)."""
    path = _path(task_root, PLAN_REL)
    if not path.exists():
        return None
    document = hooklib.read_json(path, _BAD, kind=dict) if path.is_file() else _BAD
    if document is _BAD:
        raise PlanUnreadable(f"{PLAN_REL} cannot be read as a JSON object (empty, broken or not a file); expected the plan "
                             f"with `schema: {SCHEMA}`; {_door(task_root)}")
    if document.get("schema") != SCHEMA or isinstance(document.get("schema"), bool):
        raise PlanUnreadable(f"{PLAN_REL} has `schema: {document.get('schema')!r}`; expected `schema: {SCHEMA}`; "
                             f"{_door(task_root)}")
    return document


def _rows(plan, key) -> list:
    value = plan.get(key) if isinstance(plan, dict) else None
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def rows_sha(plan) -> dict:
    """{case: hash} - the hash of the case's own row and of EVERY `tests[]` row that touches the case (a test over several
    cases belongs to each of them: a change to a shared test changes the row of all its cases, which is the point - the
    reviewer's look at a blocker is bounded by these hashes, E1). Tests are taken in `id` order so a reorder is no change."""
    tests = sorted(_rows(plan, "tests"), key=lambda test: str(test.get("id")))
    out = {}
    for row in _rows(plan, "cases"):
        if row.get("case") is None:
            continue
        case = str(row["case"])
        touching = [test for test in tests if case in [str(c) for c in test.get("cases") or []]]
        out[case] = content_hash({"case": row, "tests": touching})
    return out


def tests_cases(plan) -> dict:
    """`{test id: [the cases it lists]}` of the plan as it stands - what the receipt of a review keeps (`stamp_review`), so a
    remark that names a test is still resolved to its cases when the author has since removed or renamed that test (t-1320 F-2).
    A test id used twice (a finding of `check`) keeps the cases of both."""
    out = {}
    for test in _rows(plan, "tests"):
        cases = out.setdefault(str(test.get("id")), [])
        listed = test.get("cases") if isinstance(test.get("cases"), list) else []
        cases.extend(str(case) for case in listed if str(case) not in cases)
    return out


def test_adjacency(plan, cases) -> dict:
    """`{case: set(the other cases of `cases` that share a test with it)}` - THE one builder of "which cases a test ties together"
    (AR-15, F9): the window cut (`controller.pack_windows` through `case_groups`), the window gate (11) and the rows a plan rework
    may touch (`test_neighbours`) read this and nothing else. Every case of `cases` has a key, tied or not. A case a test lists
    that is not in `cases` ties nothing (it is outside the scope); a `tests` that is not a list, a row that is not a mapping, a
    `cases` that is not a list and an entry that is not text tie nothing. Pure; never raises."""
    wanted = [str(case) for case in cases] if isinstance(cases, (list, tuple)) else []
    known = set(wanted)
    out = {case: set() for case in wanted}
    for test in _rows(plan, "tests"):
        listed = test.get("cases")
        inside = [case for case in listed if isinstance(case, str) and case in known] if isinstance(listed, list) else []
        for case in inside:
            out[case].update(other for other in inside if other != case)
    return out


def case_groups(plan, cases, is_ui) -> list:
    """The groups of `cases` the window cut keeps whole (spec t-1314 section 2 items 1-2): the connected components of
    `test_adjacency`, in order of the smallest position of a case in `cases`, each `{"cases": [in the order of `cases`],
    "tests": [the ids of the tests that list one of them, sorted], "surface": "ui" | "other"}`. A case with no test is a group of
    one. The surface of a group: `ui` when any of its tests is `e2e-ui`; `other` when it has tests and every one of them has a
    known level that is not; otherwise (no test, or a test whose level is empty or not a word of `contract.PLAN_LEVELS`) the S3
    row decides - `ui` when `is_ui(case)` holds for any case of the group. `is_ui` answers True, False or None (`Controller.
    _is_ui_case`, THE one reader of the S3 level, AR-13): None is "the S3 level is unknown" (no word of `contract.PLAN_LEVELS`). A
    group that has a test of an unknown level and a case whose S3 level is unknown (`is_ui` is None) is `ui`: neither the test nor S3
    says it is not, and the error direction is the smaller window (FR-59). A group of cases with no test is by `is_ui` alone, as the
    cut by cases has always been (None is falsy). Pure; never raises on a plan it cannot read (then every case is a group of one)."""
    wanted = list(dict.fromkeys(str(case) for case in cases)) if isinstance(cases, (list, tuple)) else []
    adjacency = test_adjacency(plan, wanted)
    position = {case: index for index, case in enumerate(wanted)}
    rows = _rows(plan, "tests")
    seen, groups = set(), []
    for first in wanted:
        if first in seen:
            continue
        seen.add(first)
        component, stack = [], [first]
        while stack:
            case = stack.pop()
            component.append(case)
            for other in adjacency[case]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        component.sort(key=position.get)
        touching = [test for test in rows if isinstance(test.get("cases"), list) and any(c in component for c in test["cases"])]
        levels = [test.get("level") for test in touching]
        if "e2e-ui" in levels:
            surface = "ui"
        elif touching and all(level in C.PLAN_LEVELS for level in levels):
            surface = "other"
        else:
            unknown_s3 = bool(touching) and any(is_ui(case) is None for case in component)
            surface = "ui" if unknown_s3 or any(is_ui(case) for case in component) else "other"
        groups.append({"cases": component, "tests": sorted(str(test.get("id")) for test in touching), "surface": surface})
    return groups


def test_neighbours(plan, cases) -> set:
    """The cases that share a test with one of `cases`, without `cases` themselves, wherever the test lists them (the rows a plan
    rework for new or gone cases may touch, FJ-C). Read through `test_adjacency`, over every case any test lists. Pure; never raises."""
    wanted = [str(case) for case in cases] if isinstance(cases, (list, tuple, set, frozenset)) else []
    listed = [case for test in _rows(plan, "tests") if isinstance(test.get("cases"), list) for case in test["cases"] if isinstance(case, str)]
    adjacency = test_adjacency(plan, list(dict.fromkeys(wanted + listed)))   # a str key: `wanted` is text, `listed` is text
    return {other for case in wanted for other in adjacency.get(case, ())} - set(wanted)


def tests_tying(tests, cases, least=2) -> list:
    """The ids of the tests, in the order given, that list at least `least` entries of `cases` - THE one reading of "which tests
    cover these cases" (AR-13): `least=2` is the tests that TIE the cases together (the over-cap note, the slice's line), `least=1`
    the tests that touch one of them (the tests of a grown window). `tests` is a plan (its `tests` rows) or a list of test rows;
    a row that is not a mapping or lists no `cases` list covers nothing. Pure; never raises."""
    rows = _rows(tests, "tests") if isinstance(tests, dict) else [t for t in tests if isinstance(t, dict)] if isinstance(tests, list) else []
    wanted = {str(case) for case in cases} if isinstance(cases, (list, tuple, set, frozenset)) else set()
    return [str(test.get("id")) for test in rows
            if isinstance(test.get("cases"), list) and sum(1 for c in test["cases"] if str(c) in wanted) >= least]


def _pins(task_root) -> dict:
    """link key (and the bare case id) -> the pinned CaseVersion from `state/story-case-links.json`. The case index says the
    version when the case file is there; the link itself says it when the file is not (a pin outlives a missing file)."""
    pins = {}
    for link in C.story_case_links(task_root):
        if link.get("case_id") and link.get("version"):
            pins[C.case_link_key(link)] = str(link["version"])
            pins.setdefault(str(link["case_id"]), str(link["version"]))
    return pins


def _then_rows(entry) -> list:
    """[{n, text}] of the case's Then clauses, by the S5 reader of a case's Then (`s5_precheck.then_clauses`); a case file
    that is not there reads as no clause - which `check` reports as a finding, never as a pass."""
    from s5_precheck import then_clauses
    path = (entry or {}).get("path")
    text = C.read_text(Path(path)) if path else ""
    return [{"n": number, "text": " ".join(str(clause).split())} for number, clause in then_clauses(text)]


def _versions(task_root, cases) -> tuple:
    """`(case index, {case: pinned version})` for `cases`: the case file's version when it is there, else the link's pin, else
    `""`. THE one reading of the versions `scope_hash` is made of (`init` writes it, `current_hashes` compares with it)."""
    try:
        index = C.case_index(Path(task_root))
    except (OSError, ValueError, TypeError):
        index = {}
    pins = _pins(task_root)
    return index, {case: str(((index.get(case) if index else None) or {}).get("version") or pins.get(case) or "") for case in cases}


def _gate_hash(controller) -> str:
    """The approved plan's content hash (`gate-inputs`), or `""` when it cannot be read: B1b reads `""` as "not checked" and
    refuses; nothing here may turn an unreadable plan hash into a match."""
    try:
        return str(controller.gate_inputs().get("plan_content_hash") or "")
    except (StateConflict, ValueError, OSError, KeyError, TypeError):
        return ""


def _underived(scope, limit=None) -> str:
    """The head of every statement that the S5 scope could not be derived (an unknown scope is not an empty one, AR-28): one
    sentence for the refusals of `current_hashes` / `init` and the finding of `check_report`, so they cannot drift apart."""
    reason = str(scope.get("reason") or "no reason given")
    return f"the S5 scope cannot be derived ({_show(reason, limit) if limit else reason})"


def _scope(controller, state, door):
    """`(the scope document, its cases as text)`; a scope that cannot be derived is `PlanUnreadable` naming `door`."""
    scope = controller.stage_scope("S5", state)
    if not scope.get("derived"):
        raise PlanUnreadable(f"{_underived(scope)}; expected the approved plan with a disposition on its rows; {door}")
    return scope, [str(case) for case in scope.get("scope") or []]


def _dispatches(state) -> dict:
    """The `dispatches` of the controller's projection (`{}` when it has none). A state that is not a mapping, or `dispatches`
    that is neither absent nor a mapping, is `PlanUnreadable` (AR-28): THE one refusal for it, read by `mode` and `reviews`."""
    if not isinstance(state, dict):
        raise PlanUnreadable("the story state is not a mapping; expected the controller's projection; run the controller's "
                             "`recover` operation, then ask again")
    dispatches = {} if state.get("dispatches") is None else state["dispatches"]
    if not isinstance(dispatches, dict):
        raise PlanUnreadable("`dispatches` of the story state is not a mapping; expected the controller's projection; run the "
                             "controller's `recover` operation, then ask again")
    return dispatches


def current_hashes(task_root, controller) -> tuple:
    """`(scope_hash, gate_a_plan_hash)` as they stand NOW - the two values `init` writes into the plan, read by the same code
    (AR-15), so a plan written for other cases or another approved plan is told from the current one. Writes nothing. A scope
    that cannot be derived is `PlanUnreadable` (an unknown scope is not an empty one, AR-28)."""
    _scope_doc, cases = _scope(controller, controller.state(), "fix the plan, then ask again")
    _index, versions = _versions(task_root, cases)
    return content_hash(sorted([case, versions[case]] for case in cases)), _gate_hash(controller)


def _skeleton(task_root, controller, door) -> dict:
    """The skeleton plan for the stage's scope as it stands NOW: what code can derive - the cases, the S3 row (`row`, `level`,
    `fit`, `oracle`; `null` for what S3 did not say), the requirements the row names and the Then clauses (no window: the
    controller cuts the windows, from the plan's tests, after the review) - and empty places for what only the author decides.
    Writes nothing; a scope that cannot be derived is `PlanUnreadable` naming `door`. THE one builder of a case's row (AR-15):
    `init` writes the whole of it, `refresh` the rows of the new cases."""
    state = controller.state()
    scope, cases = _scope(controller, state, door)
    mapping, _dispositions, _basis = controller._case_rows(state)
    plan_rows = {str(row.get("id")): row for row in controller._plan_rows() or [] if isinstance(row, dict)}
    index, versions = _versions(task_root, cases)
    rows, pairs = [], []
    for case in cases:
        entry = index.get(case) if index else None
        pairs.append([case, versions[case]])
        row_id = mapping.get(case)
        plan_row = plan_rows.get(str(row_id)) or {}
        requirements = plan_row.get("requirements")
        if not isinstance(requirements, list):
            requirements = C.REQ_ID_RE.findall(str(plan_row.get("r") or ""))
        s3 = {"row": str(row_id) if row_id is not None else None}
        for key in ("level", "fit", "oracle"):
            s3[key] = str(plan_row.get(key) or "").strip() or None     # what S3 did not say is null, never ""
        rows.append({"case": case,
                     "requirements": [str(r) for r in requirements],
                     "s3": s3, "thens": _then_rows(entry), "remainders": []})
    return {"schema": SCHEMA, "scope_hash": content_hash(sorted(pairs)), "gate_a_plan_hash": _gate_hash(controller),
            "cases": rows, "tests": [], "fixtures": [], "refactor": ""}


def init(task_root, controller) -> dict:
    """The skeleton `work/s5-plan.json` for the stage's scope, and the plan as it now stands on disk (`_skeleton` says what it
    carries and what is left to the author: `tests[]`, `remainders`, `fixtures`, `refactor`).

    - A plan that exists and was written for the SAME cases at the same versions (`scope_hash`) and the same approved plan
      (`gate_a_plan_hash`) is NOT overwritten: a second `start` after a failure must not wipe the author's work.
    - A plan written for other cases or another plan is moved to `work/s5-plan.prev.json` (replacing the previous
      `.prev`) and a new skeleton is written: the old one is stale, and not lost (E38). A REWORK of the plan whose scope grew
      does not come here (it would lose every row): it calls `refresh`.
    - A plan that exists and cannot be read is `PlanUnreadable`, and is touched by nothing (it may be an interrupted write
      of the author's; FR-57 leaves the repair to the role).
    - An S5 with NO case in scope has no plan (E7): the skeleton is returned, nothing is written.
    - A scope that cannot be derived (`stage_scope` says `derived: false`) is `PlanUnreadable`: an unknown scope is not an
      empty one (AR-28)."""
    skeleton = _skeleton(task_root, controller, "fix the plan, then run `--init` again")
    if not skeleton["cases"]:
        return skeleton
    existing = load(task_root)
    if existing is not None:
        if (existing.get("scope_hash") == skeleton["scope_hash"]
                and existing.get("gate_a_plan_hash") == skeleton["gate_a_plan_hash"]):
            return existing
        os.replace(_path(task_root, PLAN_REL), _path(task_root, PREV_REL))
    atomic_json(_path(task_root, PLAN_REL), skeleton)
    return skeleton


def refresh(task_root, controller) -> dict:
    """The plan after the scope or the approved plan moved under a REWORK of it (spec t-1314 section 2 item 13; t-1320 question 3):
    the author's rows stay, the two hashes become the current ones, and the plan as it now stands on disk is returned.

    - The rows of cases that came into the scope are added as skeleton rows (the same builder as `init`); the rows of cases that
      left the scope STAY - `check` names them (step a) and the author decides.
    - `tests[]`, `fixtures`, `refactor` and every row already there are not touched, and nothing goes to `work/s5-plan.prev.json`
      (that is `init`'s E38, which on a rework would lose every row and have E1 refuse each old one).
    - A plan that is already current is NOT rewritten: its bytes are what the critic's receipt (`plan_sha256`) measured, and a
      rewrite that changed no row must not make the plan "changed after its review" (E11).
    - No file: as `init`. A plan that cannot be read, or whose `cases` is not a list, is `PlanUnreadable`, touched by nothing.
    - A scope that cannot be derived is `PlanUnreadable`; an S5 with no case in scope owes no plan (E7): nothing is written."""
    existing = load(task_root)
    if existing is None:
        return init(task_root, controller)
    skeleton = _skeleton(task_root, controller, "fix the plan, then ask again")
    if not skeleton["cases"]:
        return existing
    if not isinstance(existing.get("cases"), list):
        raise PlanUnreadable(f"{PLAN_REL} has no `cases` list, so its rows cannot be kept; expected the plan's skeleton rows; "
                             f"{_door(task_root)}")
    have = {str(row.get("case")) for row in _rows(existing, "cases")}
    added = [row for row in skeleton["cases"] if row["case"] not in have]
    hashes = {"scope_hash": skeleton["scope_hash"], "gate_a_plan_hash": skeleton["gate_a_plan_hash"]}
    if not added and all(existing.get(key) == value for key, value in hashes.items()):
        return existing
    refreshed = dict(existing, cases=existing["cases"] + added, **hashes)
    atomic_json(_path(task_root, PLAN_REL), refreshed)
    return refreshed


def mode(task_root, state, run_mode="desktop"):
    """`(PLANNED | LEGACY, why)`: whether this story's S5 is written against a plan. The form is FIXED by the history's first
    S5 dispatch and never switches silently (E21, F-H); the order is the rule:

      1. any S5 record of the plan kind, in any status           -> planned (a plan dispatch was made; if the file is not
         there the caller refuses "plan missing": the form does not fall back to legacy because a file is gone)
      2. else any LIVE window record of S5 (not in DISCOUNTED)   -> legacy (an earlier form, the driver, or a person's word)
      3. else (no S5 record, or every one set aside)             -> legacy for the driver process, planned for the rest.
         This is the only place the process matters, and `run_mode` is the caller's (the dispatch path, B1b): the stamp
         `pipeline.run_mode` is NOT read - a person's word that switches the mode does not rewrite it.

    The kind of a record is `controller.s5_part_of` and nothing else. The error direction is `planned` (a refusal with a
    door): an unreadable state - not a mapping, or `dispatches` neither absent nor a mapping - is `PlanUnreadable`, never
    `legacy`. A record that is not a mapping is no S5 record and is skipped."""
    import controller as CT
    dispatches = _dispatches(state)
    records = [d for d in dispatches.values() if isinstance(d, dict) and d.get("stage") == "S5"]
    if any(CT.s5_part_of(d) == "plan" for d in records):
        if _path(task_root, PLAN_REL).is_file():
            return PLANNED, "a plan dispatch is on record for S5"
        return PLANNED, f"plan record, no file: a plan dispatch is on record for S5 but {PLAN_REL} is missing"
    if any(d.get("status") not in CT.DISCOUNTED for d in records):
        return LEGACY, "earlier form, the driver, or a person's word: S5 windows were begun without a plan"
    if run_mode == "driver":
        return LEGACY, "no S5 dispatch yet and the driver process asks: the driver keeps the earlier form"
    return PLANNED, "no live S5 window on record: a plan is owed before the windows"


def plan_sha256(task_root):
    """The sha256 of the BYTES of `work/s5-plan.json` (what the critic read), or None when there is no file. THE one measure of
    "the plan as it was reviewed" - the stamp writes it, the window gate and the critic's accept compare with it (E11)."""
    path = _path(task_root, PLAN_REL)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def stamp_review(task_root, dispatch_id) -> dict:
    """Record the plan as the critic's dispatch `dispatch_id` saw it: `{dispatch, plan_sha256, rows_sha}` in
    `work/s5-plan-reviews.json` (a list; a line of the same dispatch is replaced, any other is kept). Called by `finish` for
    the critic of the plan BEFORE the dispatch is accepted (N7): the critic computes no hash, code does, and the stamp is
    measured on the bytes the critic read. A stamp of a dispatch that is then refused stays in the file; the readers take the
    stamp of the last ACCEPTED review, not the last line (R2).

    No plan is `PlanUnreadable`; so is a receipt file that exists and is not a list (the chain it holds is not rewritten
    over). Returns the line written."""
    if not str(dispatch_id or "").strip():
        raise ValueError("stamp_review needs the id of the critic's dispatch; expected e.g. `S5-qa-code-critic-1`")
    plan = load(task_root)
    if plan is None:
        raise PlanUnreadable(f"{PLAN_REL} does not exist, so there is nothing to stamp; expected the author's plan; run "
                             f"`python scripts/s5_plan.py --task {Path(task_root).resolve().name} --init`")
    path = _path(task_root, REVIEWS_REL)
    chain = []
    if path.exists():
        chain = hooklib.read_json(path, _BAD, kind=list) if path.is_file() else _BAD
        if chain is _BAD:
            raise PlanUnreadable(f"{REVIEWS_REL} cannot be read as a JSON list (empty, broken or not a file); expected the "
                                 "receipts of the plan reviews; repair the JSON - the chain it holds is not rewritten")
    line = {"dispatch": str(dispatch_id), "plan_sha256": plan_sha256(task_root), "rows_sha": rows_sha(plan),
            "tests": tests_cases(plan)}
    kept = [row for row in chain if not (isinstance(row, dict) and row.get("dispatch") == line["dispatch"])]
    atomic_json(path, kept + [line])
    return line


# --- the plan check (A1b) -------------------------------------------------------------------------------

# Every free-text field of the plan is held to this many CHARACTERS: 300 passes, 301 is a finding (E14). A long account
# belongs in an artifact; the plan is read by a critic and by every window.
TEXT_LIMIT = 300
# What `tests[].deviation[].from` can name: the plan departs from the S3 row's `fit` or its `level` (the two S3 fields the plan
# is compared with). They are field names of the S3 row, not a vocabulary.
DEVIATION_FROM = ("fit", "level")
# `case` / `test` / `then` of a review remark when the remark is about the plan as a whole: absent, empty or a dash.
_NO_REF = (None, "", "-", "–", "—")


def _line(text) -> str:
    return DV.one_line(text)


def _show(value, limit: int = 70) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _words() -> tuple:
    """(test_shapes, fit_to_shapes, data_strategies) - the plan's closed words, read from the vocabulary (AR-1). A
    vocabulary that cannot be read is a refusal, not an empty list of words: nothing could then be called wrong (AR-28)."""
    import handoff
    try:
        vocabulary = handoff.vocabulary()
    except (OSError, ValueError) as exc:
        raise PlanUnreadable(f"handoffs/vocabulary.yaml cannot be read ({exc}); expected the factory's word lists "
                             "(`test_shapes`, `fit_to_shapes`, `data_strategies`); reinstall the package") from exc
    shapes = [str(word) for word in vocabulary.get("test_shapes") or []]
    fits = vocabulary.get("fit_to_shapes")
    fit_map = ({str(key): [str(word) for word in value] for key, value in fits.items() if isinstance(value, list)}
               if isinstance(fits, dict) else {})
    strategies = [str(word) for word in vocabulary.get("data_strategies") or []]
    if not (shapes and fit_map and strategies):
        raise PlanUnreadable("handoffs/vocabulary.yaml has no `test_shapes`, `fit_to_shapes` or `data_strategies`; "
                             "expected the plan's word lists; reinstall the package")
    return shapes, fit_map, strategies


def _text_problem(where, name, value, required=False):
    """The finding for a free-text field of the plan, or None: not text, empty when required, or over `TEXT_LIMIT`."""
    if value is None or value == "":
        return (f"{where}: `{name}` is empty — fix: write it in at most {TEXT_LIMIT} characters") if required else None
    if not isinstance(value, str):
        return f"{where}: `{name}` is not text — fix: write it as a string of at most {TEXT_LIMIT} characters"
    if len(value) > TEXT_LIMIT:
        return (f"{where}: `{name}` is {len(value)} characters, the limit is {TEXT_LIMIT} — fix: shorten it to "
                f"{TEXT_LIMIT} or fewer; a long account belongs in an artifact the plan points at")
    return None


def _joined(words) -> str:
    words = [str(word) for word in words]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _project_file(root, rel):
    """(path | None, why): the project file a test path names. The survivor that resolves a test file for a probe is
    `probe_by_code._test_path` (the project root, then the run directory of the profile that owns the path); a path it
    refuses for a reason other than "no such file" is `(None, <its words>)` - the check could not tell, and says so."""
    import probe_by_code as PB
    import runtime_paths
    first = Path(root) / rel
    if first.is_file():
        return first, ""
    config = hooklib.read_json(Path(root) / runtime_paths.HOME / "config.json", {}, kind=dict)
    try:
        path, _cwd = PB._test_path(Path(root), config, {"file": rel})
    except PB.Refusal as exc:
        return None, ("" if str(exc).startswith("no file") else str(exc))
    return path, ""


def _extends_problem(test, root):
    """`(finding | None, note | None)` for the existing test an `extend`/`reuse` row builds on (step d). Python only: the AST
    of the file is the one `probe_by_code` reads (`parse_node`, `locate`); any other language is "not checked", out loud."""
    where = f"test {_show(test.get('id'))}"
    extends = test.get("extends")
    if not isinstance(extends, str) or not extends.strip():
        return (f"{where}: shape `{test.get('shape')}` builds on an existing test but `extends` is empty — fix: name "
                "it as `<file>::<function>`"), None
    text = extends.strip().replace("\\", "/")
    head = text.split("::", 1)[0]
    if "::" not in text:
        return (f"{where}: `extends` {_show(text)!r} has no `::<function>` — fix: name the test as "
                "`<file>::[Class::]<function>`"), None
    if not head.endswith(".py"):
        return None, f"{where}: `extends` {_show(text)} is not a Python file"
    import probe_by_code as PB
    try:
        spec = PB.parse_node(text, root)
    except PB.Refusal:
        return (f"{where}: `extends` {_show(text)!r} does not name a function — fix: name the test as "
                "`<file>.py::[Class::]<function>`"), None
    if root is None:
        return None, f"{where}: `extends` {_show(text)} - the project is not found, so the file was not looked for"
    path, why = _project_file(root, spec["file"])
    if why:
        return None, f"{where}: `extends` {_show(text)} - cannot tell where that test runs ({_show(why, 120)})"
    if path is None:
        return (f"{where}: `extends` names {spec['file']}, which is not under the project root — fix: name an existing "
                "test file, or plan a `new` test"), None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, SyntaxError) as exc:
        return None, f"{where}: `extends` {_show(text)} - {spec['file']} could not be parsed ({_show(exc, 80)})"
    try:
        PB.locate(tree, spec["chain"], spec["function"])
    except PB.Refusal as exc:
        return (f"{where}: `extends` {_show(text)}: {exc} — fix: name an existing test function (with its class when the "
                "name repeats), or plan a `new` test"), None
    return None, None


def _plan_cases(plan, scope, findings) -> dict:
    """Step (a): every case of the scope has a row, there are no others, each has a Then. Returns {case: row}."""
    raw = plan.get("cases")
    if not isinstance(raw, list):
        findings.append("plan: `cases` is not a list — fix: run `s5_plan.py --init` for the skeleton, or restore the list")
        return {}
    rows, seen = {}, set()
    for index, row in enumerate(raw):
        case = str(row.get("case")) if isinstance(row, dict) and row.get("case") is not None else None
        if case is None:
            findings.append(f"plan: cases[{index}] is not a row of a case — fix: keep the skeleton's rows; each has `case`")
            continue
        if case in seen:
            findings.append(f"case {case}: appears twice in `cases` — fix: keep one row per case")
            continue
        seen.add(case)
        rows[case] = row
        if case not in scope:
            findings.append(f"case {case}: is not in the S5 scope ({_show(', '.join(scope) or 'empty', 100)}) — fix: remove "
                            "the row; a case is planned only when the approved plan automates it")
    for case in scope:
        if case not in rows:
            findings.append(f"case {case}: has no row in the plan — fix: run `s5_plan.py --init` and plan its tests")
        elif not [t for t in rows[case].get("thens") or [] if isinstance(t, dict)]:
            findings.append(f"case {case}: has no Then clause — fix: the case file must state its outcomes under `## Then`; "
                            "a case with no Then proves nothing")
    return rows


def _test_rows(plan, scope, rows, findings) -> list:
    """The `tests[]` rows that are rows, with the structural findings of steps (a), (g), (i) and (z): ids, cases, words and
    the 300-character texts. A row that is not a mapping is a finding and is not read further."""
    raw = plan.get("tests")
    if not isinstance(raw, list):
        findings.append("plan: `tests` is not a list — fix: write the plan's tests as a list of rows")
        return []
    tests, ids = [], {}
    for index, test in enumerate(raw):
        if not isinstance(test, dict):
            findings.append(f"plan: tests[{index}] is not a row — fix: write each test as a mapping with an `id`")
            continue
        tests.append(test)
        identifier = test.get("id")
        where = f"test {_show(identifier) if identifier else f'tests[{index}]'}"
        if not isinstance(identifier, str) or not identifier.strip():
            findings.append(f"{where}: has no `id` — fix: give every test an id such as T-1")
        elif identifier in ids:
            findings.append(f"test {identifier}: the id is used twice (tests[{ids[identifier]}] and tests[{index}]) — fix: "
                            "ids are unique, a remark of the review names a test by it")
        else:
            ids[identifier] = index
        for key in ("file", "function"):
            if not isinstance(test.get(key), str) or not test.get(key).strip():
                findings.append(f"{where}: `{key}` is empty — fix: name the test's {key}")
        cases = test.get("cases")
        if not isinstance(cases, list) or not cases or not all(isinstance(c, str) for c in cases):
            findings.append(f"{where}: `cases` is not a non-empty list of case ids — fix: name the cases the test proves")
        else:
            outside = [c for c in cases if c not in scope]
            if outside:
                findings.append(f"{where}: `cases` names {_joined(outside)}, outside the S5 scope — fix: a test proves "
                                "only cases of this scope")
        for key in ("level", "shape", "data"):
            if not isinstance(test.get(key), str) or not test.get(key).strip():
                findings.append(f"{where}: `{key}` is empty — fix: state the test's {key}")
        problem = _text_problem(where, "assert", test.get("assert"), required=True)
        if problem:
            findings.append(problem)
        if "apart_reason" in test:      # optional (AR-23): absent, empty or blank = the test is a candidate of the grouping hint
            problem = _text_problem(where, "apart_reason", test.get("apart_reason"))
            if problem:
                findings.append(problem)
        deviations = test.get("deviation") or []
        if not isinstance(deviations, list):
            findings.append(f"{where}: `deviation` is not a list — fix: write rows `{{from: fit|level, reason}}`")
            deviations = []
        for number, deviation in enumerate(deviations):
            if not isinstance(deviation, dict) or deviation.get("from") not in DEVIATION_FROM:
                findings.append(f"{where}: deviation[{number}] does not say `from: {'|'.join(DEVIATION_FROM)}` — fix: "
                                "a plan departs from the S3 row's `fit` or `level`, and says which")
                continue
            problem = _text_problem(where, f"deviation[{number}].reason", deviation.get("reason"))
            if problem:
                findings.append(problem)
    return tests


def _proven_thens(tests, rows, findings) -> dict:
    """Step (b), the tests' side: `{(case, n): [ids of the tests that assert that Then]}`. A `thens` that is not a non-empty
    list of `<case>#<n>`, a reference of another shape, a case the test does not list and a Then the case does not have are
    findings, and a reference that names no Then proves nothing."""
    proven = {}      # (case, n) -> [test ids]
    for test in tests:
        identifier = str(test.get("id"))
        listed = test.get("cases") if isinstance(test.get("cases"), list) else []
        thens = test.get("thens")
        if not isinstance(thens, list) or not thens or not all(isinstance(t, str) for t in thens):
            findings.append(f"test {_show(identifier)}: `thens` is not a non-empty list of `<case>#<n>` — fix: name the "
                            "Then clauses the test asserts")
            continue
        for reference in dict.fromkeys(thens):
            case, hash_sign, number = reference.rpartition("#")
            if not hash_sign or not case or not number:
                findings.append(f"test {_show(identifier)}: Then reference {_show(reference)!r} is not `<case>#<n>` — fix: "
                                "write it as e.g. TC-1#2")
                continue
            if case not in listed:
                findings.append(f"test {_show(identifier)}: asserts {reference} but does not list {case} in `cases` — fix: "
                                "add the case to `cases` (the review of a case looks at the tests that list it)")
            if case in rows and number not in {str(t.get("n")) for t in rows[case].get("thens") or [] if isinstance(t, dict)}:
                findings.append(f"test {_show(identifier)}: asserts {reference}, a Then the case does not have — fix: use "
                                "the numbers of the case's Then clauses")
                continue
            proven.setdefault((case, number), []).append(identifier)
    return proven


def _left_thens(rows, findings) -> dict:
    """Step (b), the remainders' side: `{(case, n): how many remainder rows name that Then}`. A `remainders` that is not a list,
    a remainder naming a Then the case does not have, a reason outside `UNRESOLVED_REASONS` and a long detail are findings."""
    left = {}        # (case, n) -> how many remainder rows
    for case, row in rows.items():
        remainders = row.get("remainders")
        if not isinstance(remainders, list):
            findings.append(f"case {case}: `remainders` is not a list — fix: write [] when no Then is left to a person")
            continue
        own = {str(t.get("n")) for t in row.get("thens") or [] if isinstance(t, dict)}
        for number, remainder in enumerate(remainders):
            then = str(remainder.get("then")) if isinstance(remainder, dict) else ""
            if then not in own:
                findings.append(f"case {case}: remainders[{number}] names Then {_show(then) or '(none)'}, which the case does "
                                "not have — fix: name a Then of the case")
                continue
            left[(case, then)] = left.get((case, then), 0) + 1
            if remainder.get("reason") not in C.UNRESOLVED_REASONS:
                findings.append(f"case {case}: remainder of Then {then} has reason {_show(remainder.get('reason'))!r}, expected "
                                f"one of {', '.join(C.UNRESOLVED_REASONS)} — fix: use one of those words")
            problem = _text_problem(f"case {case}", f"remainders[{number}].detail", remainder.get("detail"))
            if problem:
                findings.append(problem)
    return left


def _then_bindings(tests, rows, findings) -> None:
    """Step (b): each Then of each case is in the `thens` of exactly one test OR in the case's `remainders` exactly once -
    never in both, never in neither. References that name no Then, or a case the test does not list, are findings too."""
    proven = _proven_thens(tests, rows, findings)
    left = _left_thens(rows, findings)
    for case, row in rows.items():
        for then in row.get("thens") or []:
            if not isinstance(then, dict):
                continue
            key = (case, str(then.get("n")))
            by_tests, by_remainder = proven.get(key, []), left.get(key, 0)
            name = f"case {case} Then {key[1]}"
            if not by_tests and not by_remainder:
                findings.append(f"{name}: is in no test and in no remainder — fix: assert it in a test (`thens`), or leave "
                                "it to a person as a remainder with a reason")
            elif by_tests and by_remainder:
                findings.append(f"{name}: is in the tests ({_joined(by_tests)}) and in the remainders, both — fix: exactly "
                                "one of the two")
            elif len(by_tests) > 1:
                findings.append(f"{name}: is asserted by {len(by_tests)} tests ({_joined(by_tests)}) — fix: exactly one "
                                "test asserts a Then; share the check, or consolidate the tests")
            elif by_remainder > 1:
                findings.append(f"{name}: is a remainder {by_remainder} times — fix: once")


def _test_words(tests, root, findings, notes) -> None:
    """Steps (c) to (f) on the test alone: `shape`, `level` and `data` are words of the vocabulary (`PLAN_LEVELS` for the
    level), an `extend`/`reuse` test builds on a test that exists, a `consolidate` test names what it merges."""
    shapes, _fit_map, strategies = _words()
    for test in tests:
        where = f"test {_show(test.get('id'))}"
        shape, level, data = test.get("shape"), test.get("level"), test.get("data")
        if isinstance(shape, str) and shape.strip() and shape not in shapes:
            findings.append(f"{where}: shape {_show(shape)!r} is not one of {', '.join(shapes)} — fix: use one of those words")
        if isinstance(level, str) and level.strip() and level not in C.PLAN_LEVELS:
            findings.append(f"{where}: level {_show(level)!r} is not one of {', '.join(C.PLAN_LEVELS)} — fix: use one of "
                            "those words")
        if isinstance(data, str) and data.strip() and data not in strategies:
            findings.append(f"{where}: data {_show(data)!r} is not one of {', '.join(strategies)} — fix: use one of those words")
        if shape in ("extend", "reuse"):
            problem, note = _extends_problem(test, root)
            if problem:
                findings.append(problem)
            if note:
                notes.append("not checked: " + note)
        if shape == "consolidate" and not (isinstance(test.get("consolidates"), list) and test.get("consolidates")):
            findings.append(f"{where}: shape `consolidate` names no test in `consolidates` — fix: list the tests it merges "
                            "(`consolidates` means two lists: in the S5 plan, the tests a consolidated test merges; in the manifest, "
                            "the cases the instance proves)")


def _s3_comparisons(tests, rows, findings, notes) -> None:
    """Steps (c) and (d): the test's `shape` against the S3 row's `fit`, its `level` against the S3 `level`; a departure needs
    a `deviation` row of that kind. An S3 row that says nothing is "not checked" - a note, never "matches" (E17)."""
    shapes, fit_map, _strategies = _words()
    no_fit, odd_fit, no_level = [], [], []
    for test in tests:
        where = f"test {_show(test.get('id'))}"
        shape, level = test.get("shape"), test.get("level")
        deviations = [d.get("from") for d in test.get("deviation") or [] if isinstance(d, dict)]
        departed_fit, departed_level = [], []
        for case in [c for c in test.get("cases") or [] if isinstance(c, str) and c in rows]:
            s3 = rows[case].get("s3") if isinstance(rows[case].get("s3"), dict) else {}
            fit = str(s3.get("fit") or "").strip()
            if not fit:
                no_fit.append(case)
            else:
                word = fit.split()[0]
                allowed = fit_map.get(word)
                if allowed is None:
                    odd_fit.append(f"{case} ({_show(word, 30)})")
                elif isinstance(shape, str) and shape in shapes and shape not in allowed:
                    departed_fit.append(f"{case} (S3 fit `{_show(fit)}` allows {', '.join(allowed)})")
            planned = str(s3.get("level") or "").strip()
            if not planned:
                no_level.append(case)
            elif isinstance(level, str) and level in C.PLAN_LEVELS and level != planned:
                departed_level.append(f"{case} (S3 level `{_show(planned, 30)}`)")
        if departed_fit and "fit" not in deviations:
            findings.append(f"{where}: shape `{shape}` departs from S3 for {_joined(departed_fit)}, with no deviation — fix: "
                            "take a shape S3's fit allows, or add a deviation row `{from: fit, reason}`")
        if departed_level and "level" not in deviations:
            findings.append(f"{where}: level `{level}` departs from S3 for {_joined(departed_level)}, with no deviation — fix: "
                            "take S3's level, or add a deviation row `{from: level, reason}`")
    for label, cases, what in (("shape against the S3 `fit`", no_fit, "S3 states no `fit`"),
                               ("shape against the S3 `fit`", odd_fit, "the S3 `fit` word is not one the plan knows"),
                               ("level against the S3 `level`", no_level, "S3 states no `level`")):
        if cases:
            notes.append(f"not checked: {label} for {_joined(dict.fromkeys(cases))} - {what}")


def _window_fit(controller, plan, state, notes, findings) -> None:
    """Step (k), F-J (a)/(b): what the windows the controller cuts from this plan say about it. The plan holds no window
    (`controller.s5_windows_for` cuts them, after the review, from the plan's tests and the windows already written), so this asks
    the cut:
      - a window over its cap (`over_cap`, any surface) is a NOTE: the owner's word is that the cap yields to a test written
        whole, so the author is told and the plan critic judges whether the consolidation is worth it - never a finding;
      - a test whose cases lie in two windows is a FINDING: only windows already written can part a test (a free case joins the
        window its test reaches), and written windows are not merged.
    A cut that cannot be made is a note saying the fit was not checked (an unknown is never a pass, FR-59)."""
    try:
        windows, _cut = controller.s5_windows_for(plan, state)
    except Exception as exc:      # the cut reads the state, the config and the plan: whatever it cannot read, the check says so
        notes.append(f"not checked: the fit of the tests to the windows - the windows could not be cut ({_show(exc, 120)})")
        return
    tests = [test for test in _rows(plan, "tests") if isinstance(test.get("cases"), list)]
    where_of = {str(case): window.get("index") for window in windows for case in window.get("scope") or []}
    for window in windows:
        if not window.get("over_cap"):
            continue
        scope = [str(case) for case in window.get("scope") or []]
        tying = tests_tying(tests, scope)
        because = f" because test(s) {_joined(tying)} tie them" if tying else ""
        notes.append(f"window {window.get('index')}: {len(scope)} cases over the {window.get('surface')} cap of "
                     f"{window.get('cap')}, kept whole{because}")
    for test in tests:
        cut = sorted({where_of[str(case)] for case in test["cases"] if str(case) in where_of})
        if len(cut) > 1:
            findings.append(f"test {_show(test.get('id'))} covers cases of windows {_joined(cut)}, "
                            f"{'both' if len(cut) == 2 else 'all'} already written — fix: split the test; written windows are not merged")


def check_report(task_root, controller, files=True) -> tuple:
    """`(findings, notes)`: every gap of the PLAN, all at once, and what could not be checked.

    A finding is one line, `<where>: <what is wrong> — fix: <what to do>` (the detector contract). A note is a check the
    plan's data did not let run (E16, E17) - printed, never silent, and not a finding. Code here reports and leaves the move to
    the author (FR-47): it decides nothing about a plan's wording, only presence, closed words, hashes of ids and limits.

    Missing and unreadable plans are findings too (a plan nobody can read is not a plan that passed, AR-28); an S5 with no
    case in scope owes no plan (E7). A scope that cannot be derived is a finding: an unknown scope is not an empty one.

    `files=False` leaves the project's files alone: step (d) (the test an `extend`/`reuse` row builds on) is then not looked
    for there, and says so in a note. A window's gate asks so - the plan was clean when its author's work was accepted, a window
    may legitimately rewrite the very test a later row extends, and the plan's bytes cannot have moved since (E11) - whereas
    the author's accept and the `--check` command look at the files as they are."""
    state = controller.state()
    scope_doc = controller.stage_scope("S5", state)
    if not scope_doc.get("derived"):
        return [f"plan: {_underived(scope_doc, 120)} — fix: the approved plan must give every row a disposition; then run the "
                "check again"], []
    scope = [str(case) for case in scope_doc.get("scope") or []]
    try:
        plan = load(task_root)
    except PlanUnreadable as exc:
        return [_line(exc)], []
    if plan is None:
        if not scope:
            return [], ["no case in the S5 scope: no plan is owed"]
        return [f"plan: {PLAN_REL} does not exist — fix: run `python scripts/s5_plan.py --task "
                f"{Path(task_root).resolve().name} --init` for the skeleton, then plan the tests"], []
    findings, notes = [], []
    rows = _plan_cases(plan, scope, findings)
    tests = _test_rows(plan, scope, rows, findings)
    problem = _text_problem("plan", "refactor", plan.get("refactor"))
    if problem:
        findings.append(problem)
    _then_bindings(tests, rows, findings)
    root = None
    try:
        root = controller._project_root() if files else None
    except (OSError, ValueError, AttributeError):
        root = None
    _test_words(tests, root, findings, notes)
    _s3_comparisons(tests, rows, findings, notes)
    _window_fit(controller, plan, state, notes, findings)
    return [_line(finding) for finding in findings], notes


# --- the review chain and the remarks (A1b) --------------------------------------------------------------

def _receipts(task_root):
    """`(the receipt lines | None, why not)` of `work/s5-plan-reviews.json`: absent is `(None, "does not exist")`, broken or
    not a list is `(None, "cannot be read")` - two different answers, neither an empty chain."""
    path = _path(task_root, REVIEWS_REL)
    if not path.exists():
        return None, f"{REVIEWS_REL} does not exist"
    chain = hooklib.read_json(path, _BAD, kind=list) if path.is_file() else _BAD
    if chain is _BAD:
        return None, f"{REVIEWS_REL} cannot be read as a JSON list"
    return chain, ""


def _ref(value):
    """A remark's `case` / `test` / `then`: None for "about the plan as a whole" (absent, empty or a dash), else the text."""
    return None if value in _NO_REF else str(value).strip()


def _remark(row, dispatch, kinds):
    """`(the remark, why not)`: the review remark normalised to its nine keys (+ the dispatch it came from), or the reason
    it cannot be read. The kind is a word of the vocabulary; a remark without an id cannot be answered by a row."""
    if not isinstance(row, dict):
        return None, "a remark is not a mapping"
    identifier = str(row.get("id") or "").strip()
    if not identifier:
        return None, "a remark has no `id`; expected PR-n on every row"
    if row.get("kind") not in kinds:
        return None, f"remark {identifier} has kind {_show(row.get('kind'), 30)!r}, expected one of {', '.join(kinds)}"
    return {"id": identifier, "case": _ref(row.get("case")), "test": _ref(row.get("test")), "then": _ref(row.get("then")),
            "kind": row["kind"], "check": str(row.get("check") or ""), "problem": str(row.get("problem") or ""),
            "expected": str(row.get("expected") or ""), "fix": str(row.get("fix") or ""), "review": dispatch}, ""


def reviews(task_root, state) -> list:
    """THE reader of the chain of plan reviews (AR-13): one element per ACCEPTED critic dispatch of the plan kind, in the order
    of the journal (the order the projection holds the dispatches in) - `{dispatch, outcome, remarks, plan_sha256, rows_sha,
    tests, unreadable}` (`tests`: the receipt's `{test id: cases}`, None for a receipt written before it existed).

    `outcome` and `remarks` come from the critic's form `work/handoffs/<dispatch>.yaml` (`review.outcome`, the top-level
    `remarks` list: absent reads as the empty list, the contract's "or the empty list"); `plan_sha256` and `rows_sha` from the
    receipt `stamp_review` wrote for that dispatch. What cannot be read is NOT skipped: the element carries `unreadable: <what>`
    (an empty string when all is readable) and the caller refuses (E28, AR-28). A state that is not the controller's
    projection is `PlanUnreadable`, like `mode`."""
    import controller as CT
    dispatches = _dispatches(state)
    receipts = _receipts(task_root)
    chain = []
    for record in dispatches.values():
        if not (isinstance(record, dict) and record.get("stage") == "S5" and record.get("role") == "qa-code-critic"
                and record.get("status") == "accepted" and CT.s5_part_of(record) == "plan"):
            continue
        chain.append(_review_element(task_root, str(record.get("id")), receipts))
    return chain


def _review_element(task_root, dispatch, receipts) -> dict:
    """The review of critic dispatch `dispatch`: its form (`review.outcome`, `remarks`) and its receipt, with what cannot be
    read named in `unreadable`. A remark without an `id`, with an unknown `kind`, or whose `id` repeats another of the same
    form is unreadable - it is refused here, before anything is built on it (the window answers every id by a row)."""
    import handoff
    import handoff_check
    from story_step import FORM_REL
    receipts, receipts_why = receipts
    element = {"dispatch": dispatch, "outcome": None, "remarks": [], "plan_sha256": None, "rows_sha": None, "tests": None,
               "unreadable": ""}
    problems = []
    try:
        # the form plus its waiting values file (SC1-2 part D): a `remarks` section the critic wrote only there is heard
        form = handoff_check.form_view(_path(task_root, FORM_REL.format(dispatch_id=dispatch))).data
    except (OSError, ValueError):
        form = None
        problems.append(f"no form {FORM_REL.format(dispatch_id=dispatch)}")
    if isinstance(form, dict):
        problems += _review_form(form, dispatch, element, handoff.vocabulary())
    if receipts is None:
        problems.append(receipts_why)
    else:
        line = next((r for r in receipts if isinstance(r, dict) and r.get("dispatch") == dispatch), None)
        if line is None or not isinstance(line.get("rows_sha"), dict) or not isinstance(line.get("plan_sha256"), str):
            problems.append(f"no receipt for {dispatch} in {REVIEWS_REL}")
        else:
            element["plan_sha256"], element["rows_sha"] = line["plan_sha256"], line["rows_sha"]
            element["tests"] = line["tests"] if isinstance(line.get("tests"), dict) else None    # None: a receipt before F-2
    element["unreadable"] = "; ".join(problems)
    return element


def _review_form(form, dispatch, element, vocabulary) -> list:
    """Reads the critic's form into `element` (`outcome`, `remarks`) and returns what cannot be read, as sentences."""
    verdicts = [str(word) for word in vocabulary.get("plan_verdicts") or []]
    kinds = [str(word) for word in vocabulary.get("plan_remark_kinds") or []]
    problems = []
    review = form.get("review") if isinstance(form.get("review"), dict) else {}
    element["outcome"] = review.get("outcome")
    if element["outcome"] not in verdicts:
        problems.append(f"the form's `review.outcome` is {_show(element['outcome'], 30)!r}, expected one of {', '.join(verdicts)}")
    rows = [] if form.get("remarks") is None else form["remarks"]
    if not isinstance(rows, list):
        return problems + ["the form's `remarks` is not a list"]
    for row in rows:
        remark, why = _remark(row, dispatch, kinds)
        if why:
            problems.append(why)
        elif any(seen["id"] == remark["id"] for seen in element["remarks"]):
            problems.append(f"remark {remark['id']} appears twice in the form; expected one row per id (PR-n)")
        else:
            element["remarks"].append(remark)
    return problems


def review_of(task_root, dispatch_id) -> dict:
    """The review of ONE critic dispatch, accepted or not - the shape of an element of `reviews`. The accept of the critic reads
    its own form and receipt through this BEFORE the dispatch is accepted (the receipt is written by `finish` first), so a form
    that cannot be read is refused at the door and never joins the chain."""
    return _review_element(task_root, str(dispatch_id), _receipts(task_root))


def has_blocker(element) -> bool:
    """Does this review (an element of `reviews` / `review_of`) carry a remark of kind `blocker`?"""
    return any(remark.get("kind") == "blocker" for remark in element.get("remarks") or [])


def looks(chain) -> dict:
    """`{after_blocker: n, new_cases: n}`: the looks the chain has already had past its first review, by what came before each.
    A look right after a review with a blocker is the re-look of F-B (i); a look after a review without one is the narrow look
    at new cases (F-K (a), E2). Each kind has its own cap (R1): the second kind never spends the first."""
    out = {"after_blocker": 0, "new_cases": 0}
    for previous, _ in zip(chain, chain[1:]):
        out["after_blocker" if has_blocker(previous) else "new_cases"] += 1
    return out


def next_look(chain) -> str:
    """The kind of the look a critic rework would be NOW: `after_blocker` when the last review has a blocker, else `new_cases`."""
    return "after_blocker" if chain and has_blocker(chain[-1]) else "new_cases"


def _remark_cases(remark, test_cases) -> tuple:
    """`(cases, unresolved)`: the cases a remark points at - its `case`, the case of its `then` (`<case>#<n>`) and the cases of
    its `test` as `test_cases` (`{test id: [cases]}`) says; `unresolved` is True when it names a test that map does not have
    (or that lists no case). THE one resolution of "which cases does this remark bind" (AR-15): the placement of a remark in a
    window and the rows a rework may change both read it, each with the map of its own plan."""
    cases, unresolved = set(), False
    if remark.get("case"):
        cases.add(str(remark["case"]))
    if remark.get("then") and "#" in str(remark["then"]):
        cases.add(str(remark["then"]).rpartition("#")[0])
    if remark.get("test"):
        listed = test_cases.get(str(remark["test"])) or []
        cases.update(str(case) for case in listed)
        unresolved = not listed
    return cases, unresolved


def blocker_cases(plan, remarks, stamp_tests=None):
    """The cases the `blocker` remarks bind (`_remark_cases`), or None when a blocker names nothing at all - no `case`, no `test`,
    no `then`: it is about the plan as a whole, and no row is held back. A blocker that names something names what the author
    may change; the rest of the plan stays as the critic saw it (E1).

    A test the blocker names is resolved by `stamp_tests` - the `{test id: cases}` the review's receipt kept (`tests_cases`) -
    NOT by the plan as it stands: the author mends a blocker by removing or renaming the test it names, and a lookup in the
    current plan would then find nothing and lift the bound from every row (t-1320 F-2). A receipt that predates the map
    (`stamp_tests` None) is read by the plan as it stands. A name that resolves to no case binds no case: the rows stay held."""
    tests = stamp_tests if isinstance(stamp_tests, dict) else tests_cases(plan)
    bound = set()
    for remark in remarks or []:
        if remark.get("kind") != "blocker":
            continue
        if not (remark.get("case") or remark.get("test") or remark.get("then")):
            return None
        bound |= _remark_cases(remark, tests)[0]
    return bound


def moved_cases(plan, stamp_rows):
    """`(changed, new)`: the cases whose row (with the tests that touch it) differs from the receipt's `rows_sha`, and the cases
    the receipt does not have at all (the scope grew after the review). A case the receipt has and the plan has dropped is
    neither: `check` already refuses a plan with a case outside the scope."""
    now = rows_sha(plan)
    stamp = stamp_rows if isinstance(stamp_rows, dict) else {}
    return ({case for case, sha in now.items() if case in stamp and stamp[case] != sha},
            {case for case in now if case not in stamp})


def verdict_problem(element) -> str:
    """Why the verdict of a readable review and its remarks disagree, or `""` (E40, FR-10): `approved` has no remark,
    `approved_with_remarks` has a remark and no blocker, `blocked` has a blocker. The three words are the vocabulary's
    `plan_verdicts`; what each one allows is the meaning of the word, which is why it is written here."""
    outcome, remarks = element.get("outcome"), element.get("remarks") or []
    blockers = [r["id"] for r in remarks if r.get("kind") == "blocker"]
    if outcome == "approved" and remarks:
        return f"the verdict is `approved` but the form lists {len(remarks)} remark(s) ({', '.join(r['id'] for r in remarks)})"
    if outcome == "approved_with_remarks" and (not remarks or blockers):
        return ("the verdict is `approved_with_remarks` but the form lists no remark" if not remarks else
                f"the verdict is `approved_with_remarks` but {', '.join(blockers)} is a blocker")
    if outcome == "blocked" and not blockers:
        return "the verdict is `blocked` but the form lists no blocker"
    return ""


def remarks_of(task_root, state) -> list:
    """The remarks the windows are written against: EVERY `remark` of EVERY accepted review of the chain, and the `blocker`
    rows of the LAST review only - an earlier blocker was either mended (and accepted at the re-look) or repeated in the last
    review, so it stays out (M8). Order: the chain's, then the review's. A chain with a review that cannot be read is
    `PlanUnreadable`, never a shorter list (E28, AR-28); no review, no remarks. After them come the concerns the S4 case
    critic carried (`case_concerns`): the automator answers them like any remark."""
    chain = reviews(task_root, state)
    broken = [f"{element['dispatch']}: {element['unreadable']}" for element in chain if element["unreadable"]]
    if broken:
        raise PlanUnreadable("the plan review chain cannot be read (" + "; ".join(broken) + "); expected a form and a receipt "
                             "for every accepted review; the critic completes the form, `finish` stamps the receipt")
    out = []
    for position, element in enumerate(chain):
        last = position == len(chain) - 1
        out.extend(r for r in element["remarks"] if r["kind"] == "remark" or last)
    return out + case_concerns(task_root, state)


def _case_critic_files(state) -> dict:
    """`{findings file (story-relative path parts): [(sha256, review dispatch id)]}`: the accepted S4 case-critic rounds, in the
    order they were accepted, grouped by the file their receipt measured."""
    import controller as CT
    files = {}
    for record in _dispatches(state).values():
        if not (isinstance(record, dict) and record.get("stage") == "S4" and record.get("role") == "qa-case-critic"
                and record.get("status") == "accepted"):
            continue
        for ref, _area in CT.Controller._findings_refs(record):
            key = tuple(part for part in str(ref.get("path") or "").replace("\\", "/").split("/") if part not in ("", "."))
            files.setdefault(key, []).append((str(ref.get("sha256") or ""), str(record.get("id") or "")))
    return files


def _concern_remark(number, case, check, problem, expected, fix, review) -> dict:
    """A concern as a remark of the chain's shape (nine keys, no `test` / `then`)."""
    return {"id": f"CC-{number}", "case": case, "test": None, "then": None, "kind": "remark", "check": check,
            "problem": problem, "expected": expected, "fix": fix, "review": review}


def _file_concerns(key, rounds, root, number) -> list:
    """The remarks of ONE findings file, numbered from `number`. Per case, the LATEST accepted round that lists it decides
    (AR-21): a later round over fewer cases never drops the concerns of a case only an earlier round reviewed, and a later
    round that lists the case with no concern supersedes the earlier one's. An unreadable file is a global remark (FR-59:
    nobody reads stderr; case None goes to every window)."""
    import critic_rollcall as CR
    where = "/".join(key)
    try:
        path = (root / where).resolve()
        path.relative_to(root)
        data = path.read_bytes()
    except (OSError, ValueError):
        return [_concern_remark(number, None, "case critic, S4",
                                f"the case critic's findings file {where} cannot be read, so its concerns are not carried to "
                                "automation",
                                "read that file yourself before automating, or say in `plan_remarks` why it does not apply",
                                "", rounds[-1][1])]
    read = CR.accepted_rounds(data, rounds, root)
    latest = {case: position for position, one in enumerate(read) for case in one["listed"]}
    out = []
    for position, one in enumerate(read):
        for item in one["concerns"]:
            if latest.get(str(item["case"])) == position:
                out.append(_concern_remark(
                    number + len(out), _ref(item["case"]), "case critic, S4", item["problem"],
                    f"the case critic's full finding is in {where}, round {item['review']}; take it into account when the case "
                    "is automated, or say in `plan_remarks` why it does not apply", item["fix"], item["review"]))
    return out


def case_concerns(task_root, state) -> list:
    """The concerns of the case critic that travel to the automator (HF4-11), as remarks of the chain's shape: one per
    `approve_with_concerns` row, per case from the LATEST accepted S4 case-critic round of the findings file that lists the
    case (`critic_rollcall.accepted_rounds`: THE reader of a round; this is the one place that groups the rounds by file;
    a later round with no concern on a case supersedes the earlier one's).
    Nine keys like any remark (`kind: remark`, the case it names, no `test` / `then`), so `_placement` puts it in the window of
    its case and C12 asks the automator for a `plan_remarks` row (`applied` / `not_applicable`). `expected` names the findings
    file and the round (the full finding is there); `fix` is the critic's own `fix` cell of the row, '' when it wrote none.
    `CC-n` is numbered across the files in the order the dispatches were accepted. A file that cannot be read becomes a global
    remark naming it (never a concern from bytes the receipt did not measure; a round whose receipt does not match carries
    nothing and stderr says why). Gate A's line "Concerns carried to automation" reads this too."""
    root, out = Path(task_root).resolve(), []
    for key, rounds in _case_critic_files(state).items():
        out.extend(_file_concerns(key, rounds, root, len(out) + 1))
    return out


def remark_rows_missing(remarks, rows) -> list:
    """The ids of the remarks that do not have EXACTLY one row in `rows` (the window form's `plan_remarks`): none, or two. THE
    one implementation of the fact "a row for every remark" (AR-15): the window's detector calls it. `rows` that is not a list
    has no rows. An id is named once, in the order of `remarks`."""
    counts = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("id") is not None:
            key = str(row["id"]).strip()
            counts[key] = counts.get(key, 0) + 1
    missing = []
    for remark in remarks or []:
        identifier = str(remark.get("id") if isinstance(remark, dict) else remark).strip()
        if counts.get(identifier, 0) != 1 and identifier not in missing:
            missing.append(identifier)
    return missing


def _placement(remark, window_of, tests):
    """`(windows, how)` for a remark: the windows its `case` / `test` / `then` point at, and `how` - `window` (it points at
    cases of the plan), `global` (it points at nothing: it goes to EVERY window, E10) or `unplaced` (it names a case, a test
    or a Then the plan does not have: it also goes to every window - a remark is never lost for want of a place, AR-28).
    `window_of` is `{case: window number}` of the controller's cut (the plan holds no window); a case it does not have is lost."""
    if remark.get("case") is None and remark.get("test") is None and remark.get("then") is None:
        return set(), "global"
    cases, lost = _remark_cases(remark, tests_cases({"tests": tests}))
    windows = set()
    for case in cases:
        window = window_of.get(case)
        if window is None:
            lost = True
        else:
            windows.add(window)
    return windows, ("unplaced" if lost or not windows else "window")


def _settled_lines(task_root, plan_rows, mapping, cases) -> dict:
    """`{case: line}` for the asked cases whose approved plan row is `oracle_unknown` and names questions (`question_refs`): the
    plan is NEVER written (the person approved it) - the READER derives what the person has since answered (HF4-9, F-4). The one
    answered-reader is `gate_brief.answered_questions` (AR-13: `question_register` + `question_register.closes`); the text of an
    answer is `question_register.answer_text`. Every ref answered: `expected value settled by the person (Q7): <words WHOLE>
    [answers file: <path>]` (several: `Q7: words; Q8: words`) - this is the value the automator asserts, so it is never cut
    short of `brief_pack.person_words_whole` (whole up to its maximum, then a cut that says so and names the file); some ref
    not answered: `expected value not settled yet; unanswered: Q8` and no settled claim. The register absent or unreadable, or the
    answers file absent or not read in full: no line (today's brief; an unknown is not a fact, FR-41/AR-28)."""
    out = {}
    wanted = {}
    for case in cases:
        row = plan_rows.get(str(mapping.get(case)))
        refs = [str(q) for q in (row or {}).get("question_refs") or [] if str(q).strip()] if isinstance(row, dict) else []
        if isinstance(row, dict) and row.get("oracle_unknown") is True and refs:
            wanted[case] = refs
    if not wanted:
        return out
    try:
        import brief_pack as BP
        import gate_brief as GB
        import question_register as QR
        view = QR.load(task_root)
        if not view.get("register_present") or not view.get("questions"):
            return out
        answered = GB.answered_questions(task_root, view)
    except Exception:       # an unreadable register or answers file is today's brief, never a claim
        return out
    if answered.get("unreadable"):
        return out
    by_id = {str(i.get("id")): i for i in answered.get("items") or []}
    holder = f"qa-factory/artifacts/{Path(task_root).name}/" + "/".join(QR.ANSWERS_REL)

    def words(item) -> str:
        text, _is_words = QR.answer_text(item)
        return BP.person_words_whole(text or "answered, no words recorded", None, holder)

    for case, refs in wanted.items():
        open_refs = [q for q in refs if q not in by_id]
        if open_refs:
            out[case] = "expected value not settled yet; unanswered: " + ", ".join(open_refs)
        else:
            out[case] = ("expected value settled by the person (" + ", ".join(refs) + "): " + "; ".join(
                (f"{q}: " if len(refs) > 1 else "") + words(by_id[q]) for q in refs) + f" [answers file: {holder}]")
    return out


def window_slice(task_root, n=None, state=None, cases=None) -> dict:
    """The part of the plan that a window is written against: `{window, windows, asked, cases, missing, tests, remainders,
    requirements, remarks, surface, size, over_cap, cap, grown}`. Exactly ONE of `n` (a window number) and `cases` (the cases of
    a dispatch) is given, else ValueError. The plan holds no window: the windows are the controller's cut
    (`controller.s5_windows_for`), read here once, so the slice of a window and the cut a dispatch is refused by are one fact.

    `asked` are the cases of the slice (the window's scope for `n`); `window` is `n`, or for `cases` the number of the window that
    holds ALL of them, else None (cases over two windows have no number). `cases` are the plan's rows of the asked cases, in the
    order asked; `missing` the asked cases the plan has no row for (shown as "(not in the plan)"); `tests` those whose `cases`
    touch an asked case (a shared test appears once); `remainders` the cases' remainders (flat, with the case); `requirements`
    the union of the cases' in order; `remarks` the review's remarks (`remarks_of`), each with a `placement`: the ones that point
    at cases go to the windows those cases are in, the global ones and the ones that name nothing the plan has go to every
    slice. `surface`, `size` (the cases the window holds), `over_cap`, `cap` and `grown` are the window's own words in the cut
    (`over_cap` False, `cap` None and `grown` [] for no window). Window `n` the cut does not have is a ValueError naming the
    windows it has. `state` is the controller's projection; None reads it (the CLI's case)."""
    if (n is None) == (cases is None):
        raise ValueError("window_slice takes exactly one of `n` (a window number) and `cases` (the cases of a dispatch); "
                         "expected e.g. window_slice(root, 2) or window_slice(root, cases=['TC-1', 'TC-2'])")
    plan = load(task_root)
    if plan is None:
        raise PlanUnreadable(f"{PLAN_REL} does not exist, so there is no slice of it; expected the author's plan; run "
                             f"`python scripts/s5_plan.py --task {Path(task_root).resolve().name} --init`")
    import controller as CT
    controller = CT.Controller(task_root)
    real = controller.state()
    state = real if state is None else state
    try:
        # the scope and the case -> S3 row map are the story's own; `state` is read for the windows already written
        mapping, dispositions, _basis = controller._case_rows(real)
        scope = controller._cases_by_disposition(mapping, dispositions)["automate"]
        windows, _cut = controller.s5_windows_for(plan, state, scope, mapping)
    except Exception as exc:      # the cut reads the state, the config and the plan: an unreadable one is a refusal, not a slice
        raise PlanUnreadable(f"the windows cannot be cut ({_show(exc, 120)}), so there is no slice of the plan; expected a readable "
                             f"story state and plan; run the controller's `recover` operation, then ask again") from exc
    numbers = [window["index"] for window in windows]
    window_of = {str(case): window["index"] for window in windows for case in window.get("scope") or []}
    if n is not None:
        window = next((w for w in windows if w["index"] == n), None)
        if window is None:
            raise ValueError(f"the plan has no window {n}; expected one of {', '.join(str(w) for w in numbers) or '(none)'}")
        asked = [str(case) for case in window.get("scope") or []]
    else:
        if not isinstance(cases, (list, tuple)):
            raise ValueError("window_slice: `cases` must be a list of case ids; expected e.g. ['TC-1', 'TC-2']")
        asked = list(dict.fromkeys(str(case) for case in cases))
        owners = {window_of.get(case) for case in asked}
        window = next((w for w in windows if w["index"] in owners), None) if len(owners) == 1 and None not in owners else None
    rows = {str(row["case"]): row for row in _rows(plan, "cases") if row.get("case") is not None}
    own = [rows[case] for case in asked if case in rows]
    tests = [test for test in _rows(plan, "tests") if any(str(c) in asked for c in test.get("cases") or [])]
    reach = {window_of[case] for case in asked if case in window_of}
    remarks = []
    for remark in remarks_of(task_root, state):
        places, how = _placement(remark, window_of, _rows(plan, "tests"))
        if how != "window" or places & reach:
            remarks.append(dict(remark, placement=how))
    requirements = list(dict.fromkeys(str(r) for row in own for r in row.get("requirements") or []))
    remainders = [dict(r, case=str(row.get("case"))) for row in own for r in _rows(row, "remainders")]
    held = window or {}
    try:
        plan_rows = {str(r.get("id")): r for r in controller._plan_rows() or [] if isinstance(r, dict)}
        settled = _settled_lines(task_root, plan_rows, mapping, [str(r.get("case")) for r in own])
    except Exception:
        settled = {}
    return {"settled": settled, "window": window["index"] if window else None, "windows": numbers, "asked": asked, "cases": own,
            "missing": [case for case in asked if case not in rows], "tests": tests, "remainders": remainders,
            "requirements": requirements, "remarks": remarks, "surface": held.get("surface"), "size": len(held.get("scope") or []),
            "over_cap": bool(held.get("over_cap")), "cap": held.get("cap") if held.get("over_cap") else None,
            "grown": list(held.get("grown") or [])}


def render_slice(piece) -> str:
    """The slice as markdown (the brief of a window reads it; `--out` writes it). Every empty part says so (AR-23). A window over
    its cap and a window that grew after the plan review say so in a line each, under the cases (the role must know, AR-10)."""
    head = (f"# S5 plan - window {piece['window']} of {len(piece['windows'])}" if piece["window"] is not None else
            "# S5 plan - cases " + (", ".join(piece["asked"]) or "(none)"))
    shown = [f"{case} (not in the plan)" if case in piece["missing"] else case for case in piece["asked"]]
    lines = [head, "", "Cases: " + (", ".join(shown) or "(none)")]
    if piece["over_cap"]:
        tying = tests_tying(piece["tests"], piece["asked"])
        lines.append(f"This window holds {piece['size']} cases, over the {piece['surface']} window cap of {piece['cap']}"
                     + (f": test(s) {', '.join(tying)} cover them together, and a test is written in one window." if tying else "."))
    if piece["grown"]:
        lines.append(f"This window grew by {', '.join(str(c) for c in piece['grown'])} after the plan review: add their tests, "
                     "keep what stands.")
    lines += ["", "## Requirements", ", ".join(piece["requirements"]) or "none named by S3 for these cases", "", "## Cases"]
    for row in piece["cases"]:
        s3 = row.get("s3") if isinstance(row.get("s3"), dict) else {}
        lines += ["", f"### {row.get('case')} (S3 row {s3.get('row')}; level {s3.get('level')}; fit {s3.get('fit')}; "
                      f"oracle {s3.get('oracle')})"]
        note = (piece.get("settled") or {}).get(str(row.get("case")))
        if note:
            lines.append(note)
        lines += [f"{t.get('n')}. {t.get('text')}" for t in _rows(row, "thens")] or ["(no Then clause)"]
    lines += ["", "## Remainders (left to a person)"]
    lines += [f"- {r['case']} Then {r.get('then')}: {r.get('reason')} - {r.get('detail')}" for r in piece["remainders"]] or ["none"]
    lines += ["", "## Tests"]
    if not piece["tests"]:
        lines.append("no tests planned for this window: write the remainders")
    for test in piece["tests"]:
        lines += ["", f"### {test.get('id')} - {test.get('file')}::{test.get('function')} ({test.get('shape')}, {test.get('level')}, "
                      f"data {test.get('data')})",
                  f"cases: {', '.join(str(c) for c in test.get('cases') or [])}; asserts: {', '.join(str(t) for t in test.get('thens') or [])}"]
        if test.get("extends"):
            lines.append(f"extends: {test['extends']}")
        if test.get("consolidates"):
            lines.append(f"consolidates: {', '.join(str(t) for t in test['consolidates'])}")
        if test.get("uses"):
            lines.append(f"uses: {', '.join(str(f) for f in test['uses'])}")
        if isinstance(test.get("apart_reason"), str) and test["apart_reason"].strip():
            lines.append(f"apart_reason: {test['apart_reason']}")      # a window reads why this test stands apart (AR-21)
        lines.append(f"assert: {test.get('assert')}")
        lines += [f"deviation ({d.get('from')}): {d.get('reason')}" for d in _rows(test, "deviation")]
    lines += ["", "## Remarks (plan review and case critic)"]
    for remark in piece["remarks"]:
        where = ", ".join(f"{key} {remark[key]}" for key in ("case", "test", "then") if remark.get(key)) or "the whole plan"
        lines += [f"- {remark['id']} [{remark['kind']}] {where} ({remark['check']}; {remark['placement']}): {remark['problem']} "
                  f"Expected: {remark['expected']}" + (f" Fix: {remark['fix']}" if str(remark.get("fix") or "").strip() else "")]
    if not piece["remarks"]:
        lines.append("no remarks for this window")
    return "\n".join(lines) + "\n"


def check(task_root, controller, files=True) -> list:
    """The findings of `check_report` - the gaps of the plan, all at once, as one-line strings (empty: none). What could not
    be checked is in `check_report(...)[1]`. `files=False` is the window gate's: see `check_report`."""
    return check_report(task_root, controller, files)[0]


# --- the grouping hint (advice about the shape the author chose, never a finding) ------------------------

# The shapes whose tests are candidates of the hint: a test that extends or reuses an existing test, or consolidates, is not
# one more new test of a file.
GROUP_SHAPES = ("new", "parameterize")
GROUP_IDS_SHOWN = 4
HINT_ADVICE = ("The hint above is advice about the shape you chose, not a repair: take it or answer it in the test's "
               "`apart_reason`.")
NO_PLAN = "no plan"
_GROUP_FIX = ("if they share setup and action, write one parameterized test: the data and the expected value from each case's "
              "oracle are its parameters, each parameter id naming its case; keep a test apart only for another setup, "
              "surface or fixture, in its `apart_reason`")


def _candidate(test) -> bool:
    """Is this row of `tests[]` a candidate of the grouping hint: a mapping with a shape of `GROUP_SHAPES`, a level of the
    vocabulary, a text `file`, a non-empty list of text `cases`, and no reason to stand apart. A reason that is blank (or
    absent, or null) is no reason; one that is not text is a finding of the plan check and the test is left out here."""
    if not isinstance(test, dict) or test.get("shape") not in GROUP_SHAPES or not isinstance(test.get("shape"), str):
        return False
    if not isinstance(test.get("level"), str) or test["level"] not in C.PLAN_LEVELS:
        return False
    if not isinstance(test.get("file"), str):
        return False
    cases = test.get("cases")
    if not isinstance(cases, list) or not cases or not all(isinstance(case, str) for case in cases):
        return False
    reason = test.get("apart_reason")
    return reason is None or (isinstance(reason, str) and not reason.strip())


def grouping_hints(plan, file_key=None) -> list:
    """`[{case, message, fix, tag}]`: the tests of one level in one file that each prove their own case(s) - one row per group of
    at least two tests that between them name at least two cases. Neutral rows: the caller gives them the form of its report
    (`s5_precheck._hint`, a printed `hint:`). An ADVISER, never a gate (FR-47): it counts nothing against the author, reads no
    wording (the `apart_reason` is judged by the plan critic, only its presence is read here) and returns `[]` for anything it
    cannot read. The file of a test is compared by `s5_precheck._file_key` (AR-13), or by the `file_key` function given."""
    tests = plan.get("tests") if isinstance(plan, dict) else None
    if not isinstance(tests, list):
        return []
    if file_key is None:
        from s5_precheck import _file_key as file_key       # lazy: that module reads this one lazily too
    groups = {}
    for test in tests:
        if _candidate(test):
            key = file_key(test["file"])
            if key:
                groups.setdefault((test["level"], key), []).append(test)
    rows = []
    for (level, key), members in groups.items():
        cases = list(dict.fromkeys(case for test in members for case in test["cases"]))
        if len(members) < 2 or len(cases) < 2:
            continue
        ids = [str(test.get("id")) for test in members]
        more = f", +{len(ids) - GROUP_IDS_SHOWN} more" if len(ids) > GROUP_IDS_SHOWN else ""
        digest = hashlib.sha1("\n".join(sorted(ids)).encode("utf-8")).hexdigest()[:8]
        rows.append({"case": cases[0], "tag": "group-" + digest, "fix": _GROUP_FIX,
                     "message": f"{len(members)} tests at level {level} in {key} each prove their own case(s) "
                                f"({', '.join(ids[:GROUP_IDS_SHOWN])}{more}): {', '.join(cases)}"})
    return rows


def plan_for_hints(task_root) -> tuple:
    """`(plan | None, why)`: THE one reader of the plan for the hints (AR-13). No file is `(None, "no plan")`; a plan that cannot be
    read, or any other exception of the read, is `(None, "<Type>: <message>")`. Never raises: a hint is advice, and the plan check
    already refuses what it cannot read (AR-28)."""
    try:
        plan = load(task_root)
    except Exception as exc:        # noqa: BLE001 - whatever the read does, the answer is "no plan for the hints" with the words
        return None, f"{type(exc).__name__}: {_show(exc, 100)}"
    return (plan, "") if plan is not None else (None, NO_PLAN)


def hint_rows(task_root) -> tuple:
    """`(rows, why)`: the grouping hints of the plan on disk, and `why` = "" when they were computed (even to none) or when there
    is no plan to compute them from because the plan check already says so (absent, or `PlanUnreadable`); otherwise the words of
    what failed - the caller says "not checked", never a pass and never a crash (AR-28)."""
    plan, why = plan_for_hints(task_root)
    if plan is None:
        return [], ("" if why == NO_PLAN or why.startswith(PlanUnreadable.__name__ + ":") else why)
    try:
        return grouping_hints(plan), ""
    except Exception as exc:        # noqa: BLE001
        return [], f"{type(exc).__name__}: {_show(exc, 100)}"


def print_hints(hints) -> None:
    """The one printer of `hint:` lines, shared by `--check` here and `s5_precheck.report`: the same hint prints the same line
    on both paths, every text one line (AR-18)."""
    for hint in hints or []:
        print(f"hint: [{hint.get('check') or 'plan'}] {_line(hint['message'])}")
        print(f"  consider: {_line(hint['fix'])}")


def main() -> int:
    C.force_utf8()
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--task", required=True, help="ticket id")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--init", action="store_true", help="write the skeleton work/s5-plan.json (a plan on the same cases is kept)")
    what.add_argument("--mode", action="store_true", help="print the form of this story's S5: planned or legacy")
    what.add_argument("--check", action="store_true", help="name every gap of the plan at once (exit 1: findings; 0: none)")
    what.add_argument("--window", type=int, metavar="N", help="print the plan's slice for window N as markdown")
    ap.add_argument("--out", metavar="FILE", help="with --window: write the slice to FILE instead of printing it")
    ns = ap.parse_args()
    if ns.out and ns.window is None:
        ap.error("--out belongs to --window N")
    try:
        task_root = hooklib.story_root(ns.task, "s5_plan.py --task")
        import controller as CT
        controller = CT.Controller(task_root)
        if ns.mode:
            form, why = mode(task_root, controller.state())
            print(json.dumps({"mode": form, "why": why}, ensure_ascii=False))
            return 0
        if ns.check:
            findings, notes = check_report(task_root, controller)
            hints, why = hint_rows(task_root)      # advice: never changes the findings, the verdict or the exit code
            if why:
                notes.append(f"not checked: the grouping hints of the plan ({why})")
            for note in notes:
                print(f"note: {_line(note)}")
            print_hints(hints)
            if not findings:
                print(f"OK: the plan has no gap ({len(notes)} thing(s) not checked, named above)." + (" " + HINT_ADVICE if hints else ""))
                return 0
            print(f"REJECT — {len(findings)} finding(s) in the S5 plan for the author before the code critic:")
            for finding in findings:
                print("- " + finding)
            print(f"Repair the rows named above in {PLAN_REL}, then run `python scripts/s5_plan.py --task {ns.task} --check` again.")
            return 1
        if ns.window is not None:
            text = render_slice(window_slice(task_root, ns.window, controller.state()))
            if not ns.out:
                sys.stdout.write(text)
                return 0
            target = Path(ns.out)
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = target.with_name(target.name + ".tmp")
            staging.write_text(text, encoding="utf-8")
            os.replace(staging, target)
            print(json.dumps({"path": str(target), "window": ns.window, "bytes": len(text.encode("utf-8"))}, ensure_ascii=False))
            return 0
        plan = init(task_root, controller)
        print(json.dumps({"path": PLAN_REL, "cases": len(plan.get("cases") or []),
                          "scope_hash": plan.get("scope_hash")}, ensure_ascii=False))
        return 0
    except ValueError as exc:    # PlanUnreadable, StoryRootError: the call's own fault or the plan's, with its door in the text
        print(f"s5_plan: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
