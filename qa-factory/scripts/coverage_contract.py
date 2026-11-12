"""Behavior-level coverage: semantic assessments are explicit, outcomes are projections."""
import json
import re
from pathlib import Path

from event_store import content_hash
from hooklib import sorted_paths

COVERAGE_CONTRACT_REVISION = "coverage-observation-v1"


def _implementation_ref(value):
    """Assertion evidence cannot be a labelled production location."""
    return isinstance(value, str) and value.lower().startswith(("implementation:", "production:"))


def _parts_complete(obligation):
    """A declared compound part must resolve to this obligation's actual check evidence."""
    parts = obligation.get("parts")
    if not parts:
        return True
    refs = set()
    for link in obligation.get("coverage_links") or []:
        if isinstance(link, dict):
            refs.update(value for value in (link.get("candidate_id"), link.get("test_ref")) if value)
            refs.update(link.get("assertion_refs") or [])
    refs.update(obligation.get("planned_check_refs") or [])
    return all(isinstance(part, dict) and part.get("status") == "sufficient"
               and isinstance(part.get("covered_by"), list) and part["covered_by"]
               and set(part["covered_by"]).issubset(refs) for part in parts)


def _reused_candidate_join(task, obligation, binding):
    """When S1 named an existing candidate, a binding cannot invent its assertions.

    Legacy v2 plans and newly authored factory tests need no discovery candidate. They retain
    the accepted S5-window path; only a linked existing/changed candidate is joined here.
    """
    path = Path(task) / "work" / "context-bundle.json"
    try:
        bundle = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    except (OSError, ValueError):
        return False, "discovery candidate inventory unreadable"
    candidates = {c.get("candidate_id"): c for c in bundle.get("existing_test_candidates", [])
                  if isinstance(c, dict) and c.get("candidate_id")}
    links = [link for link in obligation.get("coverage_links") or [] if isinstance(link, dict)]
    if any(link.get("candidate_origin") in {"existing", "added_in_change"}
           and link.get("candidate_id") not in candidates for link in links):
        return False, "reused candidate missing from discovery inventory"
    linked = [link for link in links if link.get("candidate_id") in candidates]
    if not linked:
        return True, ""
    valid_union = set()
    required_existing = set()
    for link in linked:
        candidate = candidates[link["candidate_id"]]
        assessment = candidate.get("candidate_evidence") or candidate
        valid_refs = set(assessment.get("assertion_refs") or [])
        if (assessment.get("executable") is not True or assessment.get("assertion_status") != "sufficient"
                or not set(link.get("assertion_refs") or []).issubset(valid_refs)):
            return False, "reused candidate assertion evidence is missing, nonexecutable, or mismatched"
        if link.get("revision") and link["revision"] != candidate.get("revision"):
            return False, "reused candidate revision does not match the plan"
        if assessment.get("file_sha256"):
            import hashlib
            try:
                if hashlib.sha256(Path(assessment["test_file"]).read_bytes()).hexdigest() != assessment["file_sha256"]:
                    return False, "reused candidate file changed since discovery"
            except (OSError, KeyError):
                return False, "reused candidate file unavailable"
        valid_union.update(valid_refs)
        required_existing.update(link.get("assertion_refs") or [])
    bound = set(binding.get("assertion_refs") or [])
    if not bound or not required_existing or not required_existing.issubset(bound):
        return False, "reused candidate binding has unknown assertions"
    return True, ""



def _proof_owed(entry, manifest) -> bool:
    """Does the ONE predicate (`proof_level.proof_required`) say a live check is owed to this row or
    window item? A binding's role-written `unchanged` is a claim; the row's measured novelty decides
    (t-134 R7, critic V12): otherwise this module would call a measured-new test witnessed while the
    ledger says a check is owed (FR-10). The error direction is toward the demand: a predicate that
    raises (its contract says it never does) reads as owed, never as witnessed. A manifest that is
    not an object reads as `{}`."""
    import proof_level
    try:
        return bool(proof_level.proof_required(entry, manifest if isinstance(manifest, dict) else {}))
    except Exception:
        return True


def _manifest_owes_proof(manifest, instance_ids) -> bool:
    """True when a manifest row that lists any of `instance_ids` (under any alias, minus the
    manifest's `retracted_instances`) is owed a live check. An instance with NO row keeps today's
    behaviour (False): a story in flight is never refused over a row it does not have (builder-rules
    9); a row without a `novelty` key is the predicate's own (b) branch, not a second rule here."""
    if not isinstance(manifest, dict):
        return False
    import contract as C
    import proof_level
    listed = {str(i) for i in instance_ids or []}
    try:
        rows = C.manifest_tests(manifest)
        return any(listed & set(proof_level.without_retracted(C.instance_id_aliases(row), manifest))
                   and _proof_owed(row, manifest) for row in rows)
    except Exception:  # rows whose ids cannot be told: the layer cannot be read, so it demands
        return True


def _ref_file(root, raw):
    """(the file a task-relative ref names, why not): never outside the task, never through `..`."""
    if (not isinstance(raw, str) or not raw or Path(raw).is_absolute() or raw.startswith(("/", "\\"))
            or ".." in re.split(r"[\\/]+", raw)):
        return None, "ref outside the task"
    path = (root / raw).resolve()
    if not path.is_relative_to(root):
        return None, "ref outside the task"
    if not path.is_file():
        return None, "no file at " + raw
    return path, ""


