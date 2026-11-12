"""Semantic acceptance of a bounded automation window, independent of product outcome."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import proof_level  # noqa: E402
from hooklib import read_json, sorted_paths  # noqa: E402

# A mechanical fix (a sleep, a raw locator, a lint) made on the critic's word after the review
# and the probe were bound to the test's bytes. The window record then carries
# `mechanical_round: {author_dispatch_id, reviewer_dispatch_id, reviewed_input_hash}` and the
# critic is NOT dispatched again: the proof that the fix was made and nothing broke is the
# author's fresh green run on the new bytes, written by `run_suite.py` as a run block. S4 does
# the same for cases (`critic_rollcall.py --apply-fixes`). 0.7.8 closed such a round with one
# more `qa-code-critic` dispatch; the owner withdrew that.
MECHANICAL_ROUND_FIELDS = ("author_dispatch_id", "reviewer_dispatch_id", "reviewed_input_hash")

# The outcome of an instance the person took over because the factory cannot execute its
# profile in this session at all (TP2-2536: Maestro/iOS, no Xcode for the agent). The
# code is written and the critic still reviews it statically; there is no run, so there is no
# product outcome and no red probe to bind. Saying that as `product:` or `sensitivity:` would
# be the window claiming a behaviour was tested and failed, which is not what happened.
HANDED_OUTCOME = "handed_to_person"

# The gap of an item whose outcome SAYS `handed_to_person` and that the manifest does not confirm (B-375, `handed_instances`).
# It must not start with `handed_to_person` (the controller splits gaps by `g.startswith(HANDED_OUTCOME + ":")`), and it is
# not derivable: code never derives an `unresolved` pair over a hand-off the manifest does not hold (t-204 F1).
HANDED_UNCONFIRMED_KIND = "handed_unconfirmed"
# The review words a handed instance may carry: the charter's static word (`unverified`) or `approved`, bound to the bytes.
HANDED_REVIEW_VERDICTS = ("approved", "unverified")

# The outcome of an instance the STAND blocked (t-219, TP1-15045 cmp2: TC_004 and TC_008 stayed on
# "Loading", no Then was reached, and a window that could name that in no word looped through eight
# critic dispatches). The test is written and reviewed statically; no run reached a verdict, so there is
# no product outcome and no probe to bind. One word with the manifest's `unresolved[].reason` (FR-10).
# Never `handed_to_person` (that is the person's own choice, never a stand problem: contract.py).
BLOCKED_OUTCOME = "blocked_by_env"
# The only review word that lets a blocked instance through (Lead decision Q4): the critic read it
# statically and says it was not verified. `approved` would claim a live check that never happened.
BLOCKED_REVIEW_VERDICT = "unverified"

# A probe that could not run here, named by a person's word (HF1-14, TP1-12586): the item RAN GREEN, owes a live
# check, reached no valid receipt, and carries a `probe_gap` block. The claim is believed only as far as the story's
# own `pipeline.json` says (a live `probe gap: <case key>` word, `contract.probe_gap_words`): named ->
# `probe_gap:<iid>`; the block with no such word -> `probe_gap_unrecorded:<iid>` (the controller refuses it whatever the
# caller typed). The factory names no gap: a failure at the mutated line whose text the tool cannot read (E15: `incomplete`,
# `cause: judgment`, `proof_level.probe_owes_judgment`) is the code critic's to judge, never a gap. The review of such an item is the critic's static word, `unverified` (D-0013: S8 reads it as
# `review_unverified`, "Left with you"); `approved` would claim a live check that never happened.
PROBE_GAP_KIND = "probe_gap"
PROBE_GAP_UNRECORDED_KIND = "probe_gap_unrecorded"


def mechanical_round(window):
    """The window's `mechanical_round` when it is well formed, else None."""
    record = (window or {}).get("mechanical_round")
    if not isinstance(record, dict):
        return None
    if any(not isinstance(record.get(k), str) or not record[k].strip() for k in MECHANICAL_ROUND_FIELDS):
        return None
    return record


def _run_blocks(root):
    for path in sorted_paths((Path(root) / "work" / "run-blocks").glob("*.json")):
        try:
            block = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(block, dict):
            yield block


def _jobs(root) -> dict:
    """job_id -> job record of `state/execution-jobs/` (written by run_suite's job store)."""
    found = {}
    for path in sorted_paths((Path(root) / "state" / "execution-jobs").glob("*.json")):
        try:
            job = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(job, dict) and job.get("job_id"):
            found[str(job["job_id"])] = job
    return found


