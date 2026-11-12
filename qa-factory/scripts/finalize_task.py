#!/usr/bin/env python3
"""Reduce task run blocks into durable, whole-story machine projections.

This command never launches tests or agents. Producers write immutable JSON blocks under
``work/run-blocks/`` or ``work/manual-blocks/``; this reducer keeps every distinct block
and writes the canonical ``run-report.json`` plus an empty triage when no failures exist.
Legacy flat/canonical run reports are read as one source block for migration.
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import run_history as RH  # noqa: E402
from event_store import EventStore, StateConflict, atomic_json  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
# The reducer's own word for a ghost row whose name the manifest retracted and no live instance
# wears (B-208, R-208.4). Local to this file: `C.SUPERSEDED_BY_RERUN` is the other one.
SUPERSEDED_BY_RETRACTION = "superseded_by_retraction"


def _load(path: Path) -> dict:
    return C.load_json(path)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _blocks(task: Path) -> list:
    """Every run and manual block of the task, oldest first, each `{"source", "data", "time",
    "started", "depth"}`.

    ONE clock for the story's run blocks (SIBLING_MAP axis 8): the run blocks are read by
    `run_history.read_run_blocks` — (time, reparse depth, file name), a reparse right after the
    block it supersedes — and not sorted here by file name and raw `attempt_started_at` text, which
    put a reparse (named `<attempt>-reparse-...`, no stamp) in a place the clock does not. `started`
    says whether a real `attempt_started_at` stands behind `time`; without one the block is
    unordered against every other block (R-208.1). Manual blocks, and run blocks in a sub-folder
    (the reader above looks at neither), are placed by their own `attempt_started_at` with the same
    parser and are merged into the same order."""
    work = C.artifact_write_path(task, "run-report.json").parent
    items, bad = RH.read_run_blocks(task)
    if bad:
        raise ValueError(f"corrupt run block {work / 'run-blocks' / bad[0]}: JSON object required")
    found = [{"source": "run-blocks/" + item["name"], "data": item["data"], "time": item["time"],
              "started": item["started"], "depth": item["depth"]} for item in items]
    for folder in ("run-blocks", "manual-blocks"):
        directory = work / folder
        if directory.exists():
            for path in sorted_paths(directory.rglob("*.json")):
                if folder == "run-blocks" and path.parent == directory:
                    continue  # the reader above has it
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    raise ValueError(f"corrupt run block {path}: {exc}") from exc
                if not isinstance(data, dict):
                    raise ValueError(f"corrupt run block {path}: JSON object required")
                own = RH.parse_time(data.get("attempt_started_at"))
                found.append({"source": str(path.relative_to(work)).replace("\\", "/"), "data": data,
                              "time": own or _EPOCH, "started": own is not None, "depth": 0})
    return sorted(found, key=lambda item: (item["time"], item["depth"], item["source"]))


def _migrate_legacy(task: Path) -> None:
    """Capture an old report once as immutable input before replacing its projection."""
    work = C.artifact_write_path(task, "run-report.json").parent
    canonical = work / "run-report.json"
    legacy = canonical if canonical.exists() else task / "run-report.json"
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"corrupt legacy run report {legacy}: {exc}") from exc
    if not isinstance(data, dict) or data.get("reducer"):
        return
    target = work / "run-blocks" / ("legacy-" + _digest(data)[:16] + ".json")
    if not target.exists():
        atomic_json(target, data)
    # Once copied, remove the conflicting read alias from the task root without losing
    # evidence. Future resolver reads see only the canonical projection.
    if legacy != canonical:
        archive = task / "state" / "migration" / ("run-report-legacy-" + _digest(data)[:16] + ".json")
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            shutil.move(str(legacy), str(archive))


def _env_block_identity(row: dict, instance_cases: dict, cfg: dict | None = None) -> tuple[set, set]:
    """What one `env_blocked` row names: instance ids and case ids.

    A row that names neither cannot be matched to any later result, so it keeps blocking —
    which is the old behaviour, and the right one: "the stand was down" with nothing to
    bind it to is not something a green elsewhere may quietly cancel."""
    instances = {str(row.get(key)) for key in ("instance_id", "test_instance_id") if row.get(key)}
    cases = set(C.case_ids(row.get("case"), cfg=cfg))
    if not cases and row.get("case"):
        cases = {str(row.get("case"))}
    for instance, linked in instance_cases.items():
        if cases & linked:
            instances.add(instance)
    return instances, cases


def _pair_rule(pair_ambiguous):
    """The per-pair order check both supersessions use: `(position of one block, position of the
    other) -> True when their order cannot be told`. `reduce` passes the real one; a bare bool is the
    old global flag's meaning (True: every pair is ambiguous), kept so an older caller still runs."""
    return pair_ambiguous if callable(pair_ambiguous) else (lambda _left, _right: bool(pair_ambiguous))


