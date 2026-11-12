"""finalize_task: a ghost row a later rerun answered stops deciding the story.

TP2-2553: the first run block spelled `TC-009` — a CASE id — in `instance_id`, so the
reducer could not join it to any manifest instance and stamped it `partial` /
`instance_manifest_join_failed`. The corrected rerun under the real instance ids superseded
nothing, because supersession existed only for `env_blocked` rows. Four such ghosts made
`execution_status: not_executed` over twelve green results, and gate B read a story that had
never run.
"""
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

import contract as C  # noqa: E402
import finalize_task as F  # noqa: E402

MANIFEST = {"tests": [{"case": "TC-009", "covers": ["TC-009"], "file": "tests/test_search.py",
                       "instance_id": "test_search[eu]", "selector": "test_search"}]}


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def task_with(blocks: list, manifest: dict = None) -> Path:
    """A task root holding the given run blocks, newest last. `blocks` are
    `(name, attempt_started_at, results)` or `(name, attempt_started_at, results, extra)` where
    `extra` is more block fields; a `None` stamp is an unordered block."""
    root = temp_dir("qa-reducer-ghost-")
    task = root / "qa-factory" / "artifacts" / "TP2-2553"
    write(task / "work" / "automation-manifest.json",
          MANIFEST if manifest is None else manifest)
    for name, started, results, *more in blocks:
        block = {"block_id": name, "results": results, **(more[0] if more else {})}
        if started:
            block["attempt_started_at"] = started
        write(task / "work" / "run-blocks" / f"{name}.json", block)
    return task


@contextmanager
def story(blocks: list, manifest: dict = None, pipeline: dict = None, prepare=None):
    """`(task, the reduced report)` of a story; the temp tree goes when the block ends. `prepare(task)`
    runs before the reduction (files a block names, for instance)."""
    task = task_with(blocks, manifest)
    try:
        if pipeline is not None:
            write(task / "pipeline.json", pipeline)
        if prepare is not None:
            prepare(task)
        yield task, F.reduce(task)[0]
    finally:
        cleanup(task.parents[2])


def raw_report(outcome: str, block: str):
    """`prepare` for `story`: a junit of the function `test_m.test_old[x]` written under the story, sha-checked
    and named in the block's `evidence` — the block's OWN raw report, which decides whether a red is one."""
    def put(task: Path) -> None:
        inner = {"failed": '<failure message="assert 1 == 2"/>'}.get(outcome, "")
        xml = ('<testsuites><testsuite name="s" tests="1"><testcase classname="tests.test_m" '
               f'name="{OLD_X}">{inner}</testcase></testsuite></testsuites>').encode("utf-8")
        relative = f"evidence/runs/{block}/report.junit.xml"
        (task / relative).parent.mkdir(parents=True, exist_ok=True)
        (task / relative).write_bytes(xml)
        path = task / "work" / "run-blocks" / f"{block}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["evidence"] = [{"reporter": "junit-xml", "report_path": relative,
                             "report_sha256": hashlib.sha256(xml).hexdigest()}]
        write(path, data)
    return put


def current_ids(report: dict) -> list:
    return [str(row.get("instance_id")) for row in report["current_results"]]


def kept_row(report: dict, instance: str) -> dict:
    """The row of `results[]` for one instance (the first: a ghost keeps its place there)."""
    return next(row for row in report["results"] if row.get("instance_id") == instance)


T1, T2, T3 = "2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z", "2026-09-22T12:00:00Z"
OLD_X = "test_old[x]"
MOD_ID = "tests/test_m.py::"


GHOST = [{"case": "TC-009", "instance_id": "TC-009", "status": "passed"}]
REAL = [{"case": "TC-009", "instance_id": "test_search[eu]", "status": "passed",
         "attempt_id": "a2"}]


