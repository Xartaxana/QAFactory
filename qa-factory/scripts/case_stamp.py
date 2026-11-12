#!/usr/bin/env python3
"""Stamp a case `Automated` by code, once its own manifest evidence proves it — nobody else
has a legal path (`validate_artifacts.py`'s state-machine gate: `status: Automated` is only
legal together with `red_probe` and `automated_by`).

TP1-15045: the manifest carried fifteen `critic_verdict: approved` green instances with
published sensitivity proofs, and not one case file's frontmatter ever said `Automated` —
nothing wrote the transition, so the coverage map and every later ledger read those cases as
still `Approved`, undone work sitting beside a green, reviewed suite. `critic_rollcall.py
--apply-fixes` already does this for the case critic's exact-text fixes (S4): the critic
decides, code writes the fact, no role dispatch in between. This is the same shape for the
code critic's verdict — the transition is a fact function of `automation-manifest.json`, not
a step anyone remembers to perform.

The unit is the CASE (RH1-8, AR-13): `case_hold` is the one answer to "does this case hold" - `""` only when every live
instance of the case (`_case_population`: the instances whose keys answer to the case under `contract.case_matches`, a bare
number matching any area, an instance with no case field belonging to the case its id prefix names) has an empty
`instance_hold`; a case with no live instance holds as `no_automation_evidence`, never as a pass. `plan`, the coverage map
(`check_coverage.collect_cases`) and gate B (`check_delivery._cases_held`, through `held_case_links`) ask it, and a row of
`unresolved[]` is read through the same matcher.

A case stamps only when EVERY live instance covering it passes `instance_hold` (HF3-1: the ONE
predicate the stamp, the coverage map and gate B's lifecycle reasons all ask): `status: green` in
the manifest AND a GREEN result row of its own in `run-report.json` (t-415: the run outranks the
manifest's word, so a red row holds it, `red_run_for`, the join the table reads too, t-419; HF3-1:
the manifest's green is the automator's word before the run, so no row, `skipped`, `partial` or a
word nobody knows holds it as well, `run_row_for` - FR-59, FR-18), and `critic_verdict` `approved`
or `approved_with_fixes`. A dead instance (`SUPERSEDED DUPLICATE`) is no instance of its case: it
neither holds nor stamps. The case also carries red-probe evidence (the canonical `sensitivity_proof.receipt_ref`, or
the S5 window shape the live pipeline writes today — a `probe` block of a known proof level
(`proof_level.level_of`) with a hashed `evidence_ref`, or a `proven` `obligation_bindings[]`
entry). A case named in
`unresolved[]` — for any reason, `handed_to_person` included — is left alone: `Automated`
states the WHOLE case is proven, and a case with an open partition is not that, whatever
fraction of it already is. The case file this writes is the one the story PINS
(`case_versions` link -> its authoring source), never the immutable snapshot, and every write
is followed by a fresh immutable version and re-pin so the snapshot chain stays intact — the
same two steps `critic_rollcall.apply_fixes` takes for a case-text repair.

    case_stamp.py --task-root <TASK_ROOT> [--dry-run] [--store <STORE>]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import external_writes as W  # noqa: E402
import proof_level  # noqa: E402
import run_history as RH  # noqa: E402  (RED_STATUSES: the one red pair; an import failure is loud, never "no red run")
import hooklib  # noqa: E402
from hooklib import parse_frontmatter  # noqa: E402
from critic_rollcall import project_root_of as _project_root  # noqa: E402  (the ONE marker walk up to qa-factory/config.json; None when there is none)

# Case identity: the area-aware spelling when this build carries it (two areas sharing
# TC-NNN numbers — a helper another package owns), the bare id otherwise. A build without it
# yet must stamp exactly as every build before it did.
_CASE_KEY = getattr(C, "case_key", None)
_MANIFEST_TEST_KEYS = getattr(C, "manifest_test_keys", None) or C.manifest_test_links


def is_red_row(row) -> bool:
    """Did the run observe this current result row RED? `failed` / `error` (`run_history.RED_STATUSES`), or - t-419 F3 - a
    row the reducer overwrote to `partial` because it could not join it to a manifest row (`finalize_task`, R-208.3): that
    overwrite keeps what the run said in `raw_status`, and a `raw_status` that is red is a red run, read exactly as
    `check_delivery.case_ownership` reads it (a `partial` with no red `raw_status` is not red; a row the reducer superseded
    is history, not the run's current word). Not an object: not red."""
    if not isinstance(row, dict):
        return False
    word = C.result_status(row)
    if word in RH.RED_STATUSES:
        return True
    return (word == "partial" and not row.get("superseded")
            and C.result_status({"status": row.get("raw_status")}) in RH.RED_STATUSES)


def _tid(row: dict) -> str:
    return str(row.get("test_id") or row.get("test") or "").strip()


def _worse(row: dict, other: dict | None) -> bool:
    """Is `row` a worse reading of "did it pass" than `other`? Red, then any word that is not green (`skipped`, `partial`,
    unknown), then green. None is worse than nothing, so the first row of a group always wins."""
    if other is None:
        return True
    rank = lambda r: 0 if is_red_row(r) else 2 if C.result_status(r) == "passed" else 1  # noqa: E731
    return rank(row) < rank(other)


def _base_aliases(alias: dict, worst: bool) -> dict:
    """`x` -> a row of `x[a]`, `x[b]` ... : the alias keys with a `[param]` group cut off. `worst=False` keeps the first row
    (the red rows are all red, which one is the same answer); `worst=True` keeps the row that reads worst, so the order the
    report lists the parameters in cannot turn `x[a]` passed + `x[b]` skipped into a pass (HF2-6)."""
    out: dict = {}
    for key, row in alias.items():
        cut = key.find("[")
        if cut > 0 and key.endswith("]"):
            base = key[:cut]
            if base not in out or (worst and _worse(row, out[base])):
                out[base] = row
    return out


def _ambiguous_tails_dropped(alias: dict, rows: list) -> dict:
    """`alias` without the keys that are only the `::` tail of SEVERAL rows' test ids: `a.py::TestA::t` and `a.py::TestB::t`
    both answer to `t`, and a tail two tests share is no test's own spelling (HF2-6, critic t-118). A tail that is also some
    row's whole `instance_id` / test id stays: that row spelled it itself."""
    whole = {str(r.get("instance_id") or "").strip() for r in rows} | {_tid(r) for r in rows}
    tails: dict = {}
    for row in rows:
        tid = _tid(row)
        if "::" in tid:
            tails.setdefault(tid.split("::")[-1], set()).add(tid)
    shared = {tail for tail, ids in tails.items() if len(ids) > 1 and tail not in whole}
    return {key: row for key, row in alias.items() if key not in shared}


def _legacy_rows(rows: list, entries, cfg) -> dict:
    """case -> its ONE current row, for the cases that have exactly one live manifest entry AND exactly one current row: the
    only join a 0.10.x story has, whose entry carries no identity of its own (`contract.legacy_identity_is_the_case`) and
    whose row carries the case. Two entries or two rows of a case join nothing: the case is not one test's name."""
    if not entries:
        return {}
    wanted: dict = {}
    for entry in entries:
        if isinstance(entry, dict):
            for case in {str(entry.get("case") or "").strip(), *C.manifest_test_links(entry, cfg)} - {""}:
                wanted[case] = wanted.get(case, 0) + 1
    by_case: dict = {}
    for row in rows:
        for case in C.case_ids(row.get("case"), cfg=cfg):
            by_case.setdefault(case, []).append(row)
    return {case: found[0] for case, found in by_case.items() if len(found) == 1 and wanted.get(case) == 1}


def run_rows_index(results, entries=None, cfg=None) -> dict:
    """The run's CURRENT result rows (`contract.current_instance_results`: key -> row) prepared for the joins `red_run_for`
    (is the instance red) and `run_row_for` (what did the run record for it). A row marked `stale` and a row the product
    set leaves out (`contract.product_result_rows`: a red probe, a diagnostic or baseline run) is no record of the instance's
    run and is dropped here, once, for both.

    `rows` / `red` (key -> row); the alias maps the dashboard's own `run_rows_by_alias` makes - over the red rows
    (`red_alias`), over every row (`all_alias`: the "does the instance have a row of its own" test of edge 3), the same
    without the `::` tails that several tests share (`join_alias`: `run_row_for` step 2), and over the rows with a `[param]`
    group cut off every spelling (`red_base_alias`: the first red row; `all_base_alias`: the worst row, edge 3). `legacy` is
    the case -> row map of `run_row_for` step 4, built only when the live manifest `entries` are given. The dashboard is
    imported HERE and not guarded: with no row nothing is imported and nothing can be wrong; with one, a build that cannot
    load the dashboard fails loud instead of reading "no red run" and passing what it should hold (t-419, FR-59)."""
    raw = results if isinstance(results, dict) else {}
    rows = {str(key): row for key, row in raw.items()
            if isinstance(row, dict) and not row.get("stale") and C.product_result_rows({"results": [row]})}
    red = {key: row for key, row in rows.items() if is_red_row(row)}
    index = {"rows": rows, "red": red, "red_alias": {}, "all_alias": {}, "join_alias": {}, "red_base_alias": {},
             "all_base_alias": {}, "legacy": {}, "cfg": cfg}   # `cfg`: the resolved config the joins reuse (B-013), None = resolve as before
    if rows:
        import factory_dashboard as FD
        everything = list(rows.values())
        if red:
            index["red_alias"] = FD.run_rows_by_alias({"current_results": list(red.values())})
            index["red_base_alias"] = _base_aliases(index["red_alias"], worst=False)
        index["all_alias"] = FD.run_rows_by_alias({"current_results": everything})
        index["join_alias"] = _ambiguous_tails_dropped(index["all_alias"], everything)
        index["all_base_alias"] = _base_aliases(index["join_alias"], worst=True)
        index["legacy"] = _legacy_rows(everything, entries, cfg)
    return index


def run_rows_of(task_root: Path, manifest: dict | None = None) -> dict:
    """`run_rows_index` of this story's `run-report.json`. Never raises over the REPORT: absent, unreadable, not an object,
    wrong-typed fields all read as "no run result" (`instance_hold` turns that into `not_run`, never into a green: FR-41,
    FR-59). With the story's `manifest` the index carries its LIVE entries (`traceability.live_tests`) and the case config, so
    the legacy step of `run_row_for` (an entry with no identity of its own) is alive - without it that step is dead and
    every 0.10.x story would read "not run" (HF3-1; the trace and the ledger build the index the same way). Without
    `manifest` the index is the red-only reader's (`stand_gaps`, `red_run_for`), which has no use for the legacy step."""
    try:
        results = C.current_instance_results(C.load_json(C.artifact(Path(task_root), "run-report.json")))
    except Exception:
        results = {}
    if manifest is None:
        return run_rows_index(results)
    from traceability import live_tests   # lazy: traceability imports this module; a build that cannot load it fails loud
    return run_rows_index(results, live_tests(manifest), C.case_config(Path(task_root)))


def run_report_unreadable(task_root: Path) -> bool:
    """Is there a `run-report.json` that cannot be read as an object - invalid JSON, undecodable bytes, an array or a bare
    word? That is "not read", not "not run" (FR-59: the gate names what it could not establish). An absent file is not this:
    nothing was run. `run_rows_of` reads both as "no result" because the join has no use for the difference; the stamp's
    `left` reason does."""
    path = C.artifact(Path(task_root), "run-report.json")
    if not path.is_file():
        return False
    try:
        return not isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except Exception:
        return True


def _is_bare(entry: dict, cfg=None) -> bool:
    """Does this manifest instance stand for the WHOLE test function? Yes when nothing on it names one parameter: no
    `parameter` / `parameters` / `parameter_map`, and no `[param]` group in any id spelling it carries (its instance id and
    aliases, `report_test_id`, `selector`, `test`, `marker`)."""
    if any(entry.get(field) for field in ("parameter", "parameters", "parameter_map")):
        return False
    names = list(C.instance_id_aliases(entry, cfg)) +[entry.get(field) for field in
                                                  ("report_test_id", "selector", "test", "marker")]
    return not any("[" in str(name) for name in names if name)


def red_run_for(entry: dict, index: dict):
    """The red run result row of this manifest instance, else None - THE one join (t-419, FR-17): `traceability` (the table),
    `case_stamp` (the stamp), `check_coverage` (the coverage map) and `check_delivery` (the lifecycle reasons) all ask here.
    In order:
      1. EXACT: one of the instance's own ids (`contract.instance_id_aliases`, the canonical id first) is the key of a red row.
      2. TOLERANT: the dashboard's own rule (`factory_dashboard.match_run_row`) over the RED rows - the instance's id
         aliases, `report_test_id` / `selector` / `test` / `marker` and their `::` tails against the rows' `instance_id`,
         `test_id` and tails. Whole spellings, the `[param]` group kept: `x[json]` is never `x[multi]`, and a bare `x` is never
         pulled to `x[json]` by a widening of the id (t-419 F1: the `same_id` widening of t-415 turned a passed
         `x[unparseable]`, whose `test` field is the bare function, red through a red sibling `x[json]`).
      3. WHOLE FUNCTION: an instance that names no parameter (`_is_bare`) and has NO run row of its own, of any status (the
         dashboard's rule over all rows finds none), stands for the function: any red parameter row `x[a]` of it reads red.
         This is how it differs from step 2's sibling case: an instance with a `parameter`, or with its own row (passed or
         not), is one parameter and a sibling's red is not its own.
    A row counts red by `is_red_row` (F3: a join-failed `partial` with a red `raw_status` too). Error direction: a match
    is a refusal to read the manifest's green as proof, a miss leaves the manifest's reading as it was - so a red row can
    only turn a reading red, never lift one. Empty or None ids on either side join nothing; no exception for them.
    The three steps are `_join` over the red rows; `run_row_for` runs the same steps over every row."""
    if not isinstance(entry, dict) or not isinstance(index, dict) or not index.get("red"):
        return None
    return _join(entry, index, "red")


# Which maps of the index each set of rows is joined through: (key -> row, alias map of step 2, `[param]`-cut map of step 3).
_JOIN_MAPS = {"red": ("red", "red_alias", "red_base_alias"), "all": ("rows", "join_alias", "all_base_alias")}


def _join(entry: dict, index: dict, which: str):
    """The three steps of `red_run_for` over ONE set of rows (`which`: `red` or `all`), so the red join and the run-record
    join cannot drift apart (AR-13). Exact id; the dashboard's tolerant rule; an instance that names no parameter and has no
    row of its own, of any status, standing for its whole function."""
    keyed, aliased, based = _JOIN_MAPS[which]
    blank = C.test_instance_id({})   # the id of a row that names nothing: a row with no ids keys to it too, and the two are not one test
    cfg = index.get("cfg")   # resolved once by the caller of `run_rows_index`; None resolves per call, as before
    for name in C.instance_id_aliases(entry, cfg):
        if name != blank and name in index[keyed]:
            return index[keyed][name]
    import factory_dashboard as FD
    row = FD.match_run_row(entry, index[aliased], cfg)
    if row is not None:
        return row
    if _is_bare(entry, cfg) and FD.match_run_row(entry, index["all_alias"], cfg) is None:
        return FD.match_run_row(entry, index[based], cfg)
    return None


def _qualifier(spelling: str) -> list:
    """The module (and class) part of a test id as dotted segments: `tests/a.py::TestA::t` and `tests.a::TestA::t` both give
    ['tests', 'a', 'TestA']. [] for a spelling with no `::`."""
    parts = str(spelling or "").strip().replace("\\", "/").split("::")
    if len(parts) < 2:
        return []
    path = parts[0]
    for ext in (".py", ".ts", ".js", ".cs", ".java"):
        if path.endswith(ext):
            path = path[:-len(ext)]
    return [seg for seg in path.replace("/", ".").split(".") if seg] + [seg for seg in parts[1:-1] if seg]


def _same_place(left: list, right: list) -> bool:
    """Can two qualifiers name one test? Equal, or one is a prefix of the other (a class the manifest did not name) or a
    suffix of it (a directory it did not name). `a.TestA` and `a.TestB`, `a` and `b` can not."""
    short, long = sorted((left, right), key=len)
    return long[:len(short)] == short or long[len(long) - len(short):] == short


def _is_neighbour(entry: dict, row: dict) -> bool:
    """Is `row` the row of ANOTHER test that shares the entry's function name? Only when both name a place (`a.py::...`) and
    no spelling of the entry's names the row's place: the id of a test is its function, but `a.py::TestA::t` and
    `a.py::TestB::t` are two tests (HF2-6, critic t-118). An entry or a row that names no place cannot be told apart and
    is not a neighbour here."""
    row_id = _tid(row)
    row_place = _qualifier(row_id)
    if not row_place:
        return False
    function = C.function_name(row_id)
    places = [_qualifier(str(entry.get(field) or "")) for field in ("report_test_id", "selector", "test", "marker")
              if C.function_name(entry.get(field)) == function]
    places = [place for place in places if place]
    return bool(places) and not any(_same_place(place, row_place) for place in places)


def run_row_for(entry: dict, index: dict):
    """The CURRENT run result row of this manifest instance - whatever its status - else None: the run recorded nothing for it.
    The one join "what did the run say about this test" (HF2-6, RD1-8): the table reads it (`pass` only with a green row)
    and the ledger reads it (`passed_green` only with a green row). In order: the three steps of `red_run_for` over EVERY
    row (`_join`), then the legacy step - an entry with no identity of its own (`contract.legacy_identity_is_the_case`),
    the only live entry of its case, and the only current row of that case: that row. A story written before instance ids
    carries no other join, and a second entry or a second row of the case makes the case no one test's name.
    Error direction, the reverse of `red_run_for`'s: a MISS reads as "not run", a MATCH can lift a reading to a pass - so
    a row of another test never matches: a `::` tail two tests share joins nothing, a row of `a.py::TestB::t` is not the
    row of `a.py::TestA::t` (`_is_neighbour`), and for a bare function with several parameter rows the worst one is
    returned whatever the order of the report. A stale row and the rows of a red probe, a diagnostic or a baseline run are
    not in the index at all (`run_rows_index`). Empty or None ids on either side join nothing; no exception for them."""
    if not isinstance(entry, dict) or not isinstance(index, dict) or not index.get("rows"):
        return None
    row = _join(entry, index, "all")
    if row is not None:
        return None if _is_neighbour(entry, row) else row
    if C.legacy_identity_is_the_case(entry):
        return (index.get("legacy") or {}).get(str(entry.get("case") or "").strip())
    return None


# The critic verdicts that approve (`handoffs/s5-critic-to-automator.yaml`: `approved_with_fixes` is a legal verdict). The
# stamp, the coverage map and gate B all read the same pair here; `report_facts.APPROVING` is its twin (a test holds them equal).
APPROVING = ("approved", "approved_with_fixes")
# Why an instance cannot carry its case's stamp, in the order the first one wins - the words `plan` prints after `left` / `why`.
NOT_GREEN, NOT_RUN, NOT_APPROVED = "not_green", "not_run", "not_approved"
HOLDS = (NOT_GREEN, NOT_RUN, NOT_APPROVED)


def instance_hold(entry: dict, index: dict) -> str:
    """`""` when this manifest instance can carry the stamp of its case, else the FIRST reason it cannot - THE one predicate
    (HF3-1, AR-13, AR-15) the stamp (`plan`), the coverage map (`check_coverage.collect_cases`) and gate B's lifecycle reasons
    (`check_delivery._cases_held`) all ask, so the three cannot disagree about "this case is proven green":
      `not_green`    the manifest's word is not `green`, or the run recorded this instance RED (`red_run_for`, or a red row the
                     legacy step found) - the run outranks the manifest's word (t-415);
      `not_run`      the manifest says `green` but the run holds no GREEN row of its own for it: no row at all, `skipped`,
                     `partial` without a red `raw_status`, a word nobody knows. The manifest's green is the automator's word
                     before the run, not an execution (FR-18); an unknown is no pass (FR-59);
      `not_approved` the critic's verdict is not in `APPROVING`.
    Error direction: this is a gate, so "hold" is the safe side - not stamping, not counting, not demanding a stamp is always
    allowed; counting a row of another test, or an unknown word, as green is not (`run_row_for` already refuses both). An entry
    that is not an object, or has no status, is `not_green`. A row without an entry (a test the manifest does not know) is
    never reached: the instance is the unit. Empty or None inputs join nothing and raise nothing."""
    if not isinstance(entry, dict) or entry.get("status") != "green" or red_run_for(entry, index) is not None:
        return NOT_GREEN
    row = run_row_for(entry, index)
    if is_red_row(row):
        return NOT_GREEN
    if row is None or C.result_status(row) != "passed":
        return NOT_RUN
    return "" if entry.get("critic_verdict") in APPROVING else NOT_APPROVED


NO_EVIDENCE = "no_automation_evidence"   # the reason of a case with no live instance at all (AR-23: the empty outcome is a hold)


def _plan_keys(entry, cfg) -> list:
    """The case keys one live manifest instance answers to - THE one rule `plan`, `case_holds` and the coverage map share
    (RH1-8, AR-13): `contract.manifest_test_keys`, and for an instance that names no case in a field, the case its id's legacy
    `TC-012::` prefix names (`contract.instance_case`) when there is one. Not an object: no keys. `cfg` is the story's case
    config, resolved once by the caller (B-013)."""
    if not isinstance(entry, dict):
        return []
    keys = [str(key) for key in _MANIFEST_TEST_KEYS(entry, cfg) if str(key).strip()]
    if not keys:
        # `instance_case(<id string>)` is the prefix step alone: with no key every cell is empty, so the field step has nothing to
        # add, and handing it the entry would resolve the project config again for each of them
        single = C.instance_case(C.test_instance_id(entry))
        keys = [single] if single else []
    return keys


def _population_of(keyed: list, key, cfg) -> list:
    """The instances of `keyed` (`[(entry, keys)]`) whose keys answer to `key` under `contract.case_matches` - the one matcher
    of a case (AR-15): a bare id on either side matches any area, two explicit areas match only when equal."""
    key = str(key or "").strip()
    if not key:
        return []
    return [entry for entry, keys in keyed if any(C.case_matches(key, one, cfg=cfg) for one in keys)]


def _case_population(live, key, cfg) -> list:
    """The LIVE instances (`traceability.live_tests`) that belong to the case `key` (RH1-8, R2). A dead row and anything that
    is not an object never belong to a case: they neither hold it nor prove it. An empty key asks nothing."""
    return _population_of([(entry, _plan_keys(entry, cfg)) for entry in live or [] if isinstance(entry, dict)], key, cfg)


def case_hold(entries, index) -> str:
    """`""` when EVERY instance of `entries` can carry its case's stamp (`instance_hold` empty for each), else the first reason in
    the order of `HOLDS` with the instances that have it (`not_green:a,b`) - THE one answer to "does this case hold" (RH1-8,
    AR-13): the unit of `Automated` is the whole case, so one clean instance never lends its pass to a sibling (FR-18). NO
    instance is not a pass: `no_automation_evidence`, never `""` (AR-23, AR-28; `all()` over nothing is True and is not asked).
    Error direction: a gate, so only toward "held". It names the reason words `instance_hold` returns and compares no verdict."""
    entries = [entry for entry in entries or []]
    if not entries:
        return NO_EVIDENCE
    held = [(C.test_instance_id(entry), instance_hold(entry, index)) for entry in entries]
    reason = next((hold for hold in HOLDS if any(why == hold for _, why in held)), "")
    if not reason:
        # a word `instance_hold` does not return today: still a hold, never a pass
        reason = next((why for _, why in held if why), "")
    if not reason:
        return ""
    return reason + ":" + ",".join(sorted({name for name, why in held if why == reason}))


def case_holds(manifest, index, cfg) -> dict:
    """`{case key: case_hold}` for every key a LIVE instance names (`_plan_keys`) - the dict form of the same answer. `cfg` is
    required: the caller resolves it ONCE per story (`contract.case_config`) and every matcher call here shares it (B-013)."""
    from traceability import live_tests   # lazy, unguarded: a build that cannot load it fails loud, never "no hold" (HF3-1)
    keyed = [(entry, _plan_keys(entry, cfg)) for entry in live_tests(manifest) if isinstance(entry, dict)]
    named = sorted({key for _, keys in keyed for key in keys})
    return {key: case_hold(_population_of(keyed, key, cfg), index) for key in named}


def held_case_links(manifest, index, cfg) -> set:
    """The bare case ids that at least one LIVE instance with a non-empty `instance_hold` names through `manifest_test_links` -
    exactly the set gate B asks (`check_delivery._cases_held`, RH1-8 R6): where the stamp is not given, gate B demands none.
    RAISES when the join cannot be built; the caller names what it could not establish (FR-59)."""
    from traceability import live_tests
    return {cid for entry in live_tests(manifest) if instance_hold(entry, index)
            for cid in C.manifest_test_links(entry, cfg)}


def case_group_key(case_id: str, area: str = "", cfg=None) -> str:
    """The key of one case. `cfg` is the STORY's config, resolved once by the caller (R3, B-013): without it the helper resolves
    the process project's config, which is the pre-RH1-8 behaviour and the wrong one for a custom `case_id_form`."""
    if _CASE_KEY:
        try:
            return _CASE_KEY(case_id, area, cfg=cfg)
        except Exception:
            pass
    return str(case_id)


def unresolved_keys(manifest, cfg=None) -> list:
    """`[(case key, reason)]` for every row of `unresolved[]` that names a case - THE one reader of those rows for the stamp's
    `plan` and the map's `collect_cases` (RH1-8 F1, AR-13, AR-15). A row with no case is skipped (it holds no case); the reason
    is `unresolved` when the row carries none. The key is read with the story's `cfg` (R3); the match is `case_matches`."""
    out = []
    for row in C.manifest_unresolved(manifest):
        cid = str(row.get("case") or "").strip()
        if cid:
            out.append((case_group_key(cid, str(row.get("area") or ""), cfg), str(row.get("reason") or "unresolved")))
    return out


def _case_source(task_root: Path, case_id: str, link: dict | None) -> Path | None:
    """The one authoring case file to edit — mirrors `critic_rollcall._resolve_source` (the
    S4 precedent this stamps by the same two steps): a pin's project-relative `source_path`
    (A20) first, a name search under the story's case directories for a pin from before that
    audit rule, and — a case with no pin at all, or a bare id two areas both answer to — a
    search by declared/derived id, resolved ONLY when it names exactly one file. Two matches
    stay unresolved rather than guessing which area's case this evidence belongs to
    (FB-2428-1's failure mode, on the write side instead of the read side)."""
    import case_versions as V
    if link:
        project_root = _project_root(task_root)
        rel = V.read_source_path(link)
        if rel and project_root:
            candidate = project_root / rel
            if candidate.is_file():
                return candidate
        name = str((link.get("store_provenance") or {}).get("source_name") or "")
        if name:
            matches = [s for s in V.discover_cases(task_root) if s.name == name]
            if len(matches) == 1:
                return matches[0]
    matches = [s for s in V.discover_cases(task_root)
              if C.case_id(s) == case_id or C.declared_case_id(s) == case_id]
    return matches[0] if len(matches) == 1 else None


def _sensitivity_receipt(entry: dict, manifest: dict, task_root: Path) -> str:
    """The red-probe evidence one green, approved instance names, whichever of the
    manifest's proof shapes it was written in. `''` when none of them is a real proof —
    never a guess, per the state machine this feeds (`red_probe` must name something real)."""
    # The row's receipt counts only when `proof_level.reached` says it holds for the test as it is
    # NOW (the BYTES RULE: raw bytes equal, or a comment-only change) - contract validity alone let a
    # receipt for old bytes stamp a changed test `Automated` (critic t-048 F2).
    got = proof_level.reached(entry, manifest, task_root)
    if got["level"] and got["ref"].get("path"):
        return str(got["ref"]["path"])
    probe = entry.get("probe")
    # Automated needs the check to be live or better: any level the vocabulary knows. A live
    # check's mutation is the assertion, so the old demand for `real_behavior` here would have
    # left every case proven by `probe_by_code.py` unstamped (D-0010).
    if isinstance(probe, dict) and proof_level.level_of(probe) is not None and probe.get("evidence_ref"):
        return str(probe["evidence_ref"])
    ids = {str(x) for x in (entry.get("obligation_ids")
                            or ([entry["obligation_id"]] if entry.get("obligation_id") else []))}
    for binding in manifest.get("obligation_bindings") or []:
        if (isinstance(binding, dict) and binding.get("sensitivity") == "proven"
                and str(binding.get("obligation_id")) in ids and binding.get("probe_receipt_ref")):
            return str(binding["probe_receipt_ref"])
    return ""


def plan(task_root: Path, manifest: dict | None = None) -> dict:
    """What would be stamped and where, resolved but not written — `--dry-run` and the real
    write share this one computation so the two can never report different cases."""
    task_root = Path(task_root)
    if manifest is None:
        manifest = C.load_json(C.artifact(task_root, "automation-manifest.json"))
    from traceability import live_tests   # lazy, unguarded: a build that cannot load it fails loud, never "no hold" (HF3-1)
    runs = run_rows_of(task_root, manifest)
    report_unreadable = run_report_unreadable(task_root)
    cfg = C.case_config(task_root)   # once per story (B-013): every matcher below shares it
    unresolved = unresolved_keys(manifest, cfg)   # (the row's case key, its reason) - read through `case_matches` (RH1-8 R4)
    # a dead row (`SUPERSEDED DUPLICATE`) is no instance of its case (HF3-1, critic t-1254 B1): `live_tests`
    keyed = [(entry, _plan_keys(entry, cfg)) for entry in live_tests(manifest) if isinstance(entry, dict)]
    by_case = {key for _, keys in keyed for key in keys}
    try:
        index = C.case_index(task_root)
    except Exception:
        index = {}
    try:
        links = {str(item.get("case_id")): item for item in C.story_case_links(task_root)
                if isinstance(item, dict)}
    except Exception:
        links = {}
    case_ids = sorted(set(index) | by_case | {key for key, _ in unresolved})
    ready, left = [], []
    for cid in case_ids:
        why_unresolved = {reason for key, reason in unresolved if C.case_matches(cid, key, cfg=cfg)}
        if why_unresolved:
            # A partial case (some partitions proven, others documented unresolved) is not a
            # WHOLE proven case: `Automated` claims the case, not a fraction of it. A row that names the number without
            # its area (or the reverse) is still this case's row: the one matcher, `contract.case_matches` (AR-15).
            left.append({"case": cid, "why": "unresolved:" + ",".join(sorted(why_unresolved))})
            continue
        entries = _population_of(keyed, cid, cfg)
        if not entries:
            left.append({"case": cid, "why": NO_EVIDENCE})
            continue
        bare = cid.rsplit("/", 1)[-1] if "/" in cid else cid
        source = _case_source(task_root, bare, links.get(bare))
        if source is None:
            left.append({"case": cid, "why": "case_source_not_found_or_ambiguous"})
            continue
        current_status = C.case_status(source)
        if current_status in ("Blocked", "Archived"):
            left.append({"case": cid, "why": f"status_{current_status.lower()}_not_touched"})
            continue
        # t-415 / HF3-1: the manifest's green is not the run's word - one predicate for every instance of the case; the
        # case is left for the FIRST reason any of its instances has (`HOLDS`: red, then not run, then not approved)
        reason = case_hold(entries, runs)
        if reason:
            if reason.startswith(NOT_RUN + ":") and report_unreadable:
                # a run report that exists but cannot be read is "not read", not "not run" (FR-59): name it
                left.append({"case": cid, "why": "run_report_unreadable"})
            else:
                left.append({"case": cid, "why": reason})
            continue
        refs, missing = [], []
        for e in entries:
            ref = _sensitivity_receipt(e, manifest, task_root)
            # D-0012: an unchanged reused instance is not probed and needs no receipt. Only a row
            # that SAYS it is unchanged and that no flag makes required is exempt: a row that says
            # nothing about its disposition is unknown, not unchanged (FR-41), and still needs proof.
            if (not ref and e.get("change_disposition") == "unchanged"
                    and not proof_level.proof_required(e, manifest)):
                # the words follow the reason: a handed case never reads "unchanged test" (FR-10)
                ref = proof_level.words_for(proof_level.not_required_why(e, manifest))
            (refs if ref else missing).append(ref or C.test_instance_id(e))
        if missing:
            left.append({"case": cid, "why": "no_sensitivity_proof:" + ",".join(sorted(missing))})
            continue
        instance_ids = sorted({C.test_instance_id(e) for e in entries})
        ready.append({"case": cid, "source": source, "link": links.get(bare),
                      "automated_by": ", ".join(instance_ids),
                      "red_probe": ", ".join(sorted(set(refs)))})
    return {"ready": ready, "left": left}


def stamp(task_root: Path, dry_run: bool = False, store: Path | None = None) -> dict:
    task_root = Path(task_root)
    manifest = C.load_json(C.artifact(task_root, "automation-manifest.json"))
    computed = plan(task_root, manifest)
    left = list(computed["left"])
    if dry_run:
        return {"stamped": [item["case"] for item in computed["ready"]], "left": left,
                "dry_run": True}
    import case_versions as V
    store = Path(store) if store is not None else V.store_root(task_root)
    stamped: list = []
    for item in computed["ready"]:
        cid, source, link = item["case"], item["source"], item["link"]
        # CS2: the stamp is execution lifecycle, not a new reviewed design. Once the manifest binds the case to
        # an immutable version (`tests[].case_version_links[]`), a new pin here would make that proof stale right
        # after S5 wrote it (every reader of the pin - delivery, coverage, the dashboard - would call the case
        # unproven), so the lifecycle frontmatter is written and the pin is left where the review put it. A case
        # the manifest does not link has no such proof and keeps the re-pin.
        immutable_proof = any(
            C.case_matches(str(ref.get("case_id") or ref.get("case") or ""), cid)
            for entry in C.manifest_tests(manifest)
            for ref in entry.get("case_version_links") or [] if isinstance(ref, dict))
        current = parse_frontmatter(C.read_text(source)) or {}
        if (current.get("status") == C.CASE_AUTOMATED
                and str(current.get("automated_by") or "") == item["automated_by"]
                and str(current.get("red_probe") or "") == item["red_probe"]):
            stamped.append(cid)  # already stamped at these exact bytes — nothing to re-pin
            continue
        W.upsert_frontmatter(source, {"status": C.CASE_AUTOMATED,
                                      "automated_by": item["automated_by"],
                                      "red_probe": item["red_probe"]})
        if immutable_proof:
            stamped.append(cid)
            continue
        try:
            record = V.create_version(store, source)
            V.pin(task_root, record, expected_previous_version=(link or {}).get("version"))
        except Exception as exc:
            left.append({"case": cid, "why": f"re-pin failed: {exc}"})
            continue
        stamped.append(cid)
    return {"stamped": stamped, "left": left}


def main() -> int:
    C.force_utf8()
    parser = argparse.ArgumentParser(
        description="stamp a case Automated once its manifest evidence proves it")
    parser.add_argument("--task-root", required=True)      # a raw string: `type=Path` read "" as the current folder
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be stamped; write and pin nothing")
    parser.add_argument("--store", type=Path, default=None)
    args = hooklib.exact_options(parser).parse_args()
    task_root = hooklib.story_cli("case_stamp.py", root=args.task_root, key_flag=None)
    result = stamp(task_root, dry_run=args.dry_run, store=args.store)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