def _project_env_blocks(blocked: list, current_instances: dict, positions: dict,
                        instance_cases: dict, pair_ambiguous=False) -> list:
    """Mark each environment block a later terminal attempt of the same instance answered.

    Ordering is by attempt, not by the order the block files were read, and a PAIR whose order
    cannot be told (the block of the outage and the block of the later result: one has no
    `attempt_started_at`, or both start together) supersedes nothing: cancelling a recorded
    outage on a guess is exactly the false green this factory exists to refuse. It is the pair
    that decides, not the whole story: an unrelated ambiguous pair elsewhere no longer keeps a
    resolved outage standing (B-208)."""
    projected = []
    unordered = _pair_rule(pair_ambiguous)
    cfg = C.case_config()  # once, not once per (block, result): B-013 performance
    for row in blocked:
        superseding = {}
        instances, cases = _env_block_identity(row, instance_cases, cfg)
        here = int(row.get("attempt_position") or 0)
        for instance, result in current_instances.items():
            if C.result_status(result) not in C.TERMINAL_RESULT_STATUSES:
                continue
            if positions.get(instance, -1) <= here:
                continue
            if unordered(here, positions.get(instance, -1)):
                continue
            if instance in instances or (cases & (set(C.case_ids(result.get("case"), cfg=cfg))
                                                  | instance_cases.get(instance, set()))):
                superseding = {"instance_id": instance,
                               "attempt_id": str(result.get("attempt_id") or ""),
                               "status": C.result_status(result)}
                break
        projected.append(dict(row, superseded=True, superseded_by=superseding) if superseding else row)
    return projected


JOIN_FAILED = "instance_manifest_join_failed"


def _ghost_cases(row: dict, instance_cases: dict, cfg: dict | None = None) -> set:
    """Which cases an unjoined result row is about.

    Its own `case` cell, the cases of its instance when the manifest knows it, and the case
    ids spelled inside its identity — the first run block of TP2-2553 put `TC-009` in
    `instance_id`, and a case id used as an instance id is still a case id."""
    identity = str(row.get("instance_id") or row.get("test_instance_id") or "")
    # `case_version_links` too (R-208.5): the ghosts of cmp1 carry the cases they prove there and
    # have no `case` cell, so the case-level rule found no case and superseded nothing.
    return (set(C.case_ids(row.get("case"), cfg=cfg)) | set(C.case_ids(identity, cfg=cfg))
            | set(C.manifest_test_links(row, cfg)) | instance_cases.get(identity, set()))


def _supersede_join_ghosts(current: dict, positions: dict, instance_cases: dict,
                           pair_ambiguous=False, red_held=None) -> dict:
    """{ghost key: what superseded it} — a later terminal joined attempt of the same case.

    A row the reducer could not join to exactly one manifest instance stays `partial` under
    its own key forever, and supersession existed only for `env_blocked` rows. On
    TP2-2553 the first block was written under case-shaped instance ids, the corrected
    rerun under the real ones superseded nothing, and four ghosts made `execution_status`
    `not_executed` over twelve green results. Ordering is by attempt position, never by file
    order, and a PAIR whose order cannot be told supersedes nothing — the same rule
    `_project_env_blocks` follows, and for the same reason; one ambiguous pair elsewhere in the
    story does not switch the others off (B-208, R-208.2).

    `red_held(key, ghost)` is True for a ghost whose history holds a red nobody answered: the
    join overwrote its status with `partial`, so a green of ANOTHER instance must not cover a red
    it never met (R-208.5). Such a ghost stays current and visible."""
    out = {}
    unordered = _pair_rule(pair_ambiguous)
    cfg = C.case_config()  # once, not once per (ghost, result): B-013 performance
    for key, ghost in current.items():
        if str(ghost.get("current_reason") or "") != JOIN_FAILED:
            continue
        cases = _ghost_cases(ghost, instance_cases, cfg)
        if not cases:
            continue
        if red_held is not None and red_held(key, ghost):
            continue
        for instance, result in current.items():
            if instance == key or str(result.get("current_reason") or "") == JOIN_FAILED:
                continue
            if C.result_status(result) not in C.TERMINAL_RESULT_STATUSES:
                continue
            if positions.get(instance, -1) <= positions.get(key, -1):
                continue
            if unordered(positions.get(key, -1), positions.get(instance, -1)):
                continue
            if cases & (set(C.case_ids(result.get("case"), cfg=cfg)) | instance_cases.get(instance, set())):
                out[key] = {"instance_id": instance,
                            "attempt_id": str(result.get("attempt_id") or ""),
                            "status": C.result_status(result)}
                break
    return out


# A verdict that did NOT judge: the critic could not tell, and the conductor records the window as
# unresolved (`handoffs/vocabulary.yaml` `expectation_change_verdicts`). It answers no red.
UNJUDGED_VERDICTS = ("could_not_judge",)