def ghost_superseded() -> None:
    task = task_with([("first", "2026-09-22T10:00:00Z", GHOST),
                      ("second", "2026-09-22T11:00:00Z", REAL)])
    try:
        report, _ = F.reduce(task)
        check_eq("the rerun leaves exactly one current row", len(report["current_results"]), 1)
        check_eq("and it is the joined instance",
                 report["current_results"][0].get("instance_id"), "test_search[eu]")
        check_eq("the story ran and passed", report["execution_status"], "passed")
        ghost = next(row for row in report["results"] if row.get("instance_id") == "TC-009")
        check_eq("the ghost is kept for diagnosis", ghost.get("superseded"), True)
        check_eq("under the reducer's own word for it",
                 ghost.get("current_reason"), C.SUPERSEDED_BY_RERUN)
        check_eq("naming what answered it",
                 (ghost.get("superseded_by") or {}).get("instance_id"), "test_search[eu]")
        check_eq("with the attempt and its outcome",
                 [(ghost.get("superseded_by") or {}).get("attempt_id"),
                  (ghost.get("superseded_by") or {}).get("status")], ["a2", "passed"])
        finding = next(f for f in report["factory_findings"]
                       if f["code"] == "INSTANCE_MANIFEST_JOIN_FAILED")
        check_eq("and the join finding carries it too",
                 (finding.get("superseded_by") or {}).get("instance_id"), "test_search[eu]")
    finally:
        cleanup(task.parents[2])


def order_decides() -> None:
    """Later by ATTEMPT, never by file order — and an order the reducer already called
    ambiguous supersedes nothing, the rule `_project_env_blocks` follows for the same
    reason: cancelling a recorded gap on a guess is the false green this factory refuses."""
    task = task_with([("aaa-rerun", "2026-09-22T11:00:00Z", REAL),
                      ("zzz-ghost", "2026-09-22T12:00:00Z", GHOST)])
    try:
        report, _ = F.reduce(task)
        ghost = next(row for row in report["results"] if row.get("instance_id") == "TC-009")
        check("a ghost recorded AFTER the green is not superseded by it",
              not ghost.get("superseded"))
        check_in("and it still says what went wrong", "instance_manifest_join_failed",
                 ghost.get("current_reason") or "")
    finally:
        cleanup(task.parents[2])

    task = task_with([("first", None, GHOST), ("second", "2026-09-22T11:00:00Z", REAL)])
    try:
        report, _ = F.reduce(task)
        check_eq("an ambiguous attempt order supersedes nothing",
                 report["attempt_order"], "ambiguous")
        ghost = next(row for row in report["results"] if row.get("instance_id") == "TC-009")
        check("the ghost stands", not ghost.get("superseded"))
        check("and stays current, as the factory's own open item",
              any(row.get("instance_id") == "TC-009" for row in report["current_results"]))
    finally:
        cleanup(task.parents[2])


def a_ghost_does_not_decide_the_run() -> None:
    """An unsuperseded ghost stays visible and stops voting: twelve green results and one row
    our reducer could not join is a run that passed, not a run that never happened."""
    green = [{"case": "TC-009", "instance_id": "test_search[eu]", "status": "passed"}]
    task = task_with([("only", "2026-09-22T10:00:00Z", green + [
        {"case": "TC-404", "instance_id": "TC-404", "status": "passed"}])])
    try:
        report, _ = F.reduce(task)
        check_eq("the green decides the run", report["execution_status"], "passed")
        check("the unjoined row is still current, for the ledger and gate B",
              any(row.get("instance_id") == "TC-404" for row in report["current_results"]))
        check_eq("and it is still counted where the totals are read",
                 report["current_totals"].get("partial"), 1)
    finally:
        cleanup(task.parents[2])

    task = task_with([("only", "2026-09-22T10:00:00Z",
                       [{"case": "TC-404", "instance_id": "TC-404", "status": "passed"}])])
    try:
        report, _ = F.reduce(task)
        check_eq("with nothing joined at all there is still nothing to stand on",
                 report["execution_status"], "not_executed")
    finally:
        cleanup(task.parents[2])