def _first_difference(found, expected, path=""):
    """The first field, by name, where a receipt on disk differs from the one the accepted window
    gives: `receipt_hash` itself is named only when nothing else differs (it follows every other
    difference)."""
    if path == "instances" and isinstance(found, list) and isinstance(expected, list):
        have = {i.get("instance_id"): i for i in found if isinstance(i, dict)}
        want = {i.get("instance_id"): i for i in expected if isinstance(i, dict)}
        if len(have) != len(found) or len(want) != len(expected) or set(have) != set(want):
            return "instances (the set of instance ids differs)"
        for iid, item in want.items():
            if have[iid] != item:
                return _first_difference(have[iid], item, f"instances[{iid}]")
        return "instances (order)"
    if isinstance(found, dict) and isinstance(expected, dict):
        for key in list(expected) + [k for k in found if k not in expected]:
            if key == "receipt_hash" and not path:
                continue
            here = path + "." + key if path else key
            if key not in found or key not in expected:
                return here
            if found[key] != expected[key]:
                return _first_difference(found[key], expected[key], here)
        return path or "receipt_hash"
    return path or "receipt"


def window_of_ref(task, raw, state=None):
    """(the accepted S5 window a `review_receipt_ref` stands for, why none): reads, never writes.

    The ref may name the window file itself (the file must EQUAL an accepted window and be in that
    dispatch's evidence with its digest) or the immutable review receipt `window_record
    --review-receipt` writes - which is a receipt, never equal to the window (t-238: every binding
    published that way read "not witnessed"). For a receipt the expected receipt is REBUILT from the
    accepted dispatch's own window by `window_record.receipt_dict` and compared whole, so a receipt is
    evidence of the window's instances, not only that something ran (FR-18); the one difference allowed is
    the writer's own - `_per_test_difference` in {copy, legacy}. Any other answer is None and a reason."""
    import hashlib
    import window_record as WR
    root = Path(task).resolve()
    path, why = _ref_file(root, raw)
    if path is None:
        return None, why
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return None, f"{raw} unreadable: {error}"
    if state is None:
        from controller import Controller
        state = Controller(root).state()
    accepted = [(str(d.get("id") or key), d) for key, d in (state.get("dispatches") or {}).items()
                if isinstance(d, dict) and d.get("stage") == "S5" and d.get("status") == "accepted"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    for _, d in accepted:
        if d.get("window") == found and any(isinstance(r, dict) and r.get("path") == raw and r.get("sha256") == digest
                                            for r in d.get("evidence_refs") or []):
            return found, ""
    if not isinstance(found, dict) or found.get("receipt_kind") != "s5_review_window":
        return None, f"{raw} is neither an accepted window nor a review receipt"
    if found.get("receipt_hash") != content_hash({k: v for k, v in found.items() if k != "receipt_hash"}):
        return None, "receipt altered: its receipt_hash does not match its content"
    mine = [d for ident, d in accepted if ident == found.get("reviewer_dispatch_id") and isinstance(d.get("window"), dict)]
    if not mine:
        return None, "no accepted window for this receipt"
    dispatch = mine[-1]   # accepted twice: the latest is the window now
    window = dispatch["window"]
    named = False
    for ref in dispatch.get("evidence_refs") or []:
        file, _ = _ref_file(root, ref.get("path") if isinstance(ref, dict) else None)
        if file is None or file.suffix.lower() != ".json" or hashlib.sha256(file.read_bytes()).hexdigest() != ref.get("sha256"):
            continue
        try:
            named = json.loads(file.read_text(encoding="utf-8")) == window
        except (OSError, ValueError):
            named = False
        if named:
            break
    if not named:
        return None, "window file missing: no evidence ref of the accepted dispatch holds its window"
    expected = WR.receipt_dict(window)
    if found == expected or WR._per_test_difference(found, expected) in ("copy", "legacy"):
        return window, ""
    return None, "receipt differs from the accepted window at " + _first_difference(found, expected)


def demanded_quality(window) -> list:
    """The quality checks a window DEMANDS (HF4-10): its recorded `required_quality_checks` through the ONE reader
    (`window_record.demanded_quality_checks`); a window of an older build that lists readiness ids demands none."""
    from window_record import demanded_quality_checks
    return demanded_quality_checks(window.get("required_quality_checks", []))[0]


def witnessed_binding(task, binding, instance_ids, results=None):
    """Read a durable accepted S5 window, including hashes validated at acceptance.

    `review_receipt_ref` names the window file or the review receipt written for it (`window_of_ref`)."""
    from acceptance import validate_window
    try:
        root = Path(task).resolve()
        window, _why = window_of_ref(root, binding.get("review_receipt_ref"))
        if window is None:
            return False
        all_instances = window.get("instances", [])
        if (not isinstance(all_instances, list)
                or any(not isinstance(item, dict) or not item.get("instance_id") for item in all_instances)
                or len({item["instance_id"] for item in all_instances}) != len(all_instances)):
            return False
        mapped = {i["instance_id"]: i for i in all_instances}
        if not instance_ids or not set(instance_ids).issubset(mapped):
            return False
        if results is not None and any(not mapped[i].get("execution_fingerprint") or
                                      mapped[i]["execution_fingerprint"] != results.get(i, {}).get("input_fingerprint") for i in instance_ids):
            return False
        required_quality = set(demanded_quality(window))
        if required_quality:
            if set(binding.get("quality_receipt_refs") or []) != required_quality:
                return False
        elif binding.get("quality_receipt_refs"):
            # HF4-10 (B10-1): nothing is demanded -> no receipt AND no reason is owed; a ref to a receipt that is not owed is false
            return False
        # The exact accepted-window equality and receipt digest above protect the integrity
        # of the whole review. Product outcomes are obligation-local: validate only the
        # instances named by this binding, with exactly its applicable quality checks, so an
        # unrelated failed instance does not erase otherwise current passed evidence.
        # `dict(window, ...)` keeps the window's `mechanical_round`, so a review bound to the
        # bytes before a mechanical fix stays current here exactly as it did at acceptance:
        # through the author's green run block on the current bytes, read from `root`.
        applicable_quality = set(binding.get("quality_receipt_refs") or [])
        targeted = dict(window,
            instances=[mapped[i] for i in instance_ids],
            required_quality_checks=sorted(applicable_quality),
            quality_receipts=[r for r in window.get("quality_receipts", [])
                              if isinstance(r, dict) and r.get("id") in applicable_quality])
        if validate_window(targeted, root):
            return False
        for iid in instance_ids:
            item = mapped[iid]
            if item.get("change_disposition") != binding.get("change_disposition"):
                return False
            if item.get("change_basis_ref") != binding.get("change_basis_ref"):
                return False
            assertion_refs = item.get("assertion_refs") or [item.get("assertion_id")]
            if not set(binding.get("assertion_refs") or []).issubset(set(assertion_refs)):
                return False
            if binding.get("sensitivity") == "proven":
                if binding.get("proof_kind") == "design_analysis":
                    return False
                probe = item.get("probe") or {}
                ref = binding.get("probe_receipt_ref")
                if ref != probe.get("evidence_ref") or not any(r.get("path") == ref for r in item.get("evidence_refs", [])):
                    return False
            elif (binding.get("sensitivity") != "not_required" or item.get("change_disposition") != "unchanged"
                  or _proof_owed(item, {})):
                # The item is the window's record of the test: its measured novelty (P5-G) or its own
                # flags say a check is owed whatever the binding wrote. `proven` is untouched above.
                return False
        return all(any(ob.get("obligation_id") == binding.get("obligation_id")
                       and ob.get("obligation_hash") == binding.get("obligation_hash")
                       for ob in mapped[i].get("obligation_refs", [])) for i in instance_ids)
    except (ValueError, OSError, KeyError, TypeError):
        return False


def plan_rows(task):
    path = Path(task) / "work" / "test-plan.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value.get("rows", []) if isinstance(value, dict) else value


# F5(a): the fixed part of the refusal of a manual-agent obligation whose `evidence_policy` is not one word of the
# manual evidence policies. ONE producer (`validate_obligations`); `manual_evidence.prepare_request` reads it to tell a
# shape error (the factory's own, walkable) from any other error of the plan (F5(c) item 1).
POLICY_SHAPE_ERROR = "evidence_policy is one word of"
# The same class for a `manual-human` obligation (m9, t-1945): its policy is text, not a list or a record - also the factory's own.
POLICY_TYPE_ERROR = "manual evidence_policy is one word (text)"

# F5(d): the one issue of `validate_manual_current` for an unprepared walk (a record carrying `unprepared`, no result).
UNPREPARED = "unprepared walk: no result is bound"


def unprepared_only(issues) -> bool:
    """True exactly when `validate_manual_current` found nothing but the unprepared marker (F5(d), AR-13)."""
    return list(issues or []) == [UNPREPARED]


def _version_door(row):
    """The tail of the refusal of a row that is not on schema version 2 (TR2-6/8, B-9; FR-1): the KEY NAME and its value,
    and, when the row carries a key that looks like it (`coverage_schema_version`), that this is not the key. Reads the
    row's key names only; the verdict stays with the caller."""
    alike = sorted(k for k in row if isinstance(k, str) and k != "schema_version" and "schema" in k and "version" in k)
    seen = f" (this row has {', '.join('`' + k + '`' for k in alike)}, which is not the key)" if alike else ""
    return f": the row key is exactly `schema_version`, written as the number 2 (`schema_version: 2`){seen}"


def validate_obligations(rows, require_v2=False):
    errors, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue  # base plan validator reports this
        version = row.get("schema_version", 1)
        if version not in (1, 2) or (require_v2 and version != 2):
            errors.append(f"{row.get('id')}: coverage schema version 2 required" + _version_door(row))
        if version == 1:
            continue
        revision = row.get("coverage_contract_revision")
        if revision not in (None, COVERAGE_CONTRACT_REVISION):
            errors.append(f"{row.get('id')}: unsupported coverage_contract_revision {revision}")
        obligations = row.get("coverage_obligations")
        if not isinstance(obligations, list) or not obligations:
            errors.append(f"{row.get('id')}: coverage_obligations required")
            continue
        for ob in obligations:
            if not isinstance(ob, dict):
                errors.append("obligation must be an object")
                continue
            oid = ob.get("obligation_id")
            if not oid or oid in ids:
                errors.append("obligation IDs must be nonempty and unique")
            ids.add(oid)
            # Every message below names the FIELD and the value it expects in one sentence (FR-1; F-cmp2-14):
            # a role without Bash reads these through a hook and has nothing else to go on. `missing {field}`
            # stays the prefix of the first one: a variant check matches it by text.
            for field in ("behavior", "observation_boundary", "completion_condition"):
                if not ob.get(field):
                    errors.append(f"{oid}: missing {field}: {field} needs a non-empty sentence")
            for field, shape in (("requirement_refs", "{ref, revision} objects"),
                                 ("applicable_scenarios", "scenario ids")):
                if not isinstance(ob.get(field), list) or not ob[field]:
                    errors.append(f"{oid}: {field} needs a non-empty list of {shape}")
            refs = ob.get("requirement_refs", [])
            if isinstance(refs, list):
                bad_refs = [i for i, r in enumerate(refs)
                            if not isinstance(r, dict) or not r.get("ref") or not r.get("revision")]
                if bad_refs:
                    errors.append(f"{oid}: " + ", ".join(f"requirement_refs[{i}]" for i in bad_refs)
                                  + " needs {ref, revision}, both non-empty")
            if ob.get("oracle_status") not in {"resolved", "unresolved"}:
                errors.append(f"{oid}: oracle_status: not filled. One of: resolved | unresolved")
            if ob.get("oracle_status") == "resolved" and not ob.get("oracle_source_ref"):
                errors.append(f"{oid}: oracle_source_ref needs the independent source (a requirement or "
                              "spec reference, not the code under test) when oracle_status is resolved")
            if ob.get("decision") not in {"reuse", "extend", "new", "manual-agent", "manual-human", "unresolved"}:
                errors.append(f"{oid}: decision: not filled. One of: reuse | extend | new | manual-agent | "
                              "manual-human | unresolved")
            if ob.get("execution_scope") not in {"current_task", "recommended_regression"}:
                errors.append(f"{oid}: execution_scope: not filled. One of: current_task | recommended_regression")
            if ob.get("oracle_status") == "unresolved" and ob.get("decision") != "unresolved":
                errors.append(f"{oid}: decision needs unresolved while oracle_status is unresolved "
                              "(an unresolved oracle cannot authorize execution)")
            review = ob.get("sufficiency_review") or {}
            if not all(review.get(k) for k in ("author_dispatch_id", "input_hash", "rationale")):
                errors.append(f"{oid}: sufficiency_review required: {{author_dispatch_id, input_hash, rationale}}, all non-empty")
            links = ob.get("coverage_links")
            if not isinstance(links, list):
                errors.append(f"{oid}: coverage_links needs a list of links ([] when no existing test is linked)")
                links = []
            if ob.get("decision") == "reuse" and not links:
                errors.append(f"{oid}: coverage_links needs at least one link when decision is reuse")
            if ob.get("decision") in {"extend", "new", "manual-agent", "manual-human"} and not ob.get("planned_check_refs"):
                errors.append(f"{oid}: planned_check_refs needs at least one check id when decision is "
                              "extend | new | manual-agent | manual-human")
            for i, link in enumerate(links):
                at = f"coverage_links[{i}]"
                if not isinstance(link, dict):
                    errors.append(f"{oid}: {at} needs an object {{candidate_id or test_ref, assessment, "
                                  "assessment_reason, does_not_prove}")
                    continue
                if not (link.get("candidate_id") or link.get("test_ref")):
                    errors.append(f"{oid}: {at} needs candidate_id (CAND-n) or test_ref (a test node id)")
                if link.get("assessment") not in {"sufficient", "partial", "none", "unknown"} or not link.get("assessment_reason"):
                    errors.append(f"{oid}: {at} needs assessment: one of sufficient | partial | none | unknown, "
                                  "and assessment_reason")
                if not isinstance(link.get("does_not_prove"), list):
                    errors.append(f"{oid}: {at} needs does_not_prove: a list ([] when nothing is left unproven)")
                if link.get("assessment") == "sufficient" and (not link.get("assertion_refs") or not link.get("proves")):
                    errors.append(f"{oid}: {at} with assessment sufficient needs assertion_refs and proves, "
                                  "both non-empty lists")
                if any(_implementation_ref(ref) for ref in link.get("assertion_refs") or []):
                    errors.append(f"{oid}: {at}.assertion_refs needs test assertion ids, not production code references")
                # Candidate metadata is owned by the context bundle. When supplied here as a
                # projection, it can rule out an inflated coverage claim without rejecting
                # older v2 plans that have not yet been enriched.
                kind = link.get("candidate_kind")
                if kind not in {None, "test", "suite", "helper"}:
                    errors.append(f"{oid}: {at}.candidate_kind: one of test | suite | helper (or leave it out)")
                if kind == "helper" and link.get("assessment") == "sufficient":
                    errors.append(f"{oid}: helper cannot be sufficient executable coverage")
                if kind == "test" and not link.get("executable_selector"):
                    errors.append(f"{oid}: test candidate needs executable selector")
                if kind == "suite" and link.get("assessment") == "sufficient" and not link.get("expanded_selectors"):
                    errors.append(f"{oid}: suite needs expanded selectors for sufficient coverage")
            parts = ob.get("parts")
            if parts is not None:
                if not isinstance(parts, list) or not parts:
                    errors.append(f"{oid}: parts must be a nonempty list when supplied")
                elif any(not isinstance(part, dict) or not part.get("part_id") or
                         part.get("status") not in {"sufficient", "partial", "unresolved"}
                         for part in parts):
                    errors.append(f"{oid}: every part needs ID and explicit status")
                elif any(part.get("status") == "sufficient" and
                         (not isinstance(part.get("covered_by"), list) or not part["covered_by"])
                         for part in parts):
                    errors.append(f"{oid}: sufficient part needs explicit covered_by evidence")
            comparison = ob.get("comparison")
            if comparison is not None and (not isinstance(comparison, dict) or
                                           not comparison.get("left") or not comparison.get("right") or
                                           not comparison.get("caller_ref")):
                errors.append(f"{oid}: comparison needs both inputs and caller reference")
            parity = ob.get("parity")
            if parity is not None and (not isinstance(parity, dict) or not parity.get("partitions")):
                errors.append(f"{oid}: parity needs independent input partitions")
            if ob.get("decision") == "unresolved" and not ob.get("remaining_gap"):
                errors.append(f"{oid}: unresolved gap must be named")
            if ob.get("decision") == "manual-agent":
                # F5(a) (B-15): the policy is ONE word of POLICIES (the one set, manual_evidence's); a dict, a list, a
                # blank or an unknown word is refused here, at the S3 exit, with the allowed words (FR-38, FR-1)
                from manual_evidence import POLICIES
                policy = ob.get("evidence_policy")
                if not isinstance(policy, str) or policy.strip() not in POLICIES:
                    errors.append(f"{oid}: {POLICY_SHAPE_ERROR} {'|'.join(sorted(POLICIES))}; evidence kinds, phases "
                                  "and the completion condition go in completion_condition and the observation fields")
            elif ob.get("decision") == "manual-human":
                policy = ob.get("evidence_policy")
                if not isinstance(policy, str):
                    errors.append(f"{oid}: {POLICY_TYPE_ERROR}, not a list or a record")
                elif not policy.strip():
                    errors.append(f"{oid}: manual evidence_policy required before Gate A")
            from observation_contract import validate_observation_contract
            errors.extend(validate_observation_contract(
                ob, required=revision == COVERAGE_CONTRACT_REVISION))
    return errors


# What the coverage report says of an obligation whose only test the code critic could not verify
# (D-0013); the person's debt, in the words "Left with you" uses.
UNVERIFIED_GAP = ("the code critic could not verify the test that covers it; it is left with you: "
                  "run it where you can, or accept the risk")


def awaiting_gap(oracle: dict) -> str:
    """The gap of an obligation that waits for a person's answer, in the task's own terms (FR-20)."""
    qid = oracle.get("question") or ""
    return ("the expected result is not confirmed by anyone; it is left with you: "
            + (f"your answer to {qid} is needed" if qid else "no question about it was raised yet"))


def _oracle_context(task) -> dict:
    """What the read-time oracle of an obligation needs, read ONCE per projection (t-227c, P20): the
    register text, whether the register is under the dated rule, the question rows
    (`question_register.load`; `{}` when the story has none) and every case file by plan row.
    Never raises on a story's own data: a reader that cannot read says nothing and the stored
    `oracle_status` stands (a projection is not the place to refuse, P1)."""
    import contract as C
    ctx = {"register": "", "dated": False, "questions": {}, "cases": {}, "date_problem": ""}
    try:
        ctx["register"] = C.read_text(C.artifact(task, "requirements-register.md"))
        created = C.front_line(ctx["register"], "created")
        # F1 (t-269): a register whose `created` is missing or no date is NOT "before the cutoff" - reading
        # it so switched the whole dated rule off with no word. A projection never refuses (P1), so it errs
        # toward the rule being ON (an implementation-only R then waits for a person) and says why.
        ctx["date_problem"] = C.oracle_date_problem(created, "created") if ctx["register"].strip() else ""
        ctx["dated"] = C.after_oracle_cutoff(created) or bool(ctx["date_problem"])
        import question_register as QR
        ctx["questions"] = {str(q.get("id") or ""): q for q in QR.load(task).get("questions", [])
                            if isinstance(q, dict) and q.get("id")}
        for meta in C.case_index(task).values():
            if meta.get("plan_row") and meta.get("path"):
                ctx["cases"].setdefault(str(meta["plan_row"]), []).append(
                    (C.read_text(Path(meta["path"])), set(meta.get("requirements") or [])))
    except Exception:
        pass
    return ctx


def _oracle_read(ctx: dict, row: dict, ob: dict) -> dict:
    """Where this obligation's expected value stands NOW, from the sources and not from what the plan
    recorded once (C3/C6, FR-16): {status: resolved | unresolved, waiting: bool, question: id or "",
    answers: [{then, question, expected}]}.

    `waiting` - the obligation is unresolved because a PERSON has not answered: a Then of a case that
    names it reads `open` through `contract.resolve_then_oracle` (an `unknown` oracle whose question is
    open), or it rests on a requirement that exists only in the diff (`unconfirmed_implementation_only`)
    whose claim nobody answered - the false `resolved` of an implementation-only R-19 (F20). It is the
    person's debt and holds nothing (F7). An `unknown` Then whose question is ANSWERED reads `person`
    with the answered value, and a stored `unresolved` obligation that had only such Thens reads
    `resolved` - the approved case is never edited after gate A. Legacy: a case with no `then_oracles`
    and a register older than the oracle cutoff change nothing, so every story before t-227 reads as
    its plan says. The error direction is toward `unresolved`."""
    import contract as C
    from traceability import then_oracle_states
    stored = str(ob.get("oracle_status") or "")
    read = {"status": stored, "waiting": False, "question": "", "answers": []}
    oid = str(ob.get("obligation_id") or "")
    refs = {str(r.get("ref") or "") for r in ob.get("requirement_refs") or [] if isinstance(r, dict)}
    if ctx["dated"]:
        claims = C.claim_questions(ctx["register"])
        open_r = C.unconfirmed_requirements(ctx["register"], ctx["questions"])
    else:
        # An undated (legacy) register keeps its S2 rows unread, but a claim the grounding step added to it
        # (`origin: S3-grounding`, G1-13) is never read as a resolved oracle: the date of S2 does not switch off S3's claim (P20).
        mine = [row for row in C.behaviour_claims(ctx["register"]) if row.get("origin") == C.CLAIM_ORIGIN_S3]
        claims = {}
        for row in mine:
            claims.setdefault(row["r"], row["question"])
        open_r = C.unconfirmed_requirements(ctx["register"], ctx["questions"]) & set(claims)
    held = sorted(refs & open_r)
    if held:
        read.update(status="unresolved", waiting=True, question=claims.get(held[0], ""))
    unknown_seen = open_thens = 0
    for text, case_requirements in ctx["cases"].get(str(row.get("id") or ""), []):
        # The obligation a case answers for comes from the approved MAPPING (the case's requirements against
        # the obligation's `requirement_refs`, the join `manual_evidence._case_obligation_mapping` makes), not
        # from whether the case text happens to print the id (t-269 F2: a case that never names OB-15 was
        # never read, and its unknown Then left the obligation `resolved`).
        if not oid or not (case_requirements & refs):
            continue
        entries, _ = C.then_oracles_from_text(text)
        for entry, state in zip(entries or [], then_oracle_states(text, ctx["questions"])):
            if str(entry.get("source") or "") != "unknown":
                continue
            unknown_seen += 1
            if state["state"] == "open":
                open_thens += 1
                if not read["question"]:
                    read["question"] = state["ref"]
            elif state["source"] == "person":
                read["answers"].append({"then": state["then"], "question": state["ref"], "expected": state["expected"]})
    if open_thens:
        read.update(status="unresolved", waiting=True)
    elif unknown_seen and not read["waiting"] and stored == "unresolved":
        read["status"] = "resolved"
    return read


def coverage_projection(task, report=None, manifest=None):
    """No executions, no positive semantic inference from green or a percentage."""
    import contract as C
    rows = plan_rows(task)
    oracle_ctx = _oracle_context(task)
    report = report if report is not None else C.load_json(C.artifact(task, "run-report.json"))
    manifest = manifest if manifest is not None else C.load_json(C.artifact(task, "automation-manifest.json"))
    results = C.current_instance_results(report)
    bindings = manifest.get("obligation_bindings") or []
    import ledger as L
    unverified_instances = {alias for test in C.manifest_tests(manifest) if L.is_unverified(test)
                            for alias in C.instance_id_aliases(test)}
    output = []
    for row in rows:
        if row.get("schema_version", 1) != 2:
            continue
        for ob in row.get("coverage_obligations") or []:
            oid = ob["obligation_id"]
            matching = [b for b in bindings if b.get("obligation_id") == oid]
            binding = matching[0] if len(matching) == 1 else {}
            current = binding.get("obligation_hash") == content_hash(ob)
            design = binding.get("design_assessment", "unknown") if current else "unknown"
            instance_ids = binding.get("instance_ids") or []
            outcomes = [results.get(i, {}) for i in instance_ids]
            if not outcomes:
                execution = "not_run"
            elif any(r.get("stale") for r in outcomes):
                execution = "stale"
            elif any(C.result_status(r) in {"failed", "error"} for r in outcomes):
                execution = "failed"
            elif all(C.result_status(r) == "passed" for r in outcomes):
                execution = "passed"
            else:
                execution = "inconclusive"
            validity = binding.get("code_validity", "unverified") if current else "unverified"
            sensitivity = binding.get("sensitivity", "missing") if current else "missing"
            # Actual review/quality/probe witnesses, not just status strings, are required.
            witnessed = current and bool(binding.get("assertion_refs")) and witnessed_binding(task, binding, instance_ids, results)
            candidate_joined, candidate_gap = _reused_candidate_join(task, ob, binding)
            witnessed = witnessed and candidate_joined
            # HF4-10 (B10-1): the quality condition is `witnessed_binding`'s alone (refs equal what the window DEMANDS, none when
            # nothing is demanded); a second "refs or a reason" here would demand a field for an empty requirement.
            witnessed = witnessed and (sensitivity == "proven" and bool(binding.get("probe_receipt_ref")) or
                sensitivity == "not_required" and binding.get("change_disposition") == "unchanged" and bool(binding.get("change_basis_ref"))
                and not _manifest_owes_proof(manifest, instance_ids))
            manual = [r for r in report.get("current_manual_checks", [])
                      if oid in (r.get("current_obligation_ids") or r.get("obligation_ids") or [r.get("obligation_id")])]
            # P20 (t-227c): the oracle as the SOURCES say now, not as the plan recorded it once.
            try:
                oracle = _oracle_read(oracle_ctx, row, ob)
            except Exception:  # a projection never refuses over a story's own data (P1): the stored status stands
                oracle = {"status": str(ob.get("oracle_status") or ""), "waiting": False, "question": "", "answers": []}
            oracle_status = oracle["status"]
            unprepared_reason = ""
            if ob.get("decision") in {"manual-agent", "manual-human"}:
                # F5(e) 2: an unprepared walk is no result row - `execution` is computed on the result rows only (none ->
                # `not_run`) and the item names the walk (AR-27); `verified` stays False
                unprepared_rows = [r for r in manual if r.get("unprepared") is not None]
                manual = [r for r in manual if r.get("unprepared") is None]
                if unprepared_rows:
                    marker = unprepared_rows[-1].get("unprepared")
                    unprepared_reason = str((marker.get("reason") if isinstance(marker, dict) else marker) or "no reason recorded")
                valid_manual = [r for r in manual if r.get("evidence_validated") and not r.get("stale")
                                and not validate_manual_current(task, r)]
                execution = "passed" if valid_manual and len(valid_manual) == len(manual) and all(r.get("result") == "pass" for r in valid_manual) else "failed" if any(r.get("result") == "fail" for r in valid_manual) else "inconclusive" if manual else "not_run"
                design = "sufficient" if valid_manual and oracle_status == "resolved" else "unknown"
                validity, sensitivity, witnessed = "not_applicable", "not_required", bool(valid_manual)
            verified = (ob.get("execution_scope") == "current_task" and oracle_status == "resolved"
                        and design == "sufficient" and execution == "passed" and validity in {"valid", "not_applicable"}
                        and witnessed and _parts_complete(ob))
            # D-0013: a green test the critic could not verify is not "evidence incomplete" - it is the
            # person's debt, said in words and never counted as a delivery gap. Only when nothing else is
            # missing (design sufficient, run green, no named gap); a red run or an unresolved oracle
            # keeps its own, blocking, gap.
            person_debt = bool(
                not verified and ob.get("execution_scope") == "current_task" and oracle_status == "resolved"
                and design == "sufficient" and execution == "passed" and _parts_complete(ob)
                and not candidate_gap and not ob.get("remaining_gap")
                and set(instance_ids) & unverified_instances)
            # The one unresolved oracle that is NOT a block (C3/F7): it waits for a person's answer. It is
            # `unresolved` AND the person's debt - never "blocking unresolved oracle" - unless a red run of
            # it exists, which keeps its own, blocking, gap.
            awaiting = bool(not verified and oracle["waiting"] and ob.get("execution_scope") == "current_task"
                            and execution != "failed")
            item = {"obligation_id": oid, "plan_row": row["id"], "decision": ob["decision"],
                "execution_scope": ob["execution_scope"], "design_assessment": design,
                "execution_state": execution, "code_validity": validity, "sensitivity": sensitivity,
                "verified": bool(verified), "person_debt": person_debt or awaiting,
                # RD1-21: the only closed oracle is `resolved` (`verified` needs it). The delivery check reads this with
                # `execution_state` to tell a red or an unproven-oracle obligation (the product's) from missing evidence.
                "oracle_open": oracle_status != "resolved",
                "instance_ids": sorted(set(instance_ids)),
                "gap": "" if verified else awaiting_gap(oracle) if awaiting else UNVERIFIED_GAP if person_debt
                else candidate_gap or ob.get("remaining_gap") or
                ("compound obligation has an incomplete part" if not _parts_complete(ob)
                 else "current sufficient evidence incomplete")}
            if unprepared_reason:
                item["unprepared"] = unprepared_reason
                if not verified and not awaiting and not person_debt:
                    item["gap"] = f"not checked by hand: unprepared - {unprepared_reason}"
            if oracle_status != str(ob.get("oracle_status") or "") or oracle["answers"]:
                # What the projection read differs from what the plan stored (read at read time, the
                # approved plan is never edited): say so, with the answered value.
                item["oracle_status"] = oracle_status
                if oracle["answers"]:
                    item["oracle_answers"] = oracle["answers"]
            output.append(item)
    doc = {"schema_version": 2, "status": "current" if output else "legacy_assessment_not_available",
           "obligations": output, "unique_instances": len({i for o in output for i in o["instance_ids"]})}
    if oracle_ctx.get("date_problem"):
        doc["oracle_date_problem"] = "requirements-register.md: " + oracle_ctx["date_problem"]
    return doc


def recorded_checkout_revisions(task, profile_id) -> set:
    """The revisions of a profile's checkout that this story's runs recorded: `expected_source_revision` of every
    `evidence/runtime-provenance-*.json` of the task whose `profile_id` is `profile_id` (`runtime_probe.py` writes
    one per run, with the checkout's git HEAD). Empty when the story recorded none for the profile, and then no
    manual proof can bind to it (unknown is not a match, FR-41). `unknown` - the probe's word for a revision it
    could not read - is never a revision."""
    found = set()
    wanted = str(profile_id or "").strip()
    for path in sorted_paths((Path(task) / "evidence").glob("runtime-provenance-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and wanted and str(data.get("profile_id") or "").strip() == wanted:
            revision = str(data.get("expected_source_revision") or "").strip()
            if revision and revision != "unknown":
                found.add(revision)
    return found


def _validate_unprepared(task, record):
    """F5(d): the issues of a record carrying `unprepared` - ALWAYS starting with UNPREPARED, never empty, so every
    filter `not validate_manual_current(r)` keeps it out of the results (FR-59). The marker is honoured only where code
    wrote it (E5.8): the case's `request.json` holds `unprepared` with the same reason. Presence checks only (AR-29)."""
    import manual_evidence as ME
    issues = [UNPREPARED]
    marker = record.get("unprepared")
    reason = marker.get("reason") if isinstance(marker, dict) else None
    request = ME.unprepared_request(task, record.get("case"))
    if not request or not reason or request.get("reason") != reason:
        issues.append("unprepared marker without an unprepared request")
    if "result" in record or "then_quotes" in record:
        issues.append("an unprepared walk records no result: its observations go to the analyst")
    if request:
        recorded = record.get("obligation_ids") or [record.get("obligation_id")]
        if sorted(str(x) for x in recorded) != sorted(str(x) for x in request.get("obligation_ids") or []):
            issues.append("an unprepared walk names the obligations of its request")
    return issues


def validate_manual_current(task, record):
    """Bind capture policy, exact case version, approved scope and source to planned intent."""
    import contract as C
    from controller import Controller
    from manual_evidence import validate_record
    if record.get("unprepared") is not None:
        return _validate_unprepared(task, record)
    state = Controller(task).state()
    captured_ids = record.get("obligation_ids") or [record.get("obligation_id")]
    ids = record.get("current_obligation_ids") or captured_ids
    obligations = {ob["obligation_id"]: ob for row in plan_rows(task) for ob in row.get("coverage_obligations", [])}
    errors = []
    if (not ids or any(oid not in obligations for oid in ids)
            or any(oid not in captured_ids for oid in ids)):
        return ["manual capture has no matching planned obligation"]
    scoped_record = dict(record)
    scoped_record.pop("obligation_id", None)
    scoped_record["obligation_ids"] = list(ids)
    scoped_record["obligation_hashes"] = {oid: (record.get("obligation_hashes") or {}).get(oid)
                                           for oid in ids}
    for oid in ids:
        ob = obligations[oid]
        errors.extend(validate_record(scoped_record, task, ob.get("evidence_policy")))
        if (ob.get("execution_scope") != "current_task" or ob.get("oracle_status") != "resolved"
                or ob.get("decision") not in {"manual-agent", "manual-human"}):
            errors.append("manual capture not authorized by planned scope/oracle")
        if record.get("obligation_hashes", {}).get(oid) != content_hash(ob):
            errors.append("manual capture binds stale or missing obligation hash")
        if record.get("completion_condition") != ob.get("completion_condition"):
            errors.append("manual completion_condition differs from approved design")
        if ob.get("evidence_policy") == "static":
            planned_reason = ob.get("before_not_applicable_reason")
            if (not planned_reason or record.get("before_not_applicable_reason") != planned_reason):
                errors.append("static before_not_applicable_reason differs from approved design")
    captured_known = [oid for oid in captured_ids if oid in obligations]
    original_hashes = record.get("obligation_hashes") or {}
    if len(captured_known) != len(captured_ids) or set(original_hashes) != set(captured_ids):
        errors.append("manual capture obligation hashes do not bind the captured set")
    policy_contract = {"evidence_policy": obligations[captured_known[0]].get("evidence_policy") if captured_known else None,
                       "completion_condition": obligations[captured_known[0]].get("completion_condition") if captured_known else None,
                       "obligation_hashes": {oid: original_hashes.get(oid) for oid in captured_ids}}
    if record.get("approved_policy_hash") != content_hash(policy_contract):
        errors.append("manual capture does not bind the approved evidence policy")
    if not record.get("gate_a_decision_ref"):
        errors.append("manual capture does not bind the approving Gate A decision")
    if not state.get("source_revision") or record.get("source_revision") != state["source_revision"]:
        errors.append("manual source revision unknown or stale")
    from profile_contract import ACCEPTS, acceptable_provenance, no_changed_file, refusal_text, validate_runtime_provenance
    before, after = record.get("runtime_before"), record.get("runtime_after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        errors.append("manual runtime before/after provenance required")
    else:
        story = Path(str(task)).name      # a person's word is bound to ONE story (t-300 N2 X5): never another's
        local_source = record.get("runtime_required") is False and record.get("target_kind") == "local_source"
        for probe in (before, after):
            checked = validate_runtime_provenance(probe)
            # ONE predicate (t-300 N2 S13, FR-17), the same as manual_evidence.validate: `matched`, the person's word for
            # THIS story, a probe that compared nothing - and the local_source `not_applicable` beside it. `unknown` is
            # refused, with or without an image (t-279 Q1 took it; Q18-B, FR-59 retire it): the person's word at the
            # build question is the door. The rule below makes before and after name the same identity.
            if not (acceptable_provenance(probe, ACCEPTS, task=story)
                    or (checked["valid"] and checked["result"] == "not_applicable" and local_source)):
                errors.append("manual runtime provenance is unverified: " + refusal_text(probe, task=story))
            # t-275 (A): the probe names the revision of the PROFILE'S CHECKOUT (its git HEAD, 40 hex), never the
            # controller's `source_revision` (the sha256 of the ticket snapshot, 64 hex): the two can never be
            # equal, so comparing them refused every real manual record. What binds the proof to this story is
            # the revision a run of this story recorded for the same profile (`evidence/runtime-provenance-*.json`).
            # A probe that did not apply (a local source with no runtime) compared nothing and binds nothing.
            if probe.get("result") != "not_applicable" and probe.get("expected_source_revision") not in \
                    recorded_checkout_revisions(task, probe.get("profile_id")):
                errors.append("manual runtime proof binds a checkout revision no run of this story recorded for its "
                              "profile: run runtime_probe.py for that profile so its revision is on record")
            # A probe that says `reason_code: no_changed_file` compared nothing because the story changes no file
            # of this checkout: enough on any stand kind (t-279 K-NA); any other not_applicable stays local_source.
            if probe.get("result") == "not_applicable" and not no_changed_file(probe) and not (record.get("runtime_required") is False and record.get("target_kind") == "local_source"):
                errors.append("live manual interaction cannot bypass runtime identity")
        for key in ("profile_id", "environment_id", "expected_source_revision", "observed_runtime_identity"):
            if before.get(key) != after.get(key):
                errors.append("manual runtime changed during execution")
    pins = {p.get("case_id"): p.get("version") for p in C.story_case_links(task)}
    if not record.get("case_version") or pins.get(record.get("case")) != record["case_version"]:
        errors.append("manual case version is not the approved pinned version")
    dispatch = state.get("dispatches", {}).get(record.get("dispatch_id"), {})
    if (dispatch.get("stage") != "S6" or dispatch.get("status") not in {"running", "accepted"}
            or record.get("case") not in dispatch.get("scope", [])):
        errors.append("manual capture must bind a current S6 dispatch")
    return sorted(set(errors))