class _RedHistory:
    """Does a ghost's history hold a red nobody answered? (B-208, R-208.4/.5.)

    ONE definition of red: t-108's R5/R5a, `run_history._classify` (`failed`/`error`, and an
    unmapped `not_run` row of a failed block — `red_unconfirmed` — unless the block's own raw
    report names the function as not red), read over every block of the story through the ONE
    block reader, never over the latest row alone: on cmp1 all 13 ghosts carry a `not_run` "report
    row missing" in the failed block `5a24a4a3`, an unconfirmed red a latest-row check cannot see.
    A red is ANSWERED when an `expectation_changes` pair spans its block and the pair has a
    critic's verdict that JUDGED on its record (`could_not_judge` judged nothing) or a person's word
    (`passed_by_word`); an unpaired red (no green
    after it, or a green on the same bytes) answers nothing. Every doubt errs toward "held": a
    measurement that cannot be made keeps the ghost visible (FR-41), and reading is lazy, so a
    story with no ghost candidate pays nothing. Writes nothing (FR-45)."""

    def __init__(self, task: Path, manifest: dict):
        self.task, self.manifest = Path(task), manifest if isinstance(manifest, dict) else {}
        self._loaded = False
        self._reds: dict = {}
        self.items: list = []
        self.index: dict = {}
        self.pairs: list = []
        self.reports: dict = {}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        import s5_precheck as S5  # lazy: s5_precheck is the detector's home, the reducer needs it only for a ghost
        self.items, _bad = RH.read_run_blocks(self.task)
        self.index = {item["name"]: position for position, item in enumerate(self.items)}
        cases = S5.scope_cases(self.task, self.manifest, None)
        changes = S5.expectation_changes(self.task, cases, self.manifest)
        S5.word_passed_pairs(self.task, changes, cases)  # marks `passed_by_word` on each pair, in place
        self.pairs = [pair for pair in changes.get("pairs") or [] if isinstance(pair, dict)]

    def _red_blocks(self, key: str) -> list:
        """Positions (in the block order) of the blocks whose rows of this function hold a red."""
        if key not in self._reds:
            self._reds[key] = RH.red_blocks(self.task, key, self.items, self.reports)
        return self._reds[key]

    def _answers(self, key: str, position: int) -> bool:
        for pair in self.pairs:
            record = pair.get("record")
            verdict = str(record.get("critic_verdict") or "").strip() if isinstance(record, dict) else ""
            judged = bool(verdict) and verdict not in UNJUDGED_VERDICTS
            if not (judged or pair.get("passed_by_word")) or not RH.same_function(str(pair.get("function") or ""), key):
                continue
            start = self.index.get(str(pair.get("red_block") or ""))
            green = pair.get("green_block")
            end = self.index.get(str(green)) if green else len(self.items) - 1
            if start is not None and end is not None and start <= position <= end:
                return True
        return False

    def held(self, row: dict) -> bool:
        """True when the function this row belongs to has a red in the story's history that no
        paired record or word answers."""
        try:
            self._load()
            key = RH.function_key(row.get("test_id"), row.get("instance_id") or row.get("test_instance_id"))
            if not key:
                return True
            return any(not self._answers(key, position) for position in self._red_blocks(key))
        except Exception:
            return True


def _retracted_names(manifest: dict) -> set:
    """The non-blank names of `manifest.retracted_instances`; empty when the key is absent or is
    not a list, and a blank or non-string entry is ignored (R-208.4). The list is cumulative
    history (`manifest_put.py` only ever appends), so a name in it may be live again."""
    raw = manifest.get("retracted_instances") if isinstance(manifest, dict) else None
    if not isinstance(raw, list):
        return set()
    return {name for name in (entry.strip() for entry in raw if isinstance(entry, str)) if name}


def _quench_by_retraction(current: dict, manifest: dict, manifest_rows: list, red_held) -> dict:
    """{ghost key: what quenched it} — a current join-failed row whose name the manifest retracted.

    All of: the name is in `retracted_instances`; no live manifest instance wears it (as its id
    or as any alias — 8 of cmp1's 21 retracted names are live again); and the ghost holds no red
    (`red_held`: the row's own raw status, any row of the identity, and the function's history).
    A live row and a red row are never hidden by history."""
    retracted = _retracted_names(manifest)
    if not retracted:
        return {}
    cfg = C.case_config()
    live = {alias for test in manifest_rows for alias in C.instance_id_aliases(test, cfg)}
    out = {}
    for key, ghost in current.items():
        if str(ghost.get("current_reason") or "") != JOIN_FAILED:
            continue
        if key in retracted and key not in live and not red_held(key, ghost):
            out[key] = {"retracted_instance": key}
    return out


def _row_key(row: dict) -> str:
    """The key `C.instance_results` files a row under."""
    return str(row.get("instance_id") or row.get("test_instance_id") or "").strip() or C.test_instance_id(row)


def _fresh(row: dict) -> dict:
    """The row as a producer wrote it: a supersession mark left on it by an older reducer run is
    dropped, because what is superseded is recomputed from the whole history every time and never
    trusted as stored (B-208)."""
    if not (row.get("superseded") or row.get("superseded_by")
            or row.get("current_reason") in (C.SUPERSEDED_BY_RERUN, SUPERSEDED_BY_RETRACTION)):
        return row
    kept = {k: v for k, v in row.items() if k not in ("superseded", "superseded_by")}
    if kept.get("current_reason") in (C.SUPERSEDED_BY_RERUN, SUPERSEDED_BY_RETRACTION):
        del kept["current_reason"]
    return kept