def a_superseded_ghost_is_not_a_delivery_reason() -> None:
    import check_delivery as D
    task = task_with([("first", "2026-09-22T10:00:00Z", GHOST),
                      ("second", "2026-09-22T11:00:00Z", REAL)])
    try:
        report, _ = F.reduce(task)
        write(task / "work" / "run-report.json", report)
        check_eq("the answered join failure is not printed to the person",
                 D.factory_finding_reasons(task), [])
        check("but the entity stays ours, never the product's",
              "TC-009" in D.factory_owned_refs(task))
    finally:
        cleanup(task.parents[2])


def ambiguity_counts_only_kept_blocks() -> None:
    """R-208.1. An accepted reparse carries its original's `attempt_started_at` and instance ids; the
    original is superseded, and counted as a second attempt it made a story with one reparse read
    `ambiguous` (cmp1). The invariant: two DISTINCT kept attempts that start together on one instance
    stay ambiguous, and so does any kept block with no `attempt_started_at` (edge i)."""
    row = dict(REAL[0], attempt_id="a1")
    mapping = {"attempt_id": "a1", "reporter_mapping": {"raw_report_hash": "h1"}}
    with story([("orig", T1, [row], dict(mapping)),
                ("orig-reparse-x", T1, [row], dict(mapping, reparse_of="orig.json",
                                                   supersedes_block_id="orig"))]) as (_t, report):
        check_eq("R-208.1: the superseded original is not a second attempt",
                 [s["id"] for s in report["reducer"]["sources"]], ["orig-reparse-x"])
        check_eq("R-208.1: one kept block, the order is told", report["attempt_order"],
                 "ordered_by_attempt_started_at")
        check("R-208.1: and the instance is not marked ambiguous",
              all(r.get("current_reason") != "ambiguous_attempt_order" for r in report["current_results"]))
    with story([("a", T1, [dict(REAL[0], attempt_id="a1")], {"attempt_id": "a1"}),
                ("b", T1, [dict(REAL[0], attempt_id="a2")], {"attempt_id": "a2"})]) as (_t, report):
        check_eq("R-208.1: two distinct kept attempts with an equal start and one instance stay ambiguous",
                 report["attempt_order"], "ambiguous")
        check_eq("and the instance says so", report["current_results"][0].get("current_reason"),
                 "ambiguous_attempt_order")
        finding = next(f for f in report["factory_findings"] if f["code"] == "AMBIGUOUS_ATTEMPT_ORDER")
        check_in("R-208.7: the finding names its exit: run the instance again", "run the instance again",
                 finding["detail"])
        check_in("R-208.7: with the command and the case", "run_suite.py --mine TC-009", finding["detail"])
    # R-208.7: a later kept block with a DISTINCT start ends the tie between the two older ones
    with story([("a", T1, [dict(REAL[0], attempt_id="a1")], {"attempt_id": "a1"}),
                ("b", T1, [dict(REAL[0], attempt_id="a2")], {"attempt_id": "a2"}),
                ("c", T3, [dict(REAL[0], attempt_id="a3")], {"attempt_id": "a3"})]) as (_t, report):
        check_eq("R-208.7: a third block with a distinct start resolves the tie: the row is no longer ambiguous",
                 (report["current_results"][0].get("current_reason"), report["current_results"][0].get("attempt_id")),
                 (None, "a3"))
        check_eq("R-208.7: and the finding is gone", [f for f in report["factory_findings"]
                                                    if f["code"] == "AMBIGUOUS_ATTEMPT_ORDER"], [])
        check_eq("R-208.7: attempt_order reads ordered when no identity has a live tie", report["attempt_order"],
                 "ordered_by_attempt_started_at")
    # the tie among the LATEST attempts stays, however many older blocks there are
    with story([("a", T1, [dict(REAL[0], attempt_id="a1")], {"attempt_id": "a1"}),
                ("c", T3, [dict(REAL[0], attempt_id="a3")], {"attempt_id": "a3"}),
                ("d", T3, [dict(REAL[0], attempt_id="a4")], {"attempt_id": "a4"})]) as (_t, report):
        check_eq("R-208.7: a tie between the two LATEST attempts stays ambiguous",
                 report["current_results"][0].get("current_reason"), "ambiguous_attempt_order")
    with story([("a", None, [dict(REAL[0])]), ("b", T2, GHOST)]) as (_t, report):
        check_eq("edge (i): a kept block with no attempt_started_at is ambiguous with every other kept block",
                 report["attempt_order"], "ambiguous")
    with story([("only", None, [dict(REAL[0])])]) as (_t, report):
        check_eq("edge (i): one block alone has nothing to be ambiguous with", report["attempt_order"],
                 "ordered_by_attempt_started_at")