def _instance_test_file(root, instance_id) -> str:
    """The project-relative test file the manifest row of this instance names, "" when none."""
    try:
        manifest = json.loads(C.artifact(Path(root), "automation-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    rows = [e for e in (C.manifest_tests(manifest) if isinstance(manifest, dict) else []) if isinstance(e, dict)]
    # The row's exact id wins. A bare alias is shared by rows of different files, so it names a file only
    # when ONE row carries it; with two or more it names none (the raw bytes of another file are never
    # compared with this instance's `input_hash`).
    exact = [e for e in rows if C.test_instance_id(e) == instance_id]
    if exact:
        return proof_level.test_file_of(exact[0])
    aliased = [e for e in rows if instance_id in set(C.instance_id_aliases(e))]
    return proof_level.test_file_of(aliased[0]) if len(aliased) == 1 else ""


def _raw_record(request: dict, test_file: str) -> tuple:
    """(the raw sha256 the request's `fingerprint_files` recorded for the test file, what is missing).
    The file is the manifest's (matched on the recorded absolute path's tail), else the request's
    ONLY test file - an instance ran from this request, so its file is among them."""
    tests = [r for r in (request.get("fingerprint_files") or [])
             if isinstance(r, dict) and r.get("kind") == "test_files" and r.get("path") and r.get("sha256")]
    if not tests:
        return "", "the job's request records no test_files in fingerprint_files"
    if test_file:
        # `proof_level.same_path`: the same rule on every OS, the case counts (AR-4). On Windows the recorded
        # path carries the on-disk case, so a manifest path typed in another case finds no record and the
        # round is not green - one more critic round, never a false "same file" (E12).
        for rec in tests:
            if proof_level.same_path(str(rec["path"]), test_file):
                return str(rec["sha256"]), ""
        return "", f"the job's request records no fingerprint_files entry for {test_file}"
    if len(tests) == 1:
        return str(tests[0]["sha256"]), ""
    return "", ("the manifest names no test file for this instance and the job's request records "
                f"{len(tests)} test files")


def green_on_current_bytes_why(item, window, root) -> tuple:
    """(green, why not): did the mechanical author's own run go green on exactly this instance's
    bytes? `why` names what is missing when it did not (FR-41), "" when it did.

    Keyed on the instance's `execution_fingerprint`: the run block under `work/run-blocks/` whose
    `input_fingerprint` equals it, written by the round's `author_dispatch_id`, holding a `passed`
    row for the instance. Its bytes are read from the job that run came from - the block's
    `attempt_id` is the job's `job_id` in `state/execution-jobs/` - whose request recorded the RAW
    sha256 of every test file it ran (`fingerprint_files`). That raw sha is compared with the
    instance's `input_hash`, the raw sha of the test file. The block's own
    `source_fingerprint.test_content_sha` is a fingerprint over the test AND helper files, another
    quantity: comparing it with the raw hash (as this did until t-023) closed no round on
    TP1-13797 (driver3: 6992616693fc... raw against bd6d28d6aade...). Every value is written by
    `run_suite.py`, none by a role."""
    record = mechanical_round(window)
    if record is None:
        return False, "the window carries no well-formed mechanical_round"
    if item.get("outcome") != "passed":
        return False, "the instance's outcome is not passed"
    fingerprint = str(item.get("execution_fingerprint") or "")
    if not fingerprint:
        return False, "the instance carries no execution_fingerprint"
    identity = item.get("instance_id")
    jobs, reasons = None, []
    for block in _run_blocks(root):
        if str(block.get("input_fingerprint") or "") != fingerprint:
            continue
        if str(block.get("dispatch_id") or "") != record["author_dispatch_id"]:
            continue
        if not any(isinstance(row, dict) and row.get("instance_id") == identity
                   and row.get("status") == "passed" for row in block.get("results") or []):
            reasons.append(f"run block {block.get('block_id')} holds no passed result for {identity}")
            continue
        attempt = str(block.get("attempt_id")
                      or (block.get("reporter_mapping") or {}).get("source_attempt_id") or "")
        jobs = _jobs(root) if jobs is None else jobs
        job = jobs.get(attempt)
        if not attempt or job is None:
            reasons.append(f"run block {block.get('block_id')} names job {attempt or '(none)'}, and no such job "
                           "is under state/execution-jobs/ to say which bytes it ran")
            continue
        raw, missing = _raw_record(job.get("request") or {}, _instance_test_file(root, identity))
        if missing:
            reasons.append(f"job {attempt}: {missing}")
            continue
        # The one predicate, asked of the raw file shas only (E11): the review of a mechanical round is bound to
        # the raw bytes the reviewer saw, so `instance`/`file_code` answers are not accepted here.
        if proof_level.same_test({"input_hash": item.get("input_hash")}, {"input_hash": raw}) != "raw":
            reasons.append(f"job {attempt} ran the test file as sha256 {raw}, the instance now holds "
                           f"{item.get('input_hash')}")
            continue
        return True, ""
    if not reasons:
        reasons.append(f"no run block under work/run-blocks/ of {record['author_dispatch_id']} has "
                       f"input_fingerprint {fingerprint}")
    return False, "; ".join(reasons)


def green_on_current_bytes(item, window, root):
    """Did the mechanical author's own run go green on exactly this instance's bytes
    (`green_on_current_bytes_why`)? Without such a run the review and the probe are simply stale,
    as they were before."""
    return green_on_current_bytes_why(item, window, root)[0]


def run_freshness_of(item) -> tuple:
    """`(state, why)` of `proof_level.run_freshness` asked of a window item ALONE (HF2-11): the run's per-test
    shas are the item's `run_identity` (copied from the run row by `window_record.build`), the test now is the
    item's own `proof_identity`. Pure over the record - no file is read and nothing is measured again - so the
    window's check and its printed note are one call."""
    item = item if isinstance(item, dict) else {}
    return proof_level.run_freshness(item, item.get("run_identity"), None, now=proof_level.proof_identity(item))


def _bound_to(item, proof, window, root):
    """A review or probe is current when it still speaks for THIS test - `proof_level.same_test`, the
    one predicate the reports, the probes and this window share (per test instance: the same bytes, the
    same test after an edit of another one, or the same code of it after a comment) - or the bytes it
    was bound to before a mechanical fix that the author has since run green on the current bytes.
    The `bound == record["reviewed_input_hash"]` comparison (and its twin at the window check) is intentional: it
    compares a RECORDED value with its copy (`window_record`), not a measurement of a test (RH1-9, §2 (vii))."""
    if proof_level.same_test(proof_level.proof_identity(item), proof_level.proof_identity(proof)):
        return True
    bound = (proof or {}).get("input_hash")
    record = mechanical_round(window)
    return (record is not None and bound == record["reviewed_input_hash"]
            and green_on_current_bytes(item, window, root))


# t-108 (B-194): a test changed between its red run and the next green run is never a silent pass.
# `window_record.build` copies the OWED pairs of the window's scope (`s5_precheck.expectation_changes`)
# into the window as `expectation_changes: [{function, red_attempt, green_attempt, critic_verdict}]`
# (plus `passed_by_word: true` on a pair a person's word passed at the S5 exit: no gap while it has no verdict);
# this module only READS that list, so `validate_window` stays pure over the record (it never calls the
# detector, and a story is never refused over what the detector could not measure - that is
# `expectation_changes_unmeasured`, which `window_record.verdict` prints and nothing here reads).
# The words are `handoffs/vocabulary.yaml`'s (`expectation_change_words`, `expectation_change_verdicts`):
# code reads them, it does not hold a second copy (FR-13).
CHANGES_KEY = "expectation_changes"
CHANGE_GAP = "expectation_change"
CHANGE_WORDS = "expectation_change_words"
CHANGE_VERDICTS = "expectation_change_verdicts"
CHANGE_GOOD_VERDICT = "legitimate_correction"  # the one verdict that is no gap
CHANGE_SHOWN = 60  # characters of an unknown verdict a gap prints; a role may have written anything


def _change_vocabulary() -> tuple:
    """(the sentences, the closed verdict list) of `handoffs/vocabulary.yaml`; ({}, []) when it
    cannot be read - the gaps then still stand, only their sentences say the words are missing."""
    try:
        import handoff
        words = handoff.vocabulary().get(CHANGE_WORDS)
        return (dict(words) if isinstance(words, dict) else {}), handoff.allowed(CHANGE_VERDICTS)
    except Exception:
        return {}, []


def change_word(name: str, **fields) -> str:
    """The vocabulary's sentence `name` filled with `fields`, "" when it cannot be had."""
    try:
        return str(_change_vocabulary()[0][name]).format(**fields)
    except Exception:
        return ""


def expectation_change_gaps(window) -> list:
    """`[(gap, code)]` for every change of the window's `expectation_changes` list that stands unresolved.

    The gap is `expectation_change:<function>: <sentence>`; `code` says which kind it is
    (`no_verdict`, `could_not_judge`, `fitted_to_code`, `unknown_verdict`), so a printer can name whose
    move it is without reading the sentence. `legitimate_correction` is no gap. A verdict outside the
    closed list is a gap that names the value and the allowed ones (nothing guesses which it meant).
    Pure, never raises. An entry with no function is named `?`, as an instance with no id is in
    `validate_window`; a key that is not a list is one such entry - a hole, not a pass (FR-41).

    A window WITHOUT the key was built before this check existed (a story in flight): it is legacy, gets
    no gap and prints nothing. Noted, not fixed: dropping the key from a window would be a silent pass;
    acceptable while `window_record` is the only writer of window records."""
    if not isinstance(window, dict) or CHANGES_KEY not in window:
        return []
    listed = window[CHANGES_KEY]
    entries = listed if isinstance(listed, list) else [None]
    vocabulary = None
    found = []
    for entry in entries:
        item = entry if isinstance(entry, dict) else {}
        function = str(item.get("function") or "?")
        verdict = item.get("critic_verdict")
        if verdict == CHANGE_GOOD_VERDICT:
            continue
        if vocabulary is None:
            vocabulary = _change_vocabulary()
        words, allowed = vocabulary
        if verdict is None or (isinstance(verdict, str) and not verdict.strip()):
            if item.get("passed_by_word") is True:
                # A person's word passed this pair at the S5 exit (`waiver.py --stage S5`): the
                # window never asks the critic or the person again (P13, builder-rules 8). The
                # entry stays in the list, visible; only the gap for "no verdict" is not raised.
                # A verdict the critic DID write still counts below - the word does not edit it.
                continue
            code = "no_verdict"
        elif isinstance(verdict, str) and verdict in allowed and "gap_" + verdict in words:
            code = verdict
        else:
            code = "unknown_verdict"
        if code == "unknown_verdict":
            shown = repr(verdict)
            shown = shown if len(shown) <= CHANGE_SHOWN else shown[:CHANGE_SHOWN] + "..."
            text = (f"{CHANGE_GAP}:{function}: the critic verdict {shown} is not one of "
                    + (", ".join(allowed) or "(the list in handoffs/vocabulary.yaml could not be read)"))
        else:
            word = "gap_" + code
            try:
                text = str(words[word]).format(function=function)
            except Exception:
                text = (f"{CHANGE_GAP}:{function}: ({word} - the sentence is missing from "
                        "handoffs/vocabulary.yaml or could not be read)")
        found.append((text, code))
    return found


# --- an instance the stand blocked (t-219) ----------------------------------------------------------
# ONE reader decides "blocked": `window_record` (writes the outcome), `validate_window` (re-derives it from
# the manifest under the task root, so a record that merely CLAIMS the outcome is not believed) and
# `s5_precheck` (the run mapping and the both-lists check) all call `blocked_instances`.
#
# ERROR DIRECTION (the gate decides whether an `unresolved` pair may be derived from it): the allowed error is
# "not blocked" - a refusal costs the critic one more round; the forbidden error is "blocked" for an instance
# that is not - it would accept a window over a gap nobody named (t-204 F1). So every doubt below answers
# "not blocked": no remedy, a remedy that looks like a secret, a passed run on the current bytes, a row for a
# case outside the scope, an instance name that matches nothing, a row that names no instance on a case with
# two or more instances (code never guesses which test was meant), a manifest with no row for the instance.

REFUSED_NO_REMEDY = "no_remedy"
REFUSED_BAD_REMEDY = "bad_remedy"
REFUSED_STALE = "stale"
REFUSED_AMBIGUOUS = "ambiguous"


def _manifest_under(root) -> dict:
    """The story's automation manifest as a dict, `{}` when it is absent or unreadable."""
    try:
        data = json.loads(C.artifact(Path(root), "automation-manifest.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


REFUSED_NO_DETAIL = "no_detail"
REFUSED_NAMES = "names"
HANDED_REFUSED_RAN = "ran"
HANDED_REFUSED_PARTIAL = "partial"
# How much of a red run's reason is shown beside a blocked instance (O3): enough to tell a stand that never
# loaded from an assertion that missed, short enough to stay one line in the "acceptable as unresolved" print
# and inside the derived reason's 300-character limit.
RAN_RED_SHOWN = 60


def blocked_row_names(row) -> list:
    """The instance ids an `unresolved[]` row names, in the row's own order, without repeats: `instance_ids`
    (the row of a case carries the list, the manifest merges unresolved[] BY CASE), then a single
    `instance_id`. Empty when it names none."""
    if not isinstance(row, dict):
        return []
    names = row.get("instance_ids")
    found = [str(n).strip() for n in (names if isinstance(names, list) else []) if str(n or "").strip()]
    if str(row.get("instance_id") or "").strip():
        found.append(str(row["instance_id"]).strip())
    return list(dict.fromkeys(found))


def blocked_row_instances(row) -> set:
    """`blocked_row_names` as a set."""
    return set(blocked_row_names(row))


def ran_red(last_run) -> str:
    """`ran red: <reason>` for a blocked instance whose latest terminal run FAILED (O3), else "".

    A red that stood on the stand's own page is parked as `blocked_by_env`; without this mark nobody reading
    the "acceptable as unresolved" line or the derived reason would see that the test RAN and went red (P20,
    FR-10: the record says what happened). `last_run` is the window's `{status, reason, block}` of the latest
    terminal run, or None when nothing ran - no mark then. An empty reason says so; a long one is cut at
    RAN_RED_SHOWN characters with an ellipsis; line breaks become spaces so the mark stays one line."""
    if not isinstance(last_run, dict) or str(last_run.get("status") or "") != "failed":
        return ""
    reason = " ".join(str(last_run.get("reason") or "").split())
    if not reason:
        reason = "(no reason recorded)"
    elif len(reason) > RAN_RED_SHOWN:
        reason = reason[:RAN_RED_SHOWN] + "…"
    return "ran red: " + reason


def _passed_on_current_bytes(entry, run_row, root) -> bool:
    """Did the latest terminal run of this instance pass on the bytes it holds NOW?

    True also when that cannot be measured: the run row carries no per-test shas, the test file is gone, or no
    job says which function this is. "Cannot tell" must read as passed, never as blocked (the forbidden error).
    Only a measured DIFFERENCE (`proof_level.run_freshness` says `stale` over two identities that were both
    measured) lets a blocked row stand beside a passed run: the test changed after it passed, and the new bytes
    never ran.

    This is the OPPOSITE direction of the window's `stale_run` gap, on purpose (HF2-11): the window reads a
    run it cannot place as "not measured" and prints it, and a MEASUREMENT cause (a deleted helper, a missing
    test file) is `stale` there; here the same inputs read as PASSED, because the error to avoid in this context
    is calling a stale `blocked_by_env` row live. So only the fourth rule of `run_freshness` is used, and only
    when the file and an identity are both there; `WHY_NO_FILE` and the MEASUREMENT causes stay passed."""
    if C.result_status(run_row) != "passed":
        return False
    if not proof_level.run_identity(run_row):
        return True
    try:
        measured = proof_level.instance_identity(entry, root)
    except Exception:
        return True
    if not measured.get("input_hash") or not measured.get("instance_identity"):
        return True
    return proof_level.run_freshness(entry, run_row, root, now=measured)[0] != "stale"


def blocked_instances(manifest, items, scope=None, root=None, runs=None, refused=None, strict=True) -> dict:
    """`{instance id: the manifest unresolved[] row that blocks it}` for the `items` (dicts with an `instance_id`).

    An instance is blocked when (B1):
      (i)   an `unresolved[]` row with reason `blocked_by_env` names it - an alias of the instance
            (`contract.instance_id_aliases`) is in the row's `instance_ids` / `instance_id` - and the instance
            covers the row's case; or the row names no instance (the cmp2 rows carry a partition and none) and
            the window has EXACTLY ONE instance of that case, and that instance covers no case outside the row;
      (ii)  `contract.remedy_errors(row.remedy)` is empty: a stand gap without its named fix never closes a
            window by code (and a remedy that reads like a secret is refused);
      (iii) the latest terminal run of the instance is not a `passed` one on the current bytes
            (`_passed_on_current_bytes`; `runs` is `window_record._terminal_runs`' map, read from `root` when
            not given; without `root` and `runs` this check is not made).

    `scope` is the window's `scope_instances` (case -> instance ids): it says which cases an instance covers and
    how many instances a case has; without it nothing is blocked (the allowed error). `refused`, when a list,
    receives `(kind, id, sentence)` for every row that matched an instance and was turned down - the reader
    prints it, so a refusal names what to repair (FR-1). `strict=False` skips (ii) and (iii): `manifest_put`
    asks "which row is about the instance that just went green", where the row's remedy decides nothing."""
    if not isinstance(manifest, dict) or not isinstance(scope, dict) or not scope:
        return {}
    rows = [r for r in C.manifest_unresolved(manifest) if str(r.get("reason") or "") == BLOCKED_OUTCOME]
    if not rows:
        return {}
    cfg = C.case_config(root) if root is not None else C.case_config()
    by_case = {str(case): [str(i) for i in ids] for case, ids in scope.items() if isinstance(ids, list)}
    # alias -> the tests[] row it names, once per call (every spelling of an instance finds its row; the first
    # row wins, as `manifest_put` merges them into one)
    by_alias: dict = {}
    for test in C.manifest_tests(manifest):
        for alias in C.instance_id_aliases(test, cfg):
            by_alias.setdefault(alias, test)
    if runs is None and root is not None and strict:
        try:
            import window_record
            runs = window_record._terminal_runs(Path(root))
        except Exception:
            return {}  # runs unreadable: nobody can say none passed - the allowed error
    runs = runs if isinstance(runs, dict) else {}
    found: dict = {}
    seen: set = set()
    for item in items or []:
        iid = str((item or {}).get("instance_id") or "") if isinstance(item, dict) else ""
        if not iid or iid in found:
            continue
        entry = by_alias.get(iid)
        if entry is None:
            continue  # a record naming a test the manifest does not hold is not a blocked test
        names = set(C.instance_id_aliases(entry, cfg)) | {iid}
        covered = [case for case, ids in by_case.items() if iid in ids]
        if not covered:
            continue
        for row in rows:
            row_case = str(row.get("case") or "")
            here = [case for case in covered if C.case_matches(row_case, case, cfg=cfg)]
            if not here:
                continue  # the row is about a case this instance does not cover (or one outside the scope)
            named = blocked_row_names(row)
            if named:
                if not set(named) & names:
                    # The row speaks about OTHER instances of this case (a normal state: one test blocked, its
                    # sibling not). It is said only when it explains a gap - an instance whose latest run did
                    # not pass: after a later fragment REPLACED the naming (O1), the red that was blocked a
                    # moment ago reads as a plain failure, and this line says why.
                    last = runs.get(iid)
                    if (refused is not None and strict and not (last and C.result_status(last[0]) == "passed")
                            and (REFUSED_NAMES, iid) not in seen):
                        seen.add((REFUSED_NAMES, iid))
                        refused.append((REFUSED_NAMES, iid,
                                        f"{here[0]}'s blocked_by_env row names [{', '.join(named)}], not {iid}; if "
                                        f"the stand blocked {iid} too, the automator adds it to that row's "
                                        "`instance_ids` through manifest_put.py (every blocked instance of the case "
                                        "listed, not only the last one sent)"))
                    continue
            else:
                alone = len(by_case[here[0]]) == 1
                outside = [case for case in covered if case not in here]
                if not alone:
                    if refused is not None and (REFUSED_AMBIGUOUS, here[0]) not in seen:
                        seen.add((REFUSED_AMBIGUOUS, here[0]))
                        refused.append((REFUSED_AMBIGUOUS, here[0],
                                        f"{here[0]}: its blocked_by_env row names no instance and the case has "
                                        f"{len(by_case[here[0]])} instances in this window; name the instance_id "
                                        "(`instance_ids` on that unresolved[] row, through manifest_put.py)"))
                    continue
                if outside:
                    continue  # the test also proves cases the row does not speak about
            if strict:
                remedy = row.get("remedy")
                problems = C.remedy_errors(remedy)
                if problems:
                    if refused is not None:
                        if remedy is None:
                            refused.append((REFUSED_NO_REMEDY, iid,
                                            f"{iid}: the blocked_by_env row has no remedy; the automator adds "
                                            "{kind, where, change, restart} to that unresolved[] row through "
                                            "manifest_put.py"))
                        else:
                            # All the problems of the remedy in the one refusal (K1): the automator
                            # corrects the row once, not once per problem.
                            defects = (problems[0] if len(problems) == 1
                                       else f"{len(problems)} defect(s): " + "; ".join(problems))
                            refused.append((REFUSED_BAD_REMEDY, iid,
                                            f"{iid}: the remedy of its blocked_by_env row is not one "
                                            f"({defects}); the automator corrects that row through "
                                            "manifest_put.py"))
                    continue
                last = runs.get(iid)
                if last and _passed_on_current_bytes(entry, last[0], root):
                    if refused is not None:
                        refused.append((REFUSED_STALE, iid,
                                        f"{iid}: a passed run on the current bytes stands beside its blocked_by_env "
                                        "row, so the blocked row is stale; send the green tests[] entry through "
                                        "manifest_put.py, which drops that row"))
                    continue
                if (last and C.result_status(last[0]) == "failed"
                        and not str(row.get("detail") or "").strip()):
                    # O5 (FR-34): a test that RAN and failed is parked as blocked only on the automator's word
                    # for what shows the stand, not the product, stopped it - code cannot tell the two reds
                    # apart (E4), so without that word the red stays a failure. A test that never ran owes none.
                    if refused is not None:
                        refused.append((REFUSED_NO_DETAIL, iid,
                                        f"{row_case}: the blocked_by_env row for {iid} says nothing about what "
                                        "stopped it, and this test ran and failed - a failure on a changed page "
                                        "may be the product's own. The automator adds a `detail` to that row "
                                        "naming the control that shows the stand, not the product, blocked it "
                                        "(what was tried: a direct call, a second route, the stand's own health); "
                                        "or the critic judges the failure a product defect"))
                    continue
            found[iid] = row
            break
    return found


# --- an instance whose side does not exist yet (t-2181 PC-4, C5) -------------------------------------------------------
# ONE reader decides "pending" for an INSTANCE (AR-13, S14): `s5_precheck` (the run mapping and C5), `window_record` (is a
# probe owed) and `run_witness_excused` (so the witness readers) all call `pending_instances`, a sibling of `blocked_instances`.
#
# ERROR DIRECTION (it moves from a report reader into the gate that excuses a run): the allowed error is "not pending" - the
# instance must run, a refusal costs the author one more round; the forbidden error is "pending" for an instance that could
# run - it would excuse a run, a probe and a witness nobody owed away (FR-59). Every doubt answers "not pending": a row
# without `instance_ids`, an instance the manifest holds no row for, a test that declares no `absent` side, a side the reader
# does not call `absent` (an unknown reads as not absent), a row of another case, an instance outside the given scope.

PENDING_OUTCOME = C.PENDING_IMPLEMENTATION


def pending_rows(manifest) -> list:
    """The `pending_implementation` rows of the manifest that name at least one instance (`instance_ids`): the ONE filter of them
    (AR-13) - `pending_instances`, the S5 sides check and the window re-derivation read through it. A whole-case row with no
    `instance_ids` is not one of them (E-X2)."""
    if not isinstance(manifest, dict):
        return []
    return [r for r in C.manifest_unresolved(manifest)
            if str(r.get("reason") or "") == PENDING_OUTCOME and isinstance(r.get("instance_ids"), list)
            and any(str(n or "").strip() for n in r["instance_ids"])]


def tests_by_alias(manifest, cfg=None) -> dict:
    """`{alias: tests[] row}` over every alias of every test (`contract.instance_id_aliases`): the ONE alias map of the pending
    readers, FIRST row wins on a repeated alias (the tie-break `pending_instances` always had)."""
    cfg = cfg if cfg is not None else C.case_config()
    by_alias: dict = {}
    for test in C.manifest_tests(manifest):
        for alias in C.instance_id_aliases(test, cfg):
            by_alias.setdefault(alias, test)
    return by_alias


def pending_instances(manifest, items, scope=None, sides=None) -> dict:
    """`{instance id: the unresolved[] row that excuses it}` for the `items` (dicts with an `instance_id`).

    An instance is pending when ALL hold (C5):
      (i)   a `pending_implementation` row of the manifest names it (an alias of it, `contract.instance_id_aliases`) in its
            `instance_ids`, and the row's case is a case the instance covers - those of `scope` (case -> instance ids) that
            list it, or, without `scope`, the cases of its `tests[]` row;
      (ii)  its `tests[]` row declares a side valued `absent` in `sides` (`{side: real|substituted|absent}`);
      (iii) with `sides` (the output of `contract.story_sides`: `{name: {reality, ...}}`) that same side is `absent` there.
    Without `sides` (manifest-only mode: `check_witness` has no story root) (iii) is not made here; `s5_precheck` makes it
    at the same S5 exit. A whole-case row with no `instance_ids` excuses no instance (E-X2)."""
    rows = pending_rows(manifest)
    if not rows:
        return {}
    cfg = C.case_config()
    by_alias = tests_by_alias(manifest, cfg)
    by_case = ({str(case): [str(i) for i in ids] for case, ids in scope.items() if isinstance(ids, list)}
               if isinstance(scope, dict) else None)
    found: dict = {}
    for item in items or []:
        iid = str((item or {}).get("instance_id") or "") if isinstance(item, dict) else ""
        if not iid or iid in found:
            continue
        entry = by_alias.get(iid)
        declared = entry.get("sides") if isinstance(entry, dict) else None
        if not isinstance(declared, dict):
            continue
        absent = [str(name) for name, value in declared.items() if value == "absent"]
        if sides is not None:
            absent = [name for name in absent
                      if isinstance(sides.get(name), dict) and sides[name].get("reality") == "absent"]
        if not absent:
            continue
        names = set(C.instance_id_aliases(entry, cfg)) | {iid}
        cases = ([case for case, ids in by_case.items() if iid in ids] if by_case is not None
                 else list(C.manifest_test_links(entry, cfg)) + [str(entry.get("case") or "")])
        for row in rows:
            named = {str(n).strip() for n in row["instance_ids"] if str(n or "").strip()}
            if named & names and any(C.case_matches(str(row.get("case") or ""), case, cfg=cfg)
                                     for case in cases if case):
                found[iid] = row
                break
    return found


# --- no run to witness (t-2181 PC-4, B3) -------------------------------------------------------------------------------
# ONE public reader of "this manifest owes no `run_witness`" (AR-13): `check_witness.RULES`, `validate_artifacts.check_phase_json`
# and `handoff_check._run_witness` all ask it, so the all-handed and the all-pending roads are excused in the same three
# places and never in two of them. ERROR DIRECTION: "" (witness owed) on any doubt; the forbidden error is excusing a run
# that was owed (FR-59).

def run_witness_excused(manifest) -> str:
    """`"handed"` when every test of the manifest belongs to a case the person took over (nothing in the session could launch a
    run: TP2-2536), `"pending"` when every test is named by `pending_instances` in its MANIFEST-ONLY mode (no story root
    here, so the reader's third condition is made by `s5_precheck` at the same S5 exit; the collect is owed instead,
    `check_witness._collect_row_missing`), else `""`. One test that could run puts the whole manifest back under the rule."""
    if not isinstance(manifest, dict):
        return ""
    try:
        handed = {row["case"] for row in C.handed_tests(manifest)}
        if handed:
            tests = [t for t in manifest.get("tests") or [] if isinstance(t, dict)]
            if all(({str(c) for c in C.manifest_test_links(t)} | {str(t.get("case") or "")}) & handed for t in tests):
                return "handed"
        ids = [C.test_instance_id(t) for t in C.manifest_tests(manifest)]
        if ids and all(ids) and all(i in pending_instances(manifest, [{"instance_id": i} for i in ids]) for i in ids):
            return "pending"
    except Exception:
        return ""
    return ""


# --- an instance the person runs (B-375) -------------------------------------------------------------------------------
# ONE reader decides "handed to the person" for an INSTANCE (AR-13): `window_record.build` (writes the outcome) and
# `validate_window` (re-derives it from the manifest under the root, so a record that merely CLAIMS the outcome is not
# believed). The rows come from `contract.handed_tests` (whole-case rows, reason exactly `handed_to_person`); a scope case
# is "handed" by the controller's own rule, `case in contract.scope_keys(row.case)` (exact keys, the rule
# `controller._cases_without_instances` applies to a case with no instance) - never `case_matches`, whose "a bare id matches
# any area" generosity is wrong in a gate.
#
# ERROR DIRECTION (host adaptation 2: `handed_tests` and `scope_keys` move from report/ledger readers into a GATE role):
# the allowed error is "not handed" (a refusal with a door costs one rebuild); the forbidden error is "handed" for an
# instance that is not - it would derive a pair over a gap nobody named (t-204 F1) and hide a case or a red run behind "the
# person runs it". Every doubt answers "not handed": no `tests[]` row for the instance, no scope, a case of the instance that
# no row hands, a row of another reason or another case, a terminal run of the instance.

def handed_instances(manifest, items, scope=None, root=None, runs=None, refused=None) -> dict:
    """`{instance id: [the handed_to_person rows that cover it]}` for the `items` (dicts with an `instance_id`).

    An instance is handed when ALL hold, checked in this order:
      1. `manifest` is a dict, `scope` a non-empty dict (case -> instance ids), and the instance resolves
         (`contract.instance_id_aliases`) to a `tests[]` row of the manifest - as `blocked_instances` requires;
      2. the window lists it under at least one case; its cases are those scope cases that list it plus those of its row's
         links (`contract.manifest_test_links`) that are scope keys, so a hand-edited `scope_instances` cannot drop a case;
         at least one of them is handed;
      3. NO terminal run of it exists (`runs` is `window_record._terminal_runs`' map, read from `root` when not given;
         without `root` and `runs` this check is not made): a run that reached `passed`/`failed` outranks the hand-off,
         build's own precedence (`ran`). A corrupt run block is skipped by `run_history.read_run_blocks`, as it is for
         `blocked_instances`: a known limit shared with it, an unreadable directory answers `{}`;
      4. EVERY one of its cases is handed (`partial` otherwise): a test that also proves a case the person does not run is
         not handed.

    `refused`, when a list, receives `(kind, instance id, sentence)` for an instance that has a handed case and was turned
    down (`ran`, `partial`), once each - the reader prints it with its repair (FR-1). An instance with no handed case at
    all is turned down silently."""
    if not isinstance(manifest, dict) or not isinstance(scope, dict) or not scope:
        return {}
    rows = C.handed_tests(manifest)
    if not rows:
        return {}
    cfg = C.case_config(root) if root is not None else C.case_config()
    keyed = [(row, set(C.scope_keys(row.get("case"), cfg=cfg))) for row in rows]
    by_case = {str(case): [str(i) for i in ids] for case, ids in scope.items() if isinstance(ids, list)}
    by_alias: dict = {}
    for test in C.manifest_tests(manifest):
        for alias in C.instance_id_aliases(test, cfg):
            by_alias.setdefault(alias, test)
    if runs is None and root is not None:
        try:
            import window_record
            runs = window_record._terminal_runs(Path(root))
        except Exception:
            return {}  # runs unreadable: nobody can say none ran - the allowed error
    found: dict = {}
    for item in items or []:
        iid = str((item or {}).get("instance_id") or "") if isinstance(item, dict) else ""
        entry = by_alias.get(iid)
        if not iid or iid in found or entry is None:
            continue  # a record naming a test the manifest does not hold is not a handed test
        covered = [case for case, ids in by_case.items() if iid in ids]
        if not covered:
            continue  # the window lists the instance under no case
        covered += [link for link in C.manifest_test_links(entry, cfg) if link in by_case and link not in covered]
        mine = [case for case in covered if any(case in keys for _row, keys in keyed)]
        if not mine:
            continue
        last = runs.get(iid) if isinstance(runs, dict) else None
        if last:
            if refused is not None:
                # The row is stale only when no OTHER instance of its cases is still un-run: a case-level row hands every
                # un-run instance of the case, and dropping it would unhand them (m-1).
                others = sorted({other for case in mine for other in by_case.get(case, [])
                                 if other != iid and other in by_alias and not (runs.get(other) if isinstance(runs, dict) else None)})
                tail = (f"the handed_to_person row beside it still hands {', '.join(others)} (not run) - keep it" if others else
                        "the handed_to_person row beside it is stale - the automator drops it through manifest_put.py")
                refused.append((HANDED_REFUSED_RAN, iid,
                                f"{iid}: the manifest hands {', '.join(mine)} to the person, and a run of it reached "
                                f"`{C.result_status(last[0])}` ({Path(last[2]).name}); the run's outcome stands, and {tail}"))
            continue
        if len(mine) != len(covered):
            if refused is not None:
                refused.append((HANDED_REFUSED_PARTIAL, iid,
                                f"{iid} covers {', '.join(mine)} (handed to the person) and "
                                f"{', '.join(c for c in covered if c not in mine)} (not handed): the automator splits the "
                                "test so a handed test covers only cases the person runs, or moves those cases to "
                                "unresolved[] with handed_to_person through manifest_put.py when the person takes them over"))
            continue
        found[iid] = [row for row, keys in keyed if any(case in keys for case in covered)]
    return found


# --- red by the requirement (HF2-3, GW1-22) ---------------------------------------------------------------------
# TP1-12586 (22-24.10.2026): ONE test (msteams) covers TC-004, TC-005 and TC-006 and fails at TC-004's Then 2. The
# row `contradicts_requirement` that says so belongs to ONE instance and ONE case, and every reader had its own idea of
# what that row speaks about (the whole case, the first instance, the partition by its raw label). The three functions
# below are the ONE reader (AR-13): `row_slice` says whether a row speaks about an instance, `red_by_requirement`
# which instances are red by a row, `red_by_own_row` whether one of those rows is a case's own. The error direction of
# all three is "not red": the cost is a refusal that names its door, the forbidden error is a red nobody explained
# passing (FR-59), or a green one called red.
CONTRADICTS_REQUIREMENT = "contradicts_requirement"
# What `row_slice` answers when the row does NOT speak about the instance (and, with `no_then`, the kinds a refusal of
# `red_by_requirement` carries).
SLICE_OTHER_CASE = "other_case"
SLICE_NAMES_OTHER = "names_other"
SLICE_NO_PARTITIONS = "no_partitions"
SLICE_OTHER_PARTITION = "other_partition"
REFUSED_NO_THEN = "no_then"
# The door of every refusal below: the one road a role has to a corrected row (FR-2). It names the fragment road and
# nothing else - the marker writes `blocked_by_check` rows since HF2-12b, but a row that was refused is corrected by
# hand in the fragment, which stays the door (FR-11).
RED_ROW_ROAD = "manifest_put.py --task <T> --fragment <file>"


def _slice_values(row, keys) -> list:
    """The values a row (or a test entry) holds under `keys`, stripped, without blanks and repeats; a list is its
    items, a scalar is itself. A value that is no label (a list inside a list, a dict) is its `str()`, which matches
    nothing."""
    out: list = []
    for key in keys:
        value = row.get(key) if isinstance(row, dict) else None
        for item in value if isinstance(value, list) else [value]:
            text = str(item).strip() if item is not None else ""
            if text and text not in out:
                out.append(text)
    return out


def row_slice(row, entry, case, cfg=None) -> str:
    """`""` when the `unresolved[]` row `row` speaks about the test `entry` (a `tests[]` row) in the case `case`;
    otherwise the code of why it does not. THE one reader of what a row's slice keys mean (AR-13, N5):
      `other_case`      the row's case is not `case` (`contract.case_matches`), or row or entry is no object;
      `names_other`     the row names instances (`contract.UNRESOLVED_INSTANCE_KEYS`) and none is an alias of
                        `entry` (`contract.instance_id_aliases`);
      `no_partitions`   the row names partitions (`UNRESOLVED_PARTITION_KEYS`) and `entry` declares none;
      `other_partition` both name partitions and the `contract.partition_key` sets do not meet.
    Checked in that order. A row without slice keys speaks about every instance of its case; `thens` is no slice key.
    A pure function: it reads no run. Error direction: toward a code. A key that is present but names nothing readable
    (`instance_ids: [None]`, a partition that is only `P-`) is a slice that matches NOTHING, not a whole-case row, and
    an empty partition key never meets another (two unreadable labels are not one partition)."""
    if not isinstance(row, dict) or not isinstance(entry, dict):
        return SLICE_OTHER_CASE
    row_case, want = str(row.get("case") or "").strip(), str(case or "").strip()
    if not row_case or not want or not C.case_matches(row_case, want, cfg=cfg):  # two blanks are not one case
        return SLICE_OTHER_CASE
    if any(row.get(key) for key in C.UNRESOLVED_INSTANCE_KEYS):
        if not set(_slice_values(row, C.UNRESOLVED_INSTANCE_KEYS)) & set(C.instance_id_aliases(entry, cfg)):
            return SLICE_NAMES_OTHER
    if any(row.get(key) for key in C.UNRESOLVED_PARTITION_KEYS):
        mine = {C.partition_key(v) for v in _slice_values(entry, C.UNRESOLVED_PARTITION_KEYS)} - {""}
        if not mine:
            return SLICE_NO_PARTITIONS
        if not mine & ({C.partition_key(v) for v in _slice_values(row, C.UNRESOLVED_PARTITION_KEYS)} - {""}):
            return SLICE_OTHER_PARTITION
    return ""


def story_scope(manifest, cfg=None) -> dict:
    """`{case: [instance ids]}` over EVERY `tests[]` row of the manifest and the cases each proves
    (`contract.manifest_test_links`), in manifest order, an instance once per case (`contract.test_instance_id`). The
    scope a window builds for its own cases (`window_record.build`), taken over the whole story: one helper for the
    controller, the delivery check and the ledger, which read a story and not a window. Empty for a manifest that is no
    object or holds no test that proves a case: with no scope nothing is red (`red_by_requirement`)."""
    out: dict = {}
    if not isinstance(manifest, dict):
        return out
    for entry in C.manifest_tests(manifest):
        identity = C.test_instance_id(entry)
        if not identity:
            continue
        for case in C.manifest_test_links(entry, cfg):
            if identity not in out.setdefault(case, []):
                out[case].append(identity)
    return out


def _red_refusal(kind, case, iid, row, entry, bound, needed) -> str:
    """The FR-1 sentence of a red instance that no `contradicts_requirement` row explained: what the row says, what
    the instance is, the fix, and the road (`RED_ROW_ROAD`). Machine channel (script refusal), not a text for a person."""
    names = ", ".join(_slice_values(row, C.UNRESOLVED_INSTANCE_KEYS))
    parts = ", ".join(_slice_values(row, C.UNRESOLVED_PARTITION_KEYS))
    if kind == SLICE_NAMES_OTHER:
        return (f"{case}'s contradicts_requirement row names [{names}], not {iid}; if {iid} is red for {case} too, the "
                "automator adds it to that row's `instance_ids` (every red instance of the case listed) and sends the "
                f"row through `{RED_ROW_ROAD}`")
    if kind == SLICE_NO_PARTITIONS:
        return (f"{case}'s contradicts_requirement row names partitions [{parts}] and {iid} declares none; the automator "
                f"names the instance in the row (`instance_ids: [{iid}]`) and sends it through `{RED_ROW_ROAD}`")
    if kind == SLICE_OTHER_PARTITION:
        mine = ", ".join(_slice_values(entry, C.UNRESOLVED_PARTITION_KEYS))
        return (f"{case}'s contradicts_requirement row names partitions [{parts}] and {iid} runs [{mine}]; the "
                "automator names this instance (or its partition) in the row and sends it through "
                f"`{RED_ROW_ROAD}`")
    held = ", ".join(str(n) for n in sorted(bound)) or "no Then"
    if needed is None:
        return (f"{case}'s contradicts_requirement row names no Then and {iid} binds {held} of {case}; the automator "
                f"binds the red Then of {case} to {iid} in `then_bindings` and sends the rows through `{RED_ROW_ROAD}`")
    asked = ", ".join(str(n) for n in sorted(needed)) or "none that can be read"
    return (f"{case}'s contradicts_requirement row names Then {asked} and {iid} binds {held} of {case}; the automator "
            "corrects `thens` to the red Then, or binds that Then to "
            f"{iid} in `then_bindings`, and sends the rows through `{RED_ROW_ROAD}`")


def red_by_requirement(manifest, items, scope, root=None, runs=None, refused=None, strict=True, report=None) -> dict:
    """`{instance id: [the unresolved[] rows that make it red]}` for the `items` (dicts with an `instance_id`): every
    instance that FAILED against a requirement and says so, in the row's own words. Same signature as
    `blocked_instances` plus `report`. The value is EVERY matching row, in the manifest's order, not the first (N1): an
    instance red for the rows of two cases is red for both, and the reader does not pick the guilty one.

    A row R matches an instance I when (i) R's reason is `contradicts_requirement` and I covers R's case in `scope`
    (`{case: [instance ids]}`, `story_scope` or a window's `scope_instances`); (ii) `row_slice(R, I, R's case)` is
    empty; (iii) R names `thens: [n...]` -> I has a COVERED `then_bindings` row `{case: R's case, instance_id: an
    alias of I}` for one of the n; R names no `thens` -> I has one for the case at all. A `thens` that is no list, is
    empty, or holds no clause number names no Then, so the row does not match. (iv) The OTHER cases I covers do not
    matter here, whatever they hold (covered rows, `blocked_by_check` rows, nothing): how a Then of another case is read
    on a red instance is the reader's (`red_by_own_row` and the ledger, the trace). I is red when some row matches AND
    its source of redness says so; exactly ONE source per call, in this order:
      (v-a) `report` given (S6+: ledger, trace, delivery check): the current result of I
            (`contract.current_instance_results`, any alias) is `failed`. Run blocks and `runs` are not read, `strict`
            is not looked at. No row, `passed`, `error`, `skipped`, a word outside the result vocabulary, a report
            that is no object: not red;
      (v-b) no `report`, `strict`: the latest terminal run of I (`runs`, or `window_record._terminal_runs(root)`) is
            `failed`. No run, a `passed` latest run, runs that cannot be read: not red;
      (v-c) no `report`, not `strict` (the precheck, `manifest_put`): the structure alone, no run is read.
    `refused`, when a list, receives `(kind, instance id, sentence)` and ONLY in (v-b), one per instance, for an
    instance whose latest run FAILED, that no row matched, and that covers a case some `contradicts_requirement` row
    speaks about: kind is the `row_slice` code of the first row turned down, or `no_then`. A green or unrun instance
    gets none (a row about its sibling is the normal state of a case with several instances). The sentence names the fix
    and `RED_ROW_ROAD` (FR-1, FR-2).

    Empty outcome (AR-23): no manifest object, no scope, no `contradicts_requirement` row -> `{}`. Error direction
    (FR-59): everything unreadable - manifest, scope, runs, report - gives `{}`, i.e. "not red", which at S5 is the
    `product:` refusal and after S5 a case read by its own runs. NOT protected, said and not hidden: the author names in
    `thens` a Then that did not fail while the test stopped at another assert; code cannot tell (FR-58), the window is
    closed as unresolved and S7 judges every red one. No side effects."""
    if not isinstance(manifest, dict) or not isinstance(scope, dict) or not scope:
        return {}
    rows = [r for r in C.manifest_unresolved(manifest) if str(r.get("reason") or "") == CONTRADICTS_REQUIREMENT]
    if not rows:
        return {}
    cfg = C.case_config(root) if root is not None else C.case_config()
    by_case = {str(case): [str(i) for i in ids] for case, ids in scope.items() if isinstance(ids, list)}
    by_alias: dict = {}
    for test in C.manifest_tests(manifest):
        for alias in C.instance_id_aliases(test, cfg):
            by_alias.setdefault(alias, test)
    bindings = [b for b in (manifest.get("then_bindings") or []) if isinstance(b, dict)
                and str(b.get("status") or "") == "covered"] if isinstance(manifest.get("then_bindings"), list) else []
    current: dict = {}
    if report is not None:
        try:
            current = C.current_instance_results(report) if isinstance(report, dict) else {}
        except Exception:
            current = {}  # a report that cannot be read names no failure - the allowed error
    elif strict:
        if runs is None and root is not None:
            try:
                import window_record
                runs = window_record._terminal_runs(Path(root))
            except Exception:
                return {}  # runs unreadable: nobody can say the latest run failed - the allowed error
        runs = runs if isinstance(runs, dict) else {}

    def failed(names) -> bool:
        """Does the source of redness of this call say `failed` for an instance answering to `names`?"""
        if report is not None:
            return any(isinstance(current.get(n), dict) and C.result_status(current[n]) == "failed" for n in names)
        if not strict:
            return True
        try:
            for name in names:
                last = runs.get(name)
                if last:
                    return isinstance(last, (tuple, list)) and isinstance(last[0], dict) \
                        and C.result_status(last[0]) == "failed"
        except Exception:
            return False  # a run map that cannot be read says nothing failed - the allowed error
        return False

    found: dict = {}
    seen: set = set()
    for item in items or []:
        iid = str((item or {}).get("instance_id") or "") if isinstance(item, dict) else ""
        if not iid or iid in seen:
            continue
        seen.add(iid)
        entry = by_alias.get(iid)
        if entry is None:
            continue  # a record naming a test the manifest does not hold is not a red test
        names = list(dict.fromkeys([iid, *C.instance_id_aliases(entry, cfg)]))
        covered = [case for case, ids in by_case.items() if iid in ids]
        matched: list = []
        turned_down: list = []
        for row in rows:
            here = [case for case in covered if C.case_matches(str(row.get("case") or ""), case, cfg=cfg)]
            if not here:
                continue  # a row about a case this instance does not cover: not about this instance at all
            case = here[0]
            code = row_slice(row, entry, case, cfg)
            if code:
                turned_down.append((code, row, case, set(), None))
                continue
            held = {n for n in (C.then_number(b.get("then")) for b in bindings
                                if str(b.get("instance_id") or "").strip() in names
                                and C.case_matches(str(b.get("case") or ""), case, cfg=cfg)) if n}
            raw = row.get(C.UNRESOLVED_THENS_KEY)
            needed = None if raw is None else ({n for n in (C.then_number(x) for x in raw) if n}
                                               if isinstance(raw, list) else set())
            if (held if needed is None else held & needed):
                matched.append(row)
            else:
                turned_down.append((REFUSED_NO_THEN, row, case, held, needed))
        if matched and failed(names):
            found[iid] = matched
        elif (not matched and turned_down and refused is not None and report is None and strict and failed(names)):
            kind, row, case, held, needed = turned_down[0]
            refused.append((kind, iid, _red_refusal(kind, case, iid, row, entry, held, needed)))
    return found


def red_by_own_row(red, iid, case, cfg=None) -> bool:
    """Is the instance `iid` red by a row of the case `case` ITSELF: `iid` is in `red` (the result of
    `red_by_requirement`) and one of its rows is `case`'s (`contract.case_matches`). THE one predicate (AR-13) of "this
    instance failed at THIS case's own requirement": the precheck, the ledger and the trace ask it, and "red only for
    OTHER cases' requirements" is `iid in red and not red_by_own_row(red, iid, case)`. Error direction: False - an
    instance not in `red`, a `red` that is no object, a row with no case, all say "not its own"."""
    rows = red.get(iid) if isinstance(red, dict) else None
    want = str(case or "").strip()
    return bool(want) and isinstance(rows, list) and any(
        isinstance(r, dict) and str(r.get("case") or "").strip() and C.case_matches(str(r["case"]).strip(), want, cfg=cfg)
        for r in rows)


def probe_gap_named(window, root) -> dict:
    """{instance id: {"key", "words", "at"}} — the items of `window` that carry a `probe_gap` block AND that a live
    recorded word of the person names: the instance id itself, else a case key of `scope_instances` that lists it, else (GW1-43)
    the decision of the CLASS (`contract.probe_gap_class_word`, key `class:probe_gap_accepted`) for a green instance whose probe
    the tool could not read (`cause: judgment` is never that: the code critic's, `proof_level.probe_owes_judgment`). The factory
    names no gap of its own (t-1968 N2). A `cannot_judge` item (t-1968 N5) is named ONLY by the person's `probe not proved: <case key>`
    word (`contract.probe_not_proved_words`) not older than the judgment, key `probe not proved: <case key>`. The ONE join (identifier equality through `contract.probe_gap_words`; never `*`, never a substring), read from
    the story's own `pipeline.json` under `root` and not from the window, which a role could have written. Error
    direction: toward NO entry (an unreadable pipeline names nothing)."""
    try:
        pipeline = json.loads((Path(root) / "pipeline.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    words, proved = C.probe_gap_words(pipeline), C.probe_not_proved_words(pipeline)
    scope = window.get("scope_instances") if isinstance(window.get("scope_instances"), dict) else {}
    named: dict = {}
    for item in window.get("instances") or []:
        if not isinstance(item, dict) or not isinstance(item.get("probe_gap"), dict):
            continue
        identity = str(item.get("instance_id") or "")
        keys = [identity] + [str(case) for case, ids in scope.items() if isinstance(ids, list) and identity in ids]
        own = list(keys)
        # t-1968 N5 (twin of `window_record.probe_gap_block`): a test whose probe the code critic could not judge (`cannot_judge`) is
        # named ONLY by the person's `probe not proved: <case key>` word of the judgment's time or later, through the one reader of
        # it; the `probe gap:` words (instance, case, `tooling:`, class) are not read for it
        # F1 (t-2007): a record still `unjudged` is the critic's and is named by NO word (instance, case, `tooling:` or class)
        if proof_level.probe_owes_judgment(root, identity, str(item.get("input_hash") or "")) == "unjudged":
            continue
        facts = proof_level.cannot_judge_facts(root, identity, str(item.get("input_hash") or ""))
        if facts is not None:
            found = proof_level.not_proved_word(facts, keys[1:], proved) if identity else None
            if found:
                named[identity] = {"key": f"{C.PROBE_NOT_PROVED_PREFIX} {found[0]}", **found[1]}
            continue
        # the class word `tooling:<language>` (EP1-36), last: the instance's own word and its case's stay first. The same reader
        # as the window's (`proof_level.tooling_gap_key`), over the current hash the item carries.
        keys.append(proof_level.tooling_gap_key(root, identity, str(item.get("input_hash") or "")))
        for key in keys:
            if identity and key in words:
                named[identity] = {"key": key, **words[key]}
                break
        else:
            # GW1-43: AFTER the equality (the person's own word about the instance or its case is quoted by them, not by the
            # class). The decision of the class covers an instance that RAN GREEN whose probe the tool could not read
            # (`proof_level.probe_could_not_run`: no record, other bytes, a stand that was down and a probe that judged are not
            # that). Same condition as `window_record.probe_gap_block`.
            klass = C.probe_gap_class_word(pipeline, own)
            if (identity and klass and item.get("outcome") == "passed"
                    and proof_level.probe_could_not_run(root, identity, str(item.get("input_hash") or ""))):
                named[identity] = dict(klass)
    return named


def validate_window(window, root):
    """Return gaps; malformed/stale claimed proofs are never an accepted green window.

    An instance's gap is classified in ONE order (HF2-4): handed -> stopped (the stand blocked it) -> red by the
    requirement (`contradicts_requirement:<iid>`, asked of `red_by_requirement`, only for an item whose outcome is
    `failed`) -> any other non-`passed` outcome (`product:<iid>`). A handed or stopped item is never red; a red item is
    asked for no probe. Empty outcome (AR-23): a window with no `failed` item makes no call and returns what it
    returned before.

    B-375: handed is believed only as far as the manifest says (`handed_instances`); a claim the manifest does not confirm is
    `handed_unconfirmed:<iid>` (not derivable, never `product:`).

    HF2-11: a `stale_run:<iid>` gap follows the outcome's own gap (never replaces it) for an instance whose latest run
    ran other code than the test holds now; this function stays pure over the record."""
    root = Path(root).resolve()
    # The closed set of dispositions is the carrier's (FR-13), read at the call: `window_record` imports this module at
    # its top, so the import cannot be a module-level one (`python -c "import acceptance"` loads no `window_record`).
    from window_record import REQUIRED_ROW_FIELDS
    dispositions = REQUIRED_ROW_FIELDS["change_disposition"].values
    required = window.get("required_quality_checks")
    if not isinstance(required, list):
        raise ValueError("required_quality_checks must be explicit, including an empty list")
    receipts = {r["id"]: r for r in window.get("quality_receipts", [])}
    gaps = []
    # HF4-10: only a check a factory script produces a receipt for is owed (the ONE reader); a window of 0.10.3 that
    # lists the readiness ids reads as owing none. Error direction: toward owing (see the reader).
    from window_record import demanded_quality_checks
    for name in demanded_quality_checks(required)[0]:
        receipt = receipts.get(name, {})
        if receipt.get("status") != "passed" or receipt.get("input_hash") != window.get("input_hash"):
            gaps.append("quality:" + name)
    # An item that CLAIMS the blocked outcome is believed only as far as the manifest says so (B3): the same
    # reader window_record used, run again over the manifest under `root`.
    claims = [i for i in window.get("instances", []) if isinstance(i, dict) and i.get("outcome") == BLOCKED_OUTCOME]
    blocked = (blocked_instances(_manifest_under(root), claims, window.get("scope_instances"), root)
               if claims else {})
    # B-375: the same for an item that CLAIMS `handed_to_person` - ONE call (`handed_instances`), never for a window with no
    # such item (AR-23: that window returns exactly what it returned before). Error direction (AR-28): a manifest absent or
    # unreadable, no scope map, a run of the instance - anything the reader cannot establish is "not handed".
    handed_claims = [i for i in window.get("instances", []) if isinstance(i, dict) and i.get("outcome") == HANDED_OUTCOME]
    handed_ok = (handed_instances(_manifest_under(root), handed_claims, window.get("scope_instances"), root)
                 if handed_claims else {})
    # t-2181 PC-4 (B2): the same for an item that CLAIMS `pending_implementation` - ONE call (`pending_instances`) over the manifest
    # and the story's sides under `root`, never for a window with no such item. A claim the reader does not name (no row, a
    # side the story does not call absent, a terminal run of it) is not excused: it is an outcome other than `passed`
    # (`product:`) and a probe is owed as for any instance that could run (AR-28, error direction "not pending").
    pending_claims = [i for i in window.get("instances", []) if isinstance(i, dict) and i.get("outcome") == PENDING_OUTCOME]
    pending_ok = (pending_instances(_manifest_under(root), pending_claims, window.get("scope_instances"),
                                    C.story_sides(read_json(root / "pipeline.json", {}, kind=dict)))
                  if pending_claims else {})
    # HF1-14: the words that name a probe gap, read once (E11: an item without `probe_gap` is judged exactly as before).
    gap_words = probe_gap_named(window, root) if any(
        isinstance(i, dict) and isinstance(i.get("probe_gap"), dict) for i in window.get("instances", [])) else {}
    # HF2-4: an item that claims it RAN RED is believed a red-by-requirement only as far as the manifest says so, by the
    # ONE reader (AR-13): one call over the manifest and the run blocks under `root` (v-b: the latest terminal run of the
    # instance is `failed`), asked ONLY about items whose outcome is `failed` - a handed or blocked item is never red
    # (the position of the red branch below, after handed and stopped, keeps that unreachable too). Error direction
    # (FR-59): anything the reader cannot establish is "not red", and the gap stays `product:`.
    ran_red = [i for i in window.get("instances", []) if isinstance(i, dict) and i.get("outcome") == "failed"]
    red = (red_by_requirement(_manifest_under(root), ran_red, window.get("scope_instances"), root)
           if ran_red else {})
    for item in window.get("instances", []):
        identity = str(item.get("instance_id") or "?")
        if not item.get("instance_id") or not item.get("input_hash"):
            gaps.append("malformed_instance:" + identity)
            continue
        claimed_handed = item.get("outcome") == HANDED_OUTCOME
        handed = claimed_handed and identity in handed_ok
        unconfirmed = claimed_handed and not handed
        stopped = item.get("outcome") == BLOCKED_OUTCOME and identity in blocked
        pending = item.get("outcome") == PENDING_OUTCOME and identity in pending_ok
        explained = not handed and not stopped and identity in red
        if unconfirmed:
            # FIRST in the chain, and the invariant that position keeps: a claim the manifest does not confirm never produces
            # `handed_to_person:` (no pair is ever derived over it) and never `product:` (the fault is the record's, not the
            # product's, FR-46). `stopped` and `explained` stay unreachable for it by construction: they need outcome
            # `blocked_by_env` / `failed`.
            gaps.append(HANDED_UNCONFIRMED_KIND + ":" + identity)
        elif handed:
            gaps.append(HANDED_OUTCOME + ":" + identity)
        elif stopped:
            gaps.append(BLOCKED_OUTCOME + ":" + identity)
        elif explained:
            # a red test a `contradicts_requirement` row explains is an OUTCOME, not a defect of this record: S7 judges
            # it (FR-21, FR-34); its review is the critic's `approved` below, bound to the bytes like any other
            gaps.append(CONTRADICTS_REQUIREMENT + ":" + identity)
        elif pending:
            pass        # excused by the reader that excuses its run, its probe and its witness (C5): no outcome gap
        elif item.get("outcome") != "passed":
            gaps.append("product:" + identity)
        # HF2-11: the instance's latest run ran other code than the test holds now (the item's `run_identity` against
        # its `instance_identity`, `run_freshness_of`). Position: after the outcome is classified, before any review
        # check - the invariant is that a run of other code never closes the window as the run it claims to be. An
        # item that ran nothing here (handed, stopped) has no run to be stale; a red, explained by its row or not,
        # keeps its own gap and gets this one beside it. Unknown (no `run_identity`, no `instance_identity`) is NOT a
        # gap - it leaves today's reading, and `window_record.verdict` prints it.
        if not handed and not stopped and not pending and run_freshness_of(item)[0] == "stale":
            gaps.append("stale_run:" + identity)
        # An item that ran green, owes a live check and CARRIES a probe gap (HF1-14): reviewed statically, like a
        # blocked one. Decided before the review because the review word depends on it.
        gapped = (isinstance(item.get("probe_gap"), dict) and item.get("outcome") == "passed"
                  and proof_level.proof_required(item, {}))
        if stopped:
            # a static review only: `approved` (or anything else) on a test that never ran is a review gap (E5)
            if item.get("review", {}).get("verdict") != BLOCKED_REVIEW_VERDICT:
                gaps.append("review:" + identity)
        elif handed:
            # a test the person runs is reviewed statically (s5.md): the charter's `unverified`, or `approved`; `rejected`
            # or no word is a review gap, and the word is bound to the bytes like any other
            if item.get("review", {}).get("verdict") not in HANDED_REVIEW_VERDICTS:
                gaps.append("review:" + identity)
            elif not _bound_to(item, item["review"], window, root):
                gaps.append("stale_review:" + identity)
        elif gapped:
            # the same for a probe that never ran (F5): `approved` would claim a live check that never happened
            if item.get("review", {}).get("verdict") != BLOCKED_REVIEW_VERDICT:
                gaps.append("review:" + identity)
            elif not _bound_to(item, item["review"], window, root):
                gaps.append("stale_review:" + identity)
        elif item.get("review", {}).get("verdict") != "approved":
            gaps.append("review:" + identity)
        elif not _bound_to(item, item["review"], window, root):
            gaps.append("stale_review:" + identity)
            record = mechanical_round(window)
            if record and item["review"].get("input_hash") == record["reviewed_input_hash"]:
                # The record claims a mechanical round but no green run of its author on
                # these bytes exists: the missing piece is named, never guessed at.
                gaps.append("mechanical_green:" + identity)
        disposition = item.get("change_disposition")
        if item.get("schema_version", window.get("schema_version", 1)) == 2:
            obligation_ids = item.get("obligation_ids")
            if obligation_ids is None and item.get("obligation_id"):
                obligation_ids = [item["obligation_id"]]
            if (not isinstance(obligation_ids, list) or not obligation_ids or
                    any(not isinstance(x, str) or not x for x in obligation_ids) or
                    len(obligation_ids) != len(set(obligation_ids))):
                gaps.append("obligation_binding:" + identity)
            if not item.get("obligation_hash"):
                gaps.append("obligation_hash:" + identity)
            if not item.get("assertion_id"):
                gaps.append("assertion_identity:" + identity)
            if not item.get("defect_location"):
                gaps.append("defect_location:" + identity)
        if disposition not in dispositions:
            gaps.append("change_disposition:" + identity)
        elif not item.get("change_basis_ref"):
            gaps.append("change_basis:" + identity)
        # ONE predicate for "a live check is demanded" (proof_level.proof_required). The handed
        # exemption stays here because a window item says it by its outcome, not by the manifest. A blocked
        # instance never ran, so there is nothing to mutate and no probe is demanded (B2); its review is the
        # critic's static word (`unverified`) and says so.
        if gapped:
            # No probe exists to judge, so the sensitivity, semantic, level and probe-evidence checks do not run
            # (saying `sensitivity:` would claim a probe ran and missed). The gap is named, or it is unrecorded.
            gaps.append((PROBE_GAP_KIND if identity in gap_words else PROBE_GAP_UNRECORDED_KIND) + ":" + identity)
        elif proof_level.proof_required(item, {}) and not handed and not stopped and not explained and not pending:
            # (`explained`: no probe is asked of a red test - whether the mutated run fails at the intended assert
            # depends on the order of the asserts, F-20 (a); the item records `probe_not_applicable` instead)
            probe = item.get("probe", {})
            if (probe.get("verdict") != "intended_failure" or
                    not _bound_to(item, probe, window, root) or
                    not probe.get("expected_location") or
                    probe.get("expected_location") != probe.get("actual_location") or
                    not probe.get("expected_reason") or
                    probe.get("expected_reason") != probe.get("actual_reason") or
                    probe.get("failure_kind") != "assertion"):
                gaps.append("sensitivity:" + identity)
            if item.get("schema_version", window.get("schema_version", 1)) == 2:
                obligation_ids = item.get("obligation_ids") or ([item.get("obligation_id")]
                                                                  if item.get("obligation_id") else [])
                probe_ids = probe.get("obligation_ids") or ([probe.get("obligation_id")]
                                                              if probe.get("obligation_id") else [])
                evidence_paths = {ref.get("path") for ref in item.get("evidence_refs", [])
                                  if isinstance(ref, dict) and ref.get("path") and ref.get("sha256")}
                if (probe_ids != obligation_ids or
                        probe.get("obligation_hash") != item.get("obligation_hash") or
                        probe.get("defect_location") != item.get("defect_location") or
                        probe.get("assertion_id") != item.get("assertion_id") or
                        probe.get("defect_location") == probe.get("expected_location") or
                        # a probe of another line than the obligation's check proves nothing about it (FR-18):
                        # the one reader names it, by the recorded fact (`target`), never by a role's judgment
                        proof_level.receipt_off_target(probe)):
                    gaps.append("semantic_sensitivity:" + identity)
                # Which level a probe is, and what mutation that level is made of, is
                # `proof_level`'s to say (D-0010): a probe that claims to catch a broken product
                # must have mutated the product, a live check's mutation is the assertion and asks
                # nothing more, and a level the vocabulary does not know is its own gap.
                problem = proof_level.probe_problem(probe)
                if problem == "level":
                    gaps.append("probe_level:" + identity)
                elif problem == "mutation_kind":
                    gaps.append("probe_mutation_kind:" + identity)
                if not probe.get("evidence_ref") or probe.get("evidence_ref") not in evidence_paths:
                    gaps.append("probe_evidence:" + identity)
        if (stopped or handed) and item.get("evidence_refs") == []:
            # a blocked test that never ran has no run to cite; its unresolved[] row is the record of it. One
            # that DID run (and failed) cites the run block like any other and is checked below (C4). The same for a test
            # the manifest hands to the person (B-375): it claims no execution, so it owes no evidence.
            continue
        if not isinstance(item.get("evidence_refs"), list) or not item.get("evidence_refs"):
            gaps.append("evidence:" + identity)
            continue
        for evidence in item.get("evidence_refs", []):
            if not isinstance(evidence, dict) or not evidence.get("path") or not evidence.get("sha256"):
                gaps.append("evidence:" + identity)
                continue
            path = (root / evidence["path"]).resolve()
            if (not path.is_relative_to(root) or not path.is_file() or
                    hashlib.sha256(path.read_bytes()).hexdigest() != evidence["sha256"]):
                gaps.append("evidence:" + identity)
    # Appended last and sorted with the rest: a window whose list is empty (or that has no such list at
    # all) returns exactly what it returned before this check, and a window that lists a change with no
    # good verdict is not clean, so the controller takes it only as an unresolved acceptance
    # (`controller.py`: `other_gaps` need `unresolved` and a `reason`) - the informed pass.
    gaps.extend(gap for gap, _code in expectation_change_gaps(window))
    if not window.get("instances") and not window.get("not_applicable_reason"):
        gaps.append("empty_scope")
    return sorted(set(gaps))


# --------------------------------------------------------------------------------------------
# The stage acceptance record (X2-5, t-1765): the stage critic's verdict on S2-S4, kept in `pipeline.json` `acceptance`.
# Code owns the DATA - the record's keys, its form, its binding to the author's last accepted dispatch, its transport; the
# MEANING of the verdict is the critic's (AR-29). ONE reader (`stage_acceptance`), ONE writer (`stage_done.py --acceptance`).
# --------------------------------------------------------------------------------------------
STAGE_ACCEPTANCE_FIELDS = ("stage", "role", "acceptor", "reviewed_dispatch", "verdict", "failure_class", "quote",
                           "witness_paths", "at")
FAILURE_CLASSES = ("spec", "capability", "data", "tooling")
STAGE_ACCEPTANCE_SIDES = ("accept", "reject")
DRIVER_ACCEPTOR = "driver"          # a conductor's `accept with a gap` recorded by the driver (the critic's last round spent)
# Every problem line below carries this phrase, so ONE recorded person's word (`waiver.py --block "stage acceptance"`) names them all.
STAGE_ACCEPTANCE_PHRASE = "stage acceptance"


def stage_def_of(stage, table=None) -> dict:
    """The row of `stage` in `references/stages.json` (`{}` when there is none): THE reader is `contract._stage_entry`; the stage's
    `acceptance_by` is the data that switches the gate on (AR-1). Never raises."""
    try:
        return dict(C._stage_entry(str(stage or ""), table))
    except Exception:  # noqa: BLE001 - a table that cannot be read switches nothing on
        return {}


def stage_acceptance_table() -> dict:
    """`{critic's verdict word: accept|reject}` from `handoffs/vocabulary.yaml` `stage_acceptance_verdicts`; `{}` when it cannot be read
    (then no word is known, and no record is ever `accept` by the table)."""
    try:
        import handoff
        raw = handoff.vocabulary().get("stage_acceptance_verdicts")
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items() if str(v) in STAGE_ACCEPTANCE_SIDES}


def stage_acceptance_verdict(word) -> str:
    """`accept`, `reject` or `""` (the word is not in the table). The direction of error is `""`, never `accept`."""
    return stage_acceptance_table().get(str(word or "").strip(), "")


def stage_acceptance(pipeline, stage) -> dict | None:
    """THE reader of the record (AR-13): the LAST round of `pipeline["acceptance"][stage]`, or None (absent, not a list, no mapping in it)."""
    rounds = (pipeline.get("acceptance") if isinstance(pipeline, dict) else None)
    rounds = rounds.get(str(stage)) if isinstance(rounds, dict) else None
    found = [r for r in rounds if isinstance(r, dict)] if isinstance(rounds, list) else []
    return found[-1] if found else None


def _path_problem(path) -> str:
    text = str(path) if isinstance(path, str) else ""
    if not text.strip():
        return "is empty"
    flat = text.replace("\\", "/")
    if flat.startswith("/") or (len(flat) > 1 and flat[1] == ":") or ".." in flat.split("/"):
        return "is not a task-relative path"
    return ""


def stage_acceptance_errors(record, *, stage_def, author_dispatch) -> list:
    """Why a stage acceptance record is not acceptable as the acceptance of `author_dispatch`; [] when it is. FORM AND BINDING ONLY (class
    `shape`): the record's keys, a `verdict` of `accept|reject`, on `reject` a `failure_class` of the four and a non-empty `quote`, on
    `accept` no `failure_class`, `witness_paths` as task-relative paths (empty is legal), an `acceptor` that is the stage's `acceptance_by` or
    `driver` and is not the reviewed role, and `reviewed_dispatch` equal to `author_dispatch`. What the verdict MEANS is never read here
    (the critic's judgment, FR-12). INVARIANT: a record given for another dispatch of the author (before a rework) never counts. No record
    (`None`) is one problem naming the stage and the dispatch."""
    stage_def = stage_def if isinstance(stage_def, dict) else {}
    stage = str(stage_def.get("id") or "")
    label = f"{stage} has" if stage else "the stage has"
    if not isinstance(record, dict):
        return [f"{label} no {STAGE_ACCEPTANCE_PHRASE} for {author_dispatch or 'the last dispatch of its author'}"]
    head = f"{STAGE_ACCEPTANCE_PHRASE} record of {stage or 'the stage'}: "
    problems = []
    missing = [k for k in STAGE_ACCEPTANCE_FIELDS if k not in record]
    if missing:
        problems.append(head + "missing " + ", ".join(missing) + "; expected " + ", ".join(STAGE_ACCEPTANCE_FIELDS))
    if stage and "stage" in record and record["stage"] != stage:
        problems.append(head + f"it is for {record['stage']!r}, not {stage}")
    verdict = record.get("verdict")
    if "verdict" in record and verdict not in STAGE_ACCEPTANCE_SIDES:
        problems.append(head + f"verdict {verdict!r} is not one of " + "|".join(STAGE_ACCEPTANCE_SIDES))
    if verdict == "reject":
        if "failure_class" in record and record["failure_class"] not in FAILURE_CLASSES:
            problems.append(head + f"a reject needs failure_class, one of {', '.join(FAILURE_CLASSES)} (got {record['failure_class']!r})")
        if "quote" in record and not (isinstance(record["quote"], str) and record["quote"].strip()):
            problems.append(head + "a reject needs a quote: the critic's words from the artifact, with its path")
    elif verdict == "accept" and record.get("failure_class") is not None:
        problems.append(head + "an accept has failure_class null")
    paths = record.get("witness_paths")
    if "witness_paths" in record:
        if not isinstance(paths, list):
            problems.append(head + "witness_paths must be a list of task-relative paths (empty is allowed)")
        else:
            problems += [head + f"witness_paths[{i}] {_path_problem(p)}" for i, p in enumerate(paths) if _path_problem(p)]
    acceptor, role = record.get("acceptor"), record.get("role")
    allowed = [a for a in (stage_def.get("acceptance_by"), DRIVER_ACCEPTOR) if isinstance(a, str) and a]
    if "acceptor" in record and acceptor not in allowed:
        problems.append(head + f"acceptor {acceptor!r} is not {' or '.join(allowed)}")
    if "role" in record and not (isinstance(role, str) and role.strip()):
        problems.append(head + "role (the author reviewed) is empty")
    if "acceptor" in record and "role" in record and acceptor == role:
        problems.append(head + "the acceptor is the role it reviewed; a role does not accept its own work")
    if "reviewed_dispatch" in record and record["reviewed_dispatch"] != author_dispatch:
        problems.append(head + f"it is for {record['reviewed_dispatch']!r}, the last dispatch of the author is {author_dispatch or 'none yet'!r}: "
                        "a record given for other bytes does not count")
    return problems


SUPERSEDED_WORD = "stage_superseded"         # the open-work word of a consumer's finish that sent the upstream handoff back (its own work is stale)
AWAITS_WORD = "stage_awaits_acceptance"      # the open-work word an author's finish carries when its stage is judged by a CONSUMER role (X7-6)


def unresolved_has_word(dispatch, word) -> bool:
    """True when the `unresolved` field of the dispatch record names `word` EXACTLY (a token of a string, of a list item, or of the
    `id`/`word` of a mapping item) - never a substring of the `reason` or of a quote (m2 of t-1860). Pure; crooked input is False."""
    import re
    raw = dispatch.get("unresolved") if isinstance(dispatch, dict) else None
    items = raw if isinstance(raw, list) else [raw]
    texts = []
    for item in items:
        if isinstance(item, dict):
            texts += [str(item.get(k)) for k in ("id", "word", "unresolved") if isinstance(item.get(k), str)]
        elif isinstance(item, str):
            texts.append(item)
    return any(token == word for text in texts for token in re.split(r"[\s,;:]+", text))


def author_dispatches(state, stage_def) -> list:
    """THE reading of "the author's dispatches of the CURRENT life" (AR-13; M4 and m5 of t-1860): the dispatches of the stage's first role,
    in the state's creation order, that are neither a read-only INVESTIGATION of S7 (`controller.s7_part_of`: it is no triage and nothing
    to accept) nor superseded (`stage_superseded`: a consumer sent its upstream handoff back, so this one is stale work). Status is left to
    the caller. `[]` for a stage with no roles."""
    roles = [str(r) for r in (stage_def or {}).get("roles") or []]
    stage = str((stage_def or {}).get("id") or "")
    if not roles or not stage:
        return []
    from controller import s7_part_of
    held = (state or {}).get("dispatches") if isinstance(state, dict) else None
    return [d for d in (held.values() if isinstance(held, dict) else [])
            if isinstance(d, dict) and d.get("stage") == stage and d.get("role") == roles[0]
            and not s7_part_of(d) and not unresolved_has_word(d, SUPERSEDED_WORD)]


def stage_author_dispatch(state, stage_def, current=None) -> str:
    """The id of the author's last ACCEPTED dispatch of the stage's current life (`author_dispatches`), in the state's creation order; the
    dispatch being accepted when it is the author's own; `""` when there is none."""
    roles = [str(r) for r in (stage_def or {}).get("roles") or []]
    stage = str((stage_def or {}).get("id") or "")
    if not roles or not stage:
        return ""
    if isinstance(current, dict) and current.get("stage") == stage and current.get("role") == roles[0]:
        return str(current.get("id") or "")
    found = ""
    for d in author_dispatches(state, stage_def):
        if d.get("status") == "accepted":
            found = str(d.get("id") or "")
    return found


def accepted_for(pipeline, stage, author, acceptor=None) -> bool:
    """THE accept predicate (AR-13): an `accept` record stands for the dispatch `author` of `stage` (its `reviewed_dispatch` is exactly that
    dispatch), by `acceptor` when one is named. A missing author or record is False - an unknown never accepts."""
    record = stage_acceptance(pipeline, stage)
    return bool(author and isinstance(record, dict) and record.get("verdict") == "accept" and record.get("reviewed_dispatch") == author
                and (acceptor is None or record.get("acceptor") == acceptor))


def consumer_dispatch(state, consumer_stage, consumer_role, after) -> str:
    """The id of the consumer's LAST accepted, not superseded dispatch of `consumer_stage` created AFTER the dispatch `after` (the author's
    dispatch it judges), in the state's creation order; `""` when there is none or `after` is unknown (M2 of t-1860: a consumer's dispatch of an
    earlier life is another handoff's judge and never stands for this one)."""
    seen, found = False, ""
    held = (state or {}).get("dispatches") if isinstance(state, dict) else None
    for d in (held.values() if isinstance(held, dict) else []):
        if not isinstance(d, dict):
            continue
        if str(d.get("id") or "") == after:
            seen = True
        elif (seen and d.get("stage") == consumer_stage and d.get("role") == consumer_role and d.get("status") == "accepted"
              and not unresolved_has_word(d, SUPERSEDED_WORD)):
            found = str(d.get("id") or "")
    return found


def awaits_acceptance(state, stage, pipeline=None, table=None) -> str:
    """THE reader (AR-13) of "the author stopped, its stage awaits the consumer's acceptance": the id of the author's LAST dispatch of
    `stage` when it is accepted with the open-work word `stage_awaits_acceptance` and the stage has an `acceptance_by` that is not one
    of its own roles (a consumer in the next stage), the stage is not completed, and - with `pipeline` given - no `accept` record
    stands for that dispatch; `""` otherwise. The dispatch gate, `next`, `stage_guard.rule_order` and the stage hosts all ask it. A
    stage with no `acceptance_by` (the world before X7-6) never awaits. Direction of error: an unreadable state is `""`."""
    stage_def = stage_def_of(stage, table)
    acceptor = stage_def.get("acceptance_by")
    roles = [str(r) for r in stage_def.get("roles") or []]
    if not acceptor or not roles or acceptor in roles or not isinstance(state, dict):
        return ""
    entry = (state.get("stages") or {}).get(stage) if isinstance(state.get("stages"), dict) else None
    if isinstance(entry, dict) and entry.get("status") == "completed":
        return ""
    # ONE reading of the author's dispatches with `stage_author_dispatch` (`author_dispatches`: the current life, no investigation, no
    # superseded one); a dispatch that never ran or was released (DISCOUNTED) is no author work either, so a cancelled relaunch after the
    # accepted, awaiting dispatch does not end the wait (m5). A live one (running) after it does: the author works again.
    from controller import DISCOUNTED
    rows = [d for d in author_dispatches(state, stage_def) if d.get("status") not in DISCOUNTED]
    last = rows[-1] if rows else None
    if not last or last.get("status") != "accepted":
        return ""
    did = str(last.get("id") or "")
    # The stop is marked by the author's own finish (the awaits word) OR, when its work ended AFTER the finish (S7: the repairs run after the
    # analyst's finish), by the driver's marker `pipeline["acceptance_awaits"][stage] == <that last dispatch>` (X7-6b; this is the one reader).
    marks = pipeline.get("acceptance_awaits") if isinstance(pipeline, dict) else None
    marked = isinstance(marks, dict) and marks.get(stage) == did
    if not unresolved_has_word(last, AWAITS_WORD) and not marked:
        return ""
    if pipeline is not None and accepted_for(pipeline, stage, did):
        return ""
    return did


def consumer_of(stage, table=None) -> str:
    """The consumer role that accepts `stage` from a LATER stage (`acceptance_by` outside the stage's own roles), or `""`."""
    stage_def = stage_def_of(stage, table)
    by = stage_def.get("acceptance_by")
    return str(by) if by and by not in (stage_def.get("roles") or []) else ""


def consumer_close_refusal(pipeline, state, stage, table=None) -> str:
    """The text that refuses `stage_done --status done` for a stage whose acceptor is a CONSUMER role (X7-6), or `""`. The author's last accepted
    dispatch must have an `accept` record (the consumer's, or the conductor's `driver` accept); a stage whose author never ran (closed by code
    with nothing to judge, E-23) or that has no consumer is refused nothing. Names the missing record and the door (FR-1, FR-2)."""
    consumer = consumer_of(stage, table)
    if not consumer:
        return ""
    stage_def = stage_def_of(stage, table)
    author = stage_author_dispatch(state, stage_def)
    if not author:
        return ""
    if accepted_for(pipeline, stage, author):
        return ""
    ticket = (pipeline.get("ticket") if isinstance(pipeline, dict) else None) or "<T>"
    return (f"{stage} is closed by the {STAGE_ACCEPTANCE_PHRASE} of {consumer}, and none stands for {author}. Dispatch {consumer} (it is let in "
            f"while {stage} awaits) and record its verdict: `stage_done.py --task {ticket} --stage {stage} --acceptance work/handoffs/<its dispatch>.yaml`.")


def author_exit_owes_plan(dispatch, table=None) -> bool:
    """True when `dispatch` is the AUTHOR of a stage that has an acceptor (`acceptance_by`): its exit window is no longer the closing one,
    and S3's plan check must still run on it (E-X2-5f). False for every stage without `acceptance_by` (the world before X2-7)."""
    d = dispatch if isinstance(dispatch, dict) else {}
    stage_def = stage_def_of(d.get("stage"), table)
    roles = stage_def.get("roles") or []
    return bool(stage_def.get("acceptance_by") and roles and d.get("role") == roles[0])


def stage_acceptance_refusal(pipeline, dispatch, state, split, table=None) -> tuple:
    """`(refusal text, passed)` of the E-B11 gate for the accept of `dispatch` that claims `stage_complete`. `("", [])` when the stage has no
    `acceptance_by` (TEMPORAL: nothing new is refused before X2-7 sets it) or its record is acceptable. `split(stage, problems)` is the
    controller's `_passed_by_person`: a problem a person's recorded word passes (`waiver.py --block "stage acceptance"`) is returned in
    `passed`, not refused. A verdict `reject` is a problem the same way (the critic sent the stage back). Never reads the verdict's meaning."""
    d = dispatch if isinstance(dispatch, dict) else {}
    stage = str(d.get("stage") or "")
    stage_def = stage_def_of(stage, table)
    if not stage_def.get("acceptance_by"):
        return "", []
    author = stage_author_dispatch(state, stage_def, d)
    record = stage_acceptance(pipeline, stage)
    problems = stage_acceptance_errors(record, stage_def=stage_def, author_dispatch=author)
    if not problems and record.get("verdict") == "reject":
        problems = [f"{STAGE_ACCEPTANCE_PHRASE}: the stage critic rejected it: {record.get('quote')}"]
    if not problems:
        return "", []
    blocking, passed = split(stage, problems)
    if not blocking:
        return "", passed
    import person_words
    ticket = (pipeline.get("ticket") if isinstance(pipeline, dict) else None) or "<T>"
    waiver = person_words.door(f"waiver.py --task {ticket} --stage {stage} --block \"{STAGE_ACCEPTANCE_PHRASE}\"")
    consumer = consumer_of(stage, table)
    if consumer:
        # X7-6 (E-8): the judge is the CONSUMER role of the next stage; the author never closes the stage by its own finish.
        return (f"{stage} cannot be closed by {d.get('role') or 'its author'}'s own finish: " + "; ".join(blocking) + f". Finish with `--not-complete "
                f"--unresolved {AWAITS_WORD} --reason \"<what {consumer} is to judge>\"`; then dispatch `{consumer}` (it is let in while {stage} "
                f"awaits) and its finish records the verdict from its form: `stage_done.py --task {ticket} --stage {stage} --acceptance "
                f"work/handoffs/<{consumer} dispatch>.yaml`, or pass it with a person's word: `" + waiver + "`"), passed
    return (f"{stage} cannot be closed: " + "; ".join(blocking) + f". Dispatch the stage critic (`{stage_def['acceptance_by']}`, stage {stage}) and "
            f"record its verdict: `stage_done.py --task {ticket} --stage {stage} --acceptance work/handoffs/<its dispatch>.yaml`, "
            "or pass it with a person's word: `" + waiver + "`"), passed


def stage_acceptance_from_form(form, *, stage, role, acceptor, reviewed_dispatch, witness_form, at) -> tuple:
    """`(record | None, problems)` from the stage critic's handoff form (`handoff.parse(...).data`): the verdict WORD is the form's
    `header.verdict` (the digest's verdict line), mapped by the table; the rest is the form's section `stage_acceptance`
    (`failure_class`, `quote`, `witness_paths`). A word outside the table gives no record. An `accept` carries no `failure_class` whatever
    the form says. Pure; form and transport only."""
    form = form if isinstance(form, dict) else {}
    header = form.get("header") if isinstance(form.get("header"), dict) else {}
    word = str(header.get("verdict") or "").strip()
    side = stage_acceptance_verdict(word)
    if not side:
        known = "|".join(stage_acceptance_table()) or "none readable"
        return None, [f"{STAGE_ACCEPTANCE_PHRASE}: verdict word `{word}` is not one of {known}; the form must end its header with one of them"]
    section = form.get("stage_acceptance") if isinstance(form.get("stage_acceptance"), dict) else {}
    paths = section.get("witness_paths")
    failure = section.get("failure_class")
    record = {"stage": stage, "role": role, "acceptor": acceptor, "reviewed_dispatch": reviewed_dispatch, "verdict": side,
              "failure_class": (str(failure) if failure not in (None, "") else None) if side == "reject" else None,
              "quote": str(section.get("quote") or "").strip(),
              "witness_paths": [str(p) for p in paths] if isinstance(paths, list) else [], "at": at}
    if not record["witness_paths"] and witness_form and side == "reject":
        record["witness_paths"] = [witness_form]
    return record, []