def reduce(task: Path) -> tuple[dict, dict]:
    task = Path(task)
    sources, seen = [], set()
    results, manual, impossible, blocked = [], [], [], []
    statuses, evidence = [], []
    found = _blocks(task)
    blocks = [(item["source"], item["data"]) for item in found]
    by_block_id = {str(block.get("block_id") or block.get("id") or ""): block for _, block in blocks}
    superseded = set()
    for _, replacement in blocks:
        old_id = str(replacement.get("supersedes_block_id") or "")
        old = by_block_id.get(old_id)
        same_attempt = old and replacement.get("attempt_id") == old.get("attempt_id")
        same_inputs = old and replacement.get("input_fingerprint") == old.get("input_fingerprint") \
            and replacement.get("source_fingerprint") == old.get("source_fingerprint")
        replacement_raw = (replacement.get("reporter_mapping") or {}).get("raw_report_hash")
        same_raw = bool(old and replacement_raw and replacement_raw ==
                        (old.get("reporter_mapping") or {}).get("raw_report_hash"))
        if old_id and replacement.get("reparse_of") and same_attempt and same_inputs and same_raw:
            superseded.add(old_id)
    invalidated = {}
    # A corrupt lifecycle journal cannot be interpreted as fresh execution evidence.
    for event in EventStore(task).read():
        if event.get("type") == "invalidate":
            payload = event.get("payload", {})
            for dispatch in payload.get("dispatch_ids") or []:
                invalidated.setdefault(str(dispatch), set()).update(map(str, payload.get("affected_scope") or []))
    manifest = C.load_json(C.artifact(task, "automation-manifest.json"))
    manifest_rows = C.manifest_tests(manifest)
    # RN1-21 (N1-3): a manifest row answers to EVERY spelling of its instance (`C.instance_id_aliases`: the 0.7.7 `case::test`, the
    # bare form, the 0.7.4 hash), the one reader of them (AR-13). A block row joins when exactly ONE distinct row answers to its id;
    # two distinct rows are `duplicate manifest identity` and none `no manifest row`: the error goes to the finding, never to a
    # join of two different tests.
    manifest_instances = {}
    case_cfg = C.case_config(task)
    for test in manifest_rows:
        for alias in C.instance_id_aliases(test, case_cfg) or [C.test_instance_id(test)]:
            manifest_instances.setdefault(alias, []).append(test)
    instance_cases = {iid: set(C.manifest_test_links(rows[0]))
                      for iid, rows in manifest_instances.items() if len(rows) == 1}
    factory_findings = []
    def stale_row(block, row):
        dispatch = str(block.get("dispatch_id") or row.get("dispatch_id") or "")
        if dispatch not in invalidated:
            return False
        identities = {str(row.get(k)) for k in ("instance_id", "test_instance_id", "case", "check", "test_id") if row.get(k)}
        identity = str(row.get("instance_id") or row.get("test_instance_id") or "")
        mapped = instance_cases.get(identity, set())
        identities.update(mapped)
        scope = invalidated[dispatch]
        # Missing identity mapping is uncertainty, never proof that a changed case is safe.
        return bool(identities & scope) or not scope or not (mapped or row.get("case") or row.get("check"))
    # The start of each block on the ONE clock (`_blocks`), None when no `attempt_started_at` stands
    # behind it: such a block is unordered against every other block.
    block_starts = {item["source"]: (item["time"] if item["started"] else None) for item in found}
    # Position in the attempt-ordered block list, so "which came first" is answered by the
    # attempt and not by the order the files happened to be read.
    block_index = {source: index for index, (source, _) in enumerate(blocks)}
    start_at = [block_starts[source] for source, _ in blocks]
    def order_ambiguous(rows, sources):
        # Concurrent blocks with equal starts are valid when their instance sets are
        # disjoint.  This function is called for one identity, so multiple origins here
        # are necessarily overlapping attempts and still require a strict order.
        origins = set(sources.get(id(row)) for row in rows if not row.get("stale"))
        times = [block_starts.get(origin) for origin in origins]
        if len(origins) < 2:
            return False
        if any(value is None for value in times):
            return True
        # A tie matters only among the LATEST attempts of the identity: two older blocks that start
        # together are answered by a later block with a distinct start (R-208.7: run it again).
        return times.count(max(times)) > 1
    def pair_ambiguous(left, right):
        """Can the order of the blocks at these two positions NOT be told: one of them has no
        start, or they start together. The rule of `order_ambiguous`, asked of one pair of blocks
        (R-208.2): an unknown position is unknown, so the pair is ambiguous."""
        if left < 0 or right < 0:
            return True
        if left == right:
            return False
        return start_at[left] is None or start_at[right] is None or start_at[left] == start_at[right]
    block_keys = [str(block.get("block_id") or block.get("id") or _digest(block)) for _, block in blocks]
    # The story's global flag is about the blocks that are KEPT: an original that an accepted
    # reparse supersedes carries the reparse's start and its instance ids, and counted as a second
    # attempt it made every reparsed story read `ambiguous` (cmp1, R-208.1). It is the report
    # field `attempt_order` only; no supersession reads it (they decide per pair). It reads
    # `ambiguous` when a kept block has no start, or some identity has a live tie (set below).
    kept = [position for position in range(len(blocks)) if block_keys[position] not in superseded]
    kept_without_start = len(kept) > 1 and any(start_at[position] is None for position in kept)
    result_sources, manual_sources, manual_invalidated = {}, {}, {}
    for position, (source, block) in enumerate(blocks):
        key = block_keys[position]
        if key in superseded:
            continue
        if key in seen:
            continue
        seen.add(key)
        sources.append({"id": key, "source": source})
        # PC-5a (B2): the block's proof stamp rides on every row reduced from it - a projection of the block, not a second record
        # (AR-14, AR-21). A block with none adds nothing; `sides_unknown` is carried as it stands, never turned into a reality.
        stamp = {k: block[k] for k in ("sides_met", "sides_unknown") if k in block}
        import_errors = []
        if block.get("import_provenance"):
            from import_test_receipt import validate_import_block
            import_errors = validate_import_block(task, block)
        evidence_errors = []
        if block.get("reporter_mapping"):
            refs = [ref for ref in block.get("evidence") or [] if isinstance(ref, dict)]
            for ref in refs:
                if ref.get("reporter") == "none":
                    continue
                raw = str(ref.get("report_path") or "")
                path = (task / raw).resolve() if raw and not Path(raw).is_absolute() else Path()
                if (not raw or not path.is_relative_to(task.resolve()) or not path.is_file() or
                        hashlib.sha256(path.read_bytes()).hexdigest() != ref.get("report_sha256")):
                    evidence_errors.append("reporter evidence missing, unsafe or hash-mismatched")
        for row in block.get("results") or []:
            if isinstance(row, dict):
                row = _fresh(row)
                retained = dict(row, stale=True, current_reason="invalidated_dispatch") if stale_row(block, row) else row
                # FB-43: a row inherits its block's `purpose` unless it carries its own (a diagnostic row
                # inside an `initial` block stays a diagnostic), so `C.product_result_rows` can tell a
                # diagnostic preflight from a product run after the blocks are merged; and only a
                # DIAGNOSTIC row stays out of the manifest join - it names no manifest instance and used
                # to come out of here as a join-failed ghost. Every other row (a red-probe, a baseline)
                # is joined exactly as before; the two purposes are `C.product_result_rows`' own.
                if block.get("purpose") and not retained.get("purpose"):
                    retained = dict(retained, purpose=block["purpose"])
                identity = str(retained.get("instance_id") or retained.get("test_instance_id") or "")
                if manifest_rows and str(retained.get("purpose") or "").lower() not in {"diagnostic", "flaky_diagnostic"}:
                    matches = manifest_instances.get(identity, [])
                    if len(matches) != 1:
                        # `raw_status` is what the run said before this overwrite: the ghost's own
                        # result survived only in the block file, and a reader (the quench below,
                        # the owner of a reason) must see whether it was red (R-208.3).
                        retained = dict(retained, raw_status=C.result_status(retained), status="partial",
                                        current_reason=JOIN_FAILED)
                        factory_findings.append({"code": "INSTANCE_MANIFEST_JOIN_FAILED",
                                                 "entity": identity or "missing-instance-id",
                                                 "attempt_id": retained.get("attempt_id"),
                                                 "detail": "no manifest row" if not matches else "duplicate manifest identity"})
                    else:
                        manifest_row = matches[0]
                        retained = dict(retained,
                            parameters=C.canonical_parameters(manifest_row.get("parameters") or
                                                              manifest_row.get("parameter_map")),
                            case_version_links=manifest_row.get("case_version_links") or [],
                            obligation_ids=manifest_row.get("obligation_ids") or retained.get("obligation_ids") or [])
                if import_errors:
                    retained = dict(retained, status="not_run", current_reason="invalid_external_evidence", evidence_errors=import_errors)
                if evidence_errors:
                    if C.result_status(retained) in {"failed", "error"}:
                        retained = dict(retained, verification_status="unverified",
                                        verification_reason="invalid_reporter_evidence",
                                        evidence_errors=evidence_errors)
                    else:
                        retained = dict(retained, status="not_run", current_reason="invalid_reporter_evidence",
                                        evidence_errors=evidence_errors)
                if stamp:
                    retained = dict(retained, **stamp)
                results.append(retained)
                result_sources[id(retained)] = source
        for row in block.get("manual_checks") or []:
            if isinstance(row, dict):
                if row.get("schema_version") == 2:
                    retained = row
                    dispatch_scope = invalidated.get(str(block.get("dispatch_id") or ""), set())
                    obligation_ids = set(row.get("obligation_ids") or [row.get("obligation_id")])
                    affected = (set(obligation_ids) if str(row.get("case") or "") in dispatch_scope or not dispatch_scope
                                else obligation_ids & dispatch_scope) if str(block.get("dispatch_id") or "") in invalidated else set()
                else:
                    retained = dict(row, stale=True, current_reason="invalidated_dispatch") if stale_row(block, row) else row
                    affected = set()
                if stamp:
                    retained = dict(retained, **stamp)
                manual.append(retained)
                manual_sources[id(retained)] = source
                manual_invalidated[id(retained)] = affected
        impossible.extend(row for row in block.get("impossible") or [] if isinstance(row, dict))
        for row in block.get("env_blocked") or []:
            if isinstance(row, dict):
                blocked.append(dict(row, attempt_position=block_index.get(source, 0)))
        statuses.append(str(block.get("execution_status") or ""))
        evidence.extend(row for row in block.get("evidence") or [] if isinstance(row, dict))

    # Preserve every attempt. The consumer's instance reducer decides the current rollup;
    # deduplicating by result/case here would recreate last-write-wins data loss.
    product_rows = C.product_result_rows({"results": results})
    # A repaired run supersedes only the current projection for the same instance. The
    # earlier failure is still retained in results[] for diagnosis and flaky analysis.
    current_instances, current_instance_position = {}, {}
    live_tie = False
    for key, rows in C.instance_results({"results": product_rows}).items():
        latest = rows[-1]
        current_instance_position[key] = block_index.get(result_sources.get(id(latest), ""), -1)
        if latest.get("stale"):
            latest = dict(latest, status="not_run", current_reason="invalidated_evidence")
        elif order_ambiguous(rows, result_sources):
            live_tie = True
            latest = dict(latest, status="partial", current_reason="ambiguous_attempt_order")
        current_instances[key] = latest
    ambiguous_order = kept_without_start or live_tie
    manual_groups = {}
    for row in manual:
        if row.get("schema_version") == 2 or row.get("unprepared") is not None:      # F5: an unprepared walk is always per-obligation
            for oid in row.get("obligation_ids") or [row.get("obligation_id")]:
                key = str(row.get("case")) + "::" + str(oid)
                manual_groups.setdefault(key, []).append(row)
        else:
            key = str(row.get("instance_id") or row.get("case") or row.get("check") or _digest(row))
            manual_groups.setdefault(key, []).append(row)
    current_manual = {}
    for key, rows in manual_groups.items():
        latest = rows[-1]
        is_v2 = latest.get("schema_version") == 2 or latest.get("unprepared") is not None
        obligation_id = key.split("::", 1)[1] if is_v2 else None
        obligation_stale = bool(obligation_id and obligation_id in manual_invalidated.get(id(latest), set()))
        walk = latest.get("unprepared") is not None        # F5(e) 1: an unprepared walk never gains a `result` word (FR-59)
        if latest.get("stale") or obligation_stale or order_ambiguous(rows, manual_sources):
            latest = dict(latest, current_reason="invalidated_evidence" if latest.get("stale") else "ambiguous_attempt_order")
            if not walk:
                latest["result"] = "inconclusive"
            if obligation_stale:
                latest["current_reason"] = "invalidated_evidence"
        if is_v2:
            latest = dict(latest, current_obligation_ids=[obligation_id])
            from coverage_contract import unprepared_only, validate_manual_current
            issues = validate_manual_current(task, latest)
            if walk and unprepared_only(issues):
                # carried under its own name: not validated as evidence, no result, the marker kept for the four readers
                latest = dict(latest, evidence_validated=False, unprepared=latest["unprepared"])
            elif issues:
                latest = dict(latest, result="inconclusive", evidence_validated=False, evidence_errors=issues)
            else:
                latest = dict(latest, evidence_validated=True)
        current_manual[key] = latest
    blocked = _project_env_blocks(blocked, current_instances, current_instance_position,
                                  instance_cases, pair_ambiguous)
    current_blocked = [row for row in blocked if not row.get("superseded")]
    # A ghost is answered only when its history holds no red, or the red is paired and answered
    # (`_RedHistory`). The rows' own `raw_status` is checked over EVERY row of the identity, not
    # the latest alone: the latest of a ghost can be a green while an earlier row of it was red.
    history = _RedHistory(task, manifest)
    raw_red = {_row_key(row) for row in results
               if str(row.get("current_reason") or "") == JOIN_FAILED and row.get("raw_status") in RH.RED_STATUSES}
    def red_held(key, ghost):
        return key in raw_red or history.held(ghost)
    ghosts = _supersede_join_ghosts(current_instances, current_instance_position,
                                    instance_cases, pair_ambiguous, red_held)
    quenched = _quench_by_retraction({k: v for k, v in current_instances.items() if k not in ghosts},
                                     manifest, manifest_rows, red_held)
    # What settled each ghost: a later green of its case (`superseded_by_rerun`), or the manifest's
    # retraction of its name (`superseded_by_retraction`).
    settled = {key: (C.SUPERSEDED_BY_RERUN, by) for key, by in ghosts.items()}
    settled.update({key: (SUPERSEDED_BY_RETRACTION, by) for key, by in quenched.items()})
    for key in settled:
        current_instances.pop(key, None)
    if settled:
        # The row keeps its place in `results[]` — with what answered it, so the diagnosis of
        # the join failure is still readable — and stops being current.
        for index, row in enumerate(results):
            identity = str(row.get("instance_id") or row.get("test_instance_id") or "")
            if str(row.get("current_reason") or "") == JOIN_FAILED and identity in settled:
                reason, by = settled[identity]
                results[index] = dict(row, superseded=True, superseded_by=by, current_reason=reason)
        for finding in factory_findings:
            answered = settled.get(str(finding.get("entity") or ""))
            if answered:
                finding["superseded_by"] = answered[1]
    # R-208.7: an order the reducer cannot tell names its way out, where the person reads it: run the
    # instance again. A later kept block with a distinct start ends the tie (`order_ambiguous` looks
    # only at the latest attempts), so the exit is real (FR-40).
    for key, row in current_instances.items():
        if str(row.get("current_reason") or "") == "ambiguous_attempt_order":
            cases = sorted(_ghost_cases(row, instance_cases))
            factory_findings.append({
                "code": "AMBIGUOUS_ATTEMPT_ORDER", "entity": key, "attempt_id": row.get("attempt_id"),
                "detail": "two attempts of this instance have no order the reducer can trust (a run block "
                          "without `attempt_started_at`, or two that start together), so it counts as "
                          "partial; run the instance again: `run_suite.py --mine "
                          + (cases[0] if cases else "<case>") + "` - a later block with a distinct start "
                          "settles the order"})
    current_statuses = [C.result_status(row) for row in current_instances.values()]
    current_statuses += [C.result_status({"status": row.get("result")}) for row in current_manual.values()]
    raw_statuses = [C.result_status(row) for row in product_rows]
    # A ghost the rerun did not answer stays visible in `current_results` — the ledger and
    # gate B show it as the factory's own — but it does not decide the RUN's status: twelve
    # green results and one row our reducer could not join is a run that passed, not a run
    # that never happened (TP2-2553). With nothing joined at all there is still
    # nothing to stand on, and that is `not_executed`.
    deciding = [C.result_status(row) for row in current_instances.values()
                if str(row.get("current_reason") or "") != JOIN_FAILED]
    deciding += [C.result_status({"status": row.get("result")}) for row in current_manual.values()]
    if any(status in ("failed", "error") for status in deciding):
        execution = "failed"
    elif deciding and all(status in ("passed", "pass") for status in deciding):
        execution = "passed"
    else:
        execution = "not_executed"
    revision = None
    try:
        revision = len(EventStore(task).read())
    except StateConflict:
        # Legacy or currently recovering event logs remain readable through artifacts;
        # surface the missing revision rather than inventing a current one.
        revision = None
    from controller import Controller
    source_revision = Controller(task).state().get("source_revision")
    report = {
        "schema_version": 2,
        "task_id": task.name,
        "source_revision": source_revision,
        "head": source_revision or "unknown",
        "controller_revision": revision,
        "reducer": {"name": "finalize_task", "sources": sources},
        "execution_status": execution,
        "results": results,
        "current_results": list(current_instances.values()),
        "manual_checks": manual,
        "current_manual_checks": list(current_manual.values()),
        "impossible": impossible,
        # Every environment block ever recorded, superseded ones marked and never removed;
        # `current_env_blocked` is the subset that still decides anything.
        "env_blocked": blocked,
        "current_env_blocked": current_blocked,
        "evidence": evidence,
        # Assembled from the blocks, never invented. validate_artifacts requires both keys on
        # run-report.json and check_witness judges them, but nothing produced them: the output
        # contract was unreachable by the normal path, and on TP2-2520 the only ways
        # left were to hand-edit an artifact or to accept a red validator. A reducer that can
        # read the blocks can also state what they show.
        # Until 0.7.5 this read `blocked` from EVERY historical row, so one bad morning on
        # the stand made the story's preflight blocked for good and no later green could
        # clear it (0.6.0 feedback on TP2-2530, item 2).
        "env_preflight": "blocked" if current_blocked else "pass",
        "totals": {status: raw_statuses.count(status) for status in sorted(set(raw_statuses))},
        "current_totals": {status: current_statuses.count(status) for status in sorted(set(current_statuses))},
        "attempt_order": "ambiguous" if ambiguous_order else "ordered_by_attempt_started_at",
        "factory_findings": factory_findings,
    }
    witness = _witness(evidence, execution, report["totals"])
    if witness:
        report["witness"] = witness
    # The same definition of "a failure that needs triage" as the driver and the S7 handover check (t-309).
    targets = C.triage_targets(report)
    triage = {"schema_version": 2, "task_id": task.name, "triage": [],
              "reducer": {"name": "finalize_task", "sources": sources}}
    # an observation (P26) is work for the analyst whatever the checks' results: "no product failures" is not said over one
    if not (targets["results"] or targets["manual"] or targets["unnamed"] or targets["observations"]):
        triage["reason"] = "no product failures in reduced run blocks"
        triage["evidence_refs"] = [item["source"] for item in sources]
    return report, triage