def the_pair_decides_not_the_story() -> None:
    """R-208.2. An unrelated ambiguous pair no longer switches off the supersession of a ghost or of an
    environment block elsewhere; an ambiguous PAIR still supersedes nothing."""
    manifest = {"tests": MANIFEST["tests"] + [{"case": "TC-010", "covers": ["TC-010"],
                                               "file": "tests/test_other.py", "instance_id": "test_other[1]",
                                               "selector": "test_other"}]}
    other = lambda attempt: [{"case": "TC-010", "instance_id": "test_other[1]", "status": "passed",  # noqa: E731
                              "attempt_id": attempt}]
    blocks = [("g", T1, GHOST, {"env_blocked": [{"case": "TC-009", "instance_id": "test_search[eu]"}]}),
              ("r", T2, REAL),
              ("x1", T3, other("x1"), {"attempt_id": "x1"}),
              ("x2", T3, other("x2"), {"attempt_id": "x2"})]
    with story(blocks, manifest) as (_t, report):
        check_eq("R-208.2: the global flag still reports the ambiguous pair elsewhere",
                 report["attempt_order"], "ambiguous")
        check("R-208.2: the ghost of an ordered pair is superseded anyway",
              kept_row(report, "TC-009").get("superseded") is True and "TC-009" not in current_ids(report),
              str(kept_row(report, "TC-009")))
        check_eq("R-208.2: and so is the environment block of an ordered pair",
                 [bool(row.get("superseded")) for row in report["env_blocked"]], [True])
        check_eq("R-208.2: nothing of it is still in force", report["current_env_blocked"], [])
    # the pair itself is unordered: one start, two blocks, disjoint instances (the global flag says ordered)
    with story([("g", T1, GHOST, {"env_blocked": [{"case": "TC-009", "instance_id": "test_search[eu]"}]}),
                ("r", T1, REAL)]) as (_t, report):
        check_eq("R-208.2: two blocks with disjoint instances that start together: the story reads ordered",
                 report["attempt_order"], "ordered_by_attempt_started_at")
        check("R-208.2: but the PAIR cannot be ordered: the ghost stands",
              not kept_row(report, "TC-009").get("superseded") and "TC-009" in current_ids(report))
        check_eq("R-208.2: and the environment block stands", len(report["current_env_blocked"]), 1)


def the_join_keeps_the_raw_result() -> None:
    """R-208.3 and edges (ix) and (x)."""
    failed_ghost = {"case": "TC-404", "instance_id": "TC-404", "status": "failed"}
    with story([("only", T1, [dict(REAL[0]), GHOST[0], failed_ghost])]) as (_t, report):
        passed_row, failed_row = kept_row(report, "TC-009"), kept_row(report, "TC-404")
        check_eq("R-208.3: a passed ghost keeps its raw status and is `partial` now",
                 (passed_row.get("raw_status"), passed_row.get("status")), ("passed", "partial"))
        check_eq("R-208.3: a failed ghost keeps its raw status too",
                 (failed_row.get("raw_status"), failed_row.get("status")), ("failed", "partial"))
        check_eq("edge (ix): an identity whose whole history is one block: nothing superseded, `raw_status` written",
                 [bool(kept_row(report, i).get("superseded")) for i in ("TC-009", "TC-404")], [False, False])
        check("R-208.3: a joined row has no raw_status (the overwrite is the join's)",
              "raw_status" not in kept_row(report, "test_search[eu]"))
    stored = dict(GHOST[0], superseded=True, superseded_by={"instance_id": "gone"},
                  current_reason=C.SUPERSEDED_BY_RERUN)
    live_stored = dict(REAL[0], superseded=True, superseded_by={"instance_id": "gone"},
                       current_reason=F.SUPERSEDED_BY_RETRACTION)
    with story([("only", T1, [live_stored, stored])]) as (_t, report):
        ghost = kept_row(report, "TC-009")
        check_eq("edge (x): a stored `superseded: true` is recomputed from the history, not trusted",
                 (ghost.get("superseded"), ghost.get("current_reason")), (None, F.JOIN_FAILED))
        check("edge (x): the ghost is current again", "TC-009" in current_ids(report))
        live = kept_row(report, "test_search[eu]")
        check_eq("edge (x): a live row that carried the mark is live",
                 (live.get("superseded"), live.get("current_reason")), (None, None))


def the_cases_of_a_ghost_include_its_links() -> None:
    """R-208.5. The ghosts of cmp1 carry the cases they prove in `case_version_links` and have no `case`
    cell; the case-level rule found no case and superseded nothing."""
    links = [{"case_id": "TC-009", "version": "v1"}]
    ghost = {"instance_id": OLD_X, "status": "passed", "case_version_links": links}
    with story([("first", T1, [ghost]), ("second", T2, REAL)]) as (_t, report):
        row = kept_row(report, OLD_X)
        check_eq("R-208.5: a ghost with only `case_version_links` is superseded by a later green of the case",
                 (row.get("superseded"), row.get("current_reason")), (True, C.SUPERSEDED_BY_RERUN))
        check_eq("R-208.5: naming what answered it", (row.get("superseded_by") or {}).get("instance_id"),
                 "test_search[eu]")
        check_not_in("R-208.5: and it is no longer current", OLD_X, str(current_ids(report)))
    # the invariant: a ghost that was RED is never covered by a green of another instance
    with story([("first", T1, [dict(ghost, status="failed")]), ("second", T2, REAL)]) as (_t, report):
        row = kept_row(report, OLD_X)
        check_eq("R-208.5: a ghost whose raw status is `failed` is not superseded by another instance's green",
                 (row.get("superseded"), row.get("raw_status")), (None, "failed"))
        check("R-208.5: it stays current and visible", OLD_X in current_ids(report))
    with story([("first", T1, [dict(ghost, status="error")]), ("second", T2, REAL)]) as (_t, report):
        check("R-208.5: `error` is red too", OLD_X in current_ids(report) and not kept_row(report, OLD_X).get("superseded"))