def _witness(evidence: list, execution: str, totals: dict) -> str:
    """The run_suite summaries the blocks actually name, with what they add up to.

    Deliberately absent when no block names a summary: an empty run has no witness, and a
    sentence saying so would pass the length check while being exactly the false green this
    factory exists to refuse. A missing key fails validation loudly, which is the truth."""
    summaries = [str(row.get("summary") or "") for row in evidence if isinstance(row, dict)]
    summaries = [s for s in dict.fromkeys(summaries) if s]
    if not summaries:
        return ""
    counted = ", ".join(f"{name}={count}" for name, count in sorted(totals.items())) or "no results"
    return (f"run_suite summaries: {'; '.join(summaries)} | execution_status={execution} | "
            f"totals: {counted}")


def refresh(task: Path) -> dict:
    """Code-only snapshot entry point for controller/stage_done integrations."""
    task = Path(task)
    try:
        _migrate_legacy(task)
        report, triage = reduce(task)
    except Exception as exc:
        atomic_json(C.artifact_write_path(task, "finalization-receipt.json"),
                    {"task": task.name, "status": "incomplete", "error": str(exc)})
        raise
    triage_path = C.artifact_write_path(task, "triage.json")
    existing_triage = C.load_json(triage_path)
    # t-309: ONE definition of a failure that needs triage (`contract.triage_targets`) and of the spellings a
    # row may carry (`contract.id_spellings`). Before it, the analyst's five ENV rows of cmp2r (ids with `[chromium]`,
    # three of them manual `inconclusive`) were archived here as "not bound to current failure" and S7 refused.
    # t-319 (critic t-312 F3): a row is kept when it answers ONE failure by `contract.same_id` - the matching rule
    # of the S7 check and of gate B - not when the union of every spelling meets the union of every failure's: that
    # kept a stale `x[multi]` for the failure `x[json]`, and `s7_repairs` then repaired a test that passes.
    targets = C.triage_targets(report)
    has_failure = bool(targets["results"] or targets["manual"] or targets["unnamed"] or targets["observations"])
    if has_failure and isinstance(existing_triage.get("triage"), list) and existing_triage["triage"]:
        # t-323 A1: kept = what `contract.bind_triage` binds to a failure, plus the rows it calls ambiguous (a row
        # that names two failures is the analyst's to fix, so S7 refuses it BY NAME; archived, it would read as "no
        # row" and the person's work would vanish from the form). A row of another attempt than the failure's, or
        # one that names no failure of this run, is stale.
        failures, _unnamed = C.triage_failures(report)
        bound = C.bind_triage(failures, existing_triage["triage"])
        keep = {id(row) for rows in bound["matched"].values() for row in rows} | {id(row) for row in bound["ambiguous_rows"]}
        # the row of an observation (`<case>#obs<n>`) is kept by this same binding: `matched` holds the rows of the observation's
        # own attempt, and a stale row of another attempt (or of a target the runner dropped) is archived (t-1747 F5, AR-13)
        kept = [row for row in existing_triage["triage"] if id(row) in keep]
        stale = [row for row in existing_triage["triage"] if id(row) not in keep]
        if stale:
            archive = task / "state" / "migration" / ("stale-triage-" + _digest({"rows": stale})[:16] + ".json")
            atomic_json(archive, {"rows": stale, "reason": "not bound to current failure"})
        triage["triage"] = kept
        # t-305 N1 (C5): the flag says an ANALYST row was kept; the rows `s7_pretriage` wrote (`source: code`) are code's
        # own and are kept or archived by the same binding, but they are not the analyst's work
        triage["analyst_preserved"] = any(row.get("source") != "code" for row in kept)
    elif not has_failure and isinstance(existing_triage.get("triage"), list) and existing_triage["triage"]:
        archive = task / "state" / "migration" / ("stale-triage-" + _digest({"rows": existing_triage["triage"]})[:16] + ".json")
        atomic_json(archive, {"rows": existing_triage["triage"], "reason": "current failures repaired"})
    atomic_json(C.artifact_write_path(task, "run-report.json"), report)
    atomic_json(triage_path, triage)
    atomic_json(C.artifact_write_path(task, "finalization-receipt.json"),
                {"task": task.name, "status": "complete", "sources": len(report["reducer"]["sources"])})
    return {"task": task.name, "sources": len(report["reducer"]["sources"]),
            "results": len(report["results"]), "manual_blocks": len(report["manual_checks"]),
            "execution_status": report["execution_status"], **_stamp_cases(task),
            **_refresh_delivery_manifest(task)}