def a_retracted_ghost_is_quenched() -> None:
    """R-208.4 and its edges (ii), (iii), (iv)."""
    def blocks(ghost_status: str = "not_run") -> list:
        return [("b1", T1, [dict(REAL[0]), {"instance_id": OLD_X, "status": ghost_status}])]
    manifest = dict(MANIFEST, retracted_instances=[OLD_X])
    with story(blocks(), manifest) as (task, report):
        row = kept_row(report, OLD_X)
        check_eq("R-208.4: a retracted, not-live ghost is superseded by retraction",
                 (row.get("superseded"), row.get("current_reason")), (True, "superseded_by_retraction"))
        check_eq("R-208.4: kept in results[] with its raw status", (row.get("status"), row.get("raw_status")),
                 ("partial", "not_run"))
        check_not_in("R-208.4: and no longer current", OLD_X, str(current_ids(report)))
        check_eq("R-208.4: the totals no longer count it", report["current_totals"], {"passed": 1})
        finding = next(f for f in report["factory_findings"] if f.get("entity") == OLD_X)
        check_eq("R-208.4: the join finding carries what quenched it", finding.get("superseded_by"),
                 {"retracted_instance": OLD_X})
        import check_delivery as D
        write(task / "work" / "run-report.json", report)
        check_eq("R-208.4: and it is not printed to the person", D.factory_finding_reasons(task), [])
    # edge (ii): the list absent, not a list, empty, or only blank entries: no quench
    for label, retracted in (("absent", None), ("a string", OLD_X), ("an object", {OLD_X: True}), ("empty", []),
                             ("blank entries", ["", "   ", None, 7])):
        variant = dict(MANIFEST) if retracted is None else dict(MANIFEST, retracted_instances=retracted)
        with story(blocks(), variant) as (_t, report):
            check(f"edge (ii): retracted_instances {label}: the ghost is not quenched",
                  OLD_X in current_ids(report) and not kept_row(report, OLD_X).get("superseded"))
    with story(blocks(), dict(MANIFEST, retracted_instances=["", " " + OLD_X + " "])) as (_t, report):
        check("edge (ii): a blank entry beside a name is ignored, the name still counts",
              kept_row(report, OLD_X).get("current_reason") == "superseded_by_retraction")
    # edge (iii): a name retracted and live again is never quenched. Two manifest rows of one name make the
    # join fail while the name is live; an alias of a live instance is live as well.
    twice = {"tests": MANIFEST["tests"] + [dict(MANIFEST["tests"][0], instance_id=OLD_X, selector="test_old"),
                                           dict(MANIFEST["tests"][0], instance_id=OLD_X, selector="test_old")],
             "retracted_instances": [OLD_X]}
    with story(blocks(), twice) as (_t, report):
        row = kept_row(report, OLD_X)
        check_eq("edge (iii): a retracted name that is live again (here: a duplicate identity) stays a join failure",
                 row.get("current_reason"), F.JOIN_FAILED)
        check("edge (iii): current and visible", OLD_X in current_ids(report))
    alias = C.instance_id_aliases(MANIFEST["tests"][0])[1]
    check("edge (iii): the control - the manifest instance really answers to a second spelling",
          alias != "test_search[eu]", alias)
    with story([("b1", T1, [dict(REAL[0]), {"instance_id": alias, "status": "not_run"}])],
               dict(MANIFEST, retracted_instances=[alias])) as (_t, report):
        check("edge (iii): a retracted spelling that is an ALIAS of a live instance is live: not quenched",
              alias in current_ids(report) and not kept_row(report, alias).get("superseded"))
    # edge (iv): a red under a retracted name is never quenched
    for status in ("failed", "error"):
        with story(blocks(status), manifest) as (_t, report):
            row = kept_row(report, OLD_X)
            check(f"edge (iv): a `{status}` row under a retracted name is not quenched, and is current",
                  not row.get("superseded") and OLD_X in current_ids(report), str(row))


def an_unconfirmed_red_keeps_the_ghost_visible() -> None:
    """Edge (v): the cmp1 shape. The ghost row is `not_run` / "report row missing" in a block whose run
    FAILED: red by t-108's R5/R5a (one definition, imported from `run_history`) unless the block's own raw
    report names the function as not red. A check of the latest row's raw status alone quenches it."""
    row = {"instance_id": OLD_X, "test_id": MOD_ID + OLD_X, "status": "not_run", "reason": "report row missing",
           "case": "TC-009"}
    manifest = dict(MANIFEST, retracted_instances=[OLD_X])
    red_block = lambda status: ("b0", T1, [dict(row)], {"execution_status": status})  # noqa: E731
    later = ("b1", T2, REAL, {"execution_status": "passed"})
    with story([red_block("failed"), later], manifest) as (_t, report):
        ghost = kept_row(report, OLD_X)
        check("edge (v): an unconfirmed red, retracted name, later green of its case: still a current ghost",
              not ghost.get("superseded") and OLD_X in current_ids(report), str(ghost))
        check_eq("edge (v): it says what went wrong", ghost.get("current_reason"), F.JOIN_FAILED)
    coded = dict(row, reason="id not in report; nearest: a.spec.ts::x", reason_code="id_not_in_report")   # EP1-37 E-2: a file contract's missing row
    with story([("b0", T1, [coded], {"execution_status": "failed"}), later], manifest) as (_t, report):
        ghost = kept_row(report, OLD_X)
        check("E-2: a missing row of a file contract (reason_code, new text) in a failed block is an unconfirmed red too",
              not ghost.get("superseded") and OLD_X in current_ids(report), str(ghost))
    with story([red_block("passed"), later], manifest) as (_t, report):
        check_eq("edge (v) control: the same row in a block whose run did not fail is not a red: settled",
                 kept_row(report, OLD_X).get("superseded"), True)
    with story([red_block("failed"), later], manifest, prepare=raw_report("passed", "b0")) as (_t, report):
        check_eq("edge (v) control: a function the block's own raw report names as passed is not red: settled",
                 kept_row(report, OLD_X).get("superseded"), True)
    with story([red_block("failed"), later], manifest, prepare=raw_report("failed", "b0")) as (_t, report):
        check("edge (v): a function the raw report says failed is a confirmed red: visible",
              not kept_row(report, OLD_X).get("superseded") and OLD_X in current_ids(report))
    # the same red with the name NOT retracted: the later green of its case must not cover it either
    with story([red_block("failed"), later]) as (_t, report):
        check("R-208.5: an unanswered red is not covered by a later green of its case",
              not kept_row(report, OLD_X).get("superseded") and OLD_X in current_ids(report))


def a_paired_red_answers_the_ghost() -> None:
    """Edges (vi) and (vii): the function went red under its live instance and passed on changed code
    (an `expectation_changes` pair). A critic's verdict on the record, or a person's word, answers that
    red; a record with no verdict, no record and no `expectation_changes` key do not."""
    live = {"case": "TC-009", "covers": ["TC-009"], "file": "tests/test_m.py", "instance_id": "test_old[y]",
            "selector": "test_old", "test_function": "test_old"}
    row = lambda status, sha, attempt: {"case": "TC-009", "instance_id": "test_old[y]",  # noqa: E731
                                        "test_id": MOD_ID + "test_old[y]", "status": status,
                                        "instance_code_sha": sha, "attempt_id": attempt}
    ghost = {"instance_id": OLD_X, "test_id": MOD_ID + OLD_X, "status": "passed"}
    blocks = [("b0", T1, [ghost], {"attempt_id": "b0", "execution_status": "passed"}),
              ("b1", T2, [row("failed", "s1", "b1")], {"attempt_id": "b1", "execution_status": "failed"}),
              ("b2", T3, [row("passed", "s2", "b2")], {"attempt_id": "b2", "execution_status": "passed"})]
    record = {"function": "test_m.test_old", "red_attempt": "b1", "green_attempt": "b2",
              "then_refs": [{"case": "TC-009", "then": 1}], "what_changed": "the expected value",
              "reason": "the approved case allows it"}
    base = {"tests": [live], "retracted_instances": [OLD_X]}

    def outcome(manifest: dict, pipeline: dict = None) -> tuple:
        with story(blocks, manifest, pipeline) as (_t, report):
            return kept_row(report, OLD_X).get("current_reason"), OLD_X in current_ids(report)
    check_eq("edge (vii): `expectation_changes` absent: the red has no pair, the ghost stays visible",
             outcome(base), (F.JOIN_FAILED, True))
    check_eq("edge (vii): a record with no critic verdict does not answer it",
             outcome(dict(base, expectation_changes=[record])), (F.JOIN_FAILED, True))
    check_eq("fork 5a: `could_not_judge` judged nothing: it does not answer the red",
             outcome(dict(base, expectation_changes=[dict(record, critic_verdict="could_not_judge",
                                                          critic_note="cannot tell")])), (F.JOIN_FAILED, True))
    check_eq("fork 5a: `fitted_to_code` is a verdict that judged: it answers",
             outcome(dict(base, expectation_changes=[dict(record, critic_verdict="fitted_to_code")])),
             ("superseded_by_retraction", False))
    check_eq("edge (vi): a record with a critic's verdict answers the red: the retracted ghost is quenched",
             outcome(dict(base, expectation_changes=[dict(record, critic_verdict="legitimate_correction")])),
             ("superseded_by_retraction", False))
    import waiver as W
    pipeline = {"task": "T"}
    W.apply_stage_override(pipeline, "S5", "changed-after-red", "the person lets the test stand", W.now_iso())
    check_eq("edge (vi): a person's word on the pair answers it as well",
             outcome(base, pipeline), ("superseded_by_retraction", False))
    # the ghost may also be superseded by the later green of its case, once the red is answered
    cased = [("b0", T1, [dict(ghost, case="TC-009")], blocks[0][3])] + blocks[1:]
    answered = dict(base, retracted_instances=[], expectation_changes=[dict(record, critic_verdict="legitimate_correction")])
    with story(cased, answered) as (_t, report):
        check_eq("edge (vi): an answered red lets a later green of the case supersede the ghost",
                 kept_row(report, OLD_X).get("current_reason"), C.SUPERSEDED_BY_RERUN)
    with story(cased, dict(answered, expectation_changes=[])) as (_t, report):
        check_eq("edge (vii): with no pair the same later green leaves the ghost visible",
                 kept_row(report, OLD_X).get("current_reason"), F.JOIN_FAILED)