def _refresh_delivery_manifest(task: Path) -> dict:
    """The delivery manifest is built LAST, after every record this reduce rewrote.

    S8 assembled it at step 2 and then the reducer, acceptance, the waivers and the ledger
    kept writing, so gate B of TP2-2553 read four `delivery manifest: stale hash`
    reasons about records the factory itself had just rewritten. Never raises into the
    reducer, same as `_stamp_cases`: a manifest that cannot be rebuilt is its own finding,
    not a reason `run-report.json` stops being written."""
    try:
        import delivery_manifest
        doc = delivery_manifest.refresh(task)
        return {} if doc is None else {"delivery_manifest": len(doc.get("files") or [])}
    except Exception as exc:
        return {"delivery_manifest_error": str(exc)}


def _stamp_cases(task: Path) -> dict:
    """A case's manifest evidence does not wait for someone to notice it — stamp it
    `Automated` right after every reduce, well before `delivery_manifest.py` assembles what
    gate B reads. Never raises into the reducer: a case-stamping failure is `case_stamp`'s own
    finding, not a reason `run-report.json` stops being written."""
    try:
        import case_stamp
        return {"case_stamp": case_stamp.stamp(task)}
    except Exception as exc:
        return {"case_stamp_error": str(exc)}


def main() -> int:
    C.force_utf8()
    parser = argparse.ArgumentParser(description="reduce task run blocks without executing tests")
    parser.add_argument("task_root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = refresh(Path(args.task_root))
    print(json.dumps(result, ensure_ascii=False) if args.json else
          f"finalize_task: {result['task']} — {result['sources']} blocks, {result['results']} results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