def the_blocks_are_read_on_the_one_clock() -> None:
    """Edge (viii): `_blocks` reads the run blocks through `run_history.read_run_blocks`. A reparse is named
    `<attempt>-reparse-<hash>.json` and has no stamp, so by file name alone it sorted BEFORE the `2026...`
    original it supersedes; on the clock it comes right after it."""
    row = dict(REAL[0], attempt_id="1abc")
    original = "20260930T045703820495Z-1abc"
    task = task_with([(original, T1, [row], {"attempt_id": "1abc"}),
                      ("1abc-reparse-h", T1, [row], {"attempt_id": "1abc", "reparse_of": original + ".json"}),
                      ("0zzz", T2, [row], {"attempt_id": "0zzz"})])
    try:
        order = [item["source"] for item in F._blocks(task)]
        check_eq("edge (viii): the clock order wins over the name order (reparse right after its original)",
                 order, ["run-blocks/" + original + ".json", "run-blocks/1abc-reparse-h.json", "run-blocks/0zzz.json"])
        check_eq("edge (viii): and the name order would have been another", sorted(order),
                 ["run-blocks/0zzz.json", "run-blocks/1abc-reparse-h.json", "run-blocks/" + original + ".json"])
        (task / "work" / "manual-blocks").mkdir(parents=True)
        write(task / "work" / "manual-blocks" / "m.json", {"block_id": "m", "attempt_started_at": T3,
                                                            "manual_checks": []})
        check_eq("a manual block is merged into the same order by its own clock",
                 [item["source"] for item in F._blocks(task)][-1], "manual-blocks/m.json")
        (task / "work" / "run-blocks" / "bad.json").write_text("{not json", encoding="utf-8")
        try:
            F.reduce(task)
            check("a corrupt run block still stops the reducer", False)
        except ValueError as exc:
            check_in("a corrupt run block still stops the reducer, naming the file", "bad.json", str(exc))
    finally:
        cleanup(task.parents[2])


def the_reducer_imports_only_public_names_of_run_history() -> None:
    """Fork 3: the red rule and the clock parser have public names; no underscore name of `run_history`
    is reached into from `finalize_task`."""
    import re
    source = (Path(__file__).resolve().parents[1] / "finalize_task.py").read_text(encoding="utf-8")
    check_eq("finalize_task reaches no underscore name of run_history", re.findall(r"\bRH\._\w+|from run_history import[^\n]*\b_\w+", source), [])
    import run_history as RH
    check("the public names exist", all(callable(getattr(RH, n, None)) for n in ("red_blocks", "parse_time", "same_function")))


def main() -> None:
    the_reducer_imports_only_public_names_of_run_history()
    ghost_superseded()
    order_decides()
    a_ghost_does_not_decide_the_run()
    a_superseded_ghost_is_not_a_delivery_reason()
    ambiguity_counts_only_kept_blocks()
    the_pair_decides_not_the_story()
    the_join_keeps_the_raw_result()
    the_cases_of_a_ghost_include_its_links()
    a_retracted_ghost_is_quenched()
    an_unconfirmed_red_keeps_the_ghost_visible()
    a_paired_red_answers_the_ghost()
    the_blocks_are_read_on_the_one_clock()
    finish("test_reducer_supersession")


if __name__ == "__main__":
    main()
