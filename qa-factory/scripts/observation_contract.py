"""Typed design-time observation contracts for coverage obligations.

The validator proves shape and reference joins only.  It deliberately cannot prove that a
reviewer found every mutable surface or that the selected oracle is semantically correct.
"""

CLAIM_KINDS = {"state_unchanged", "no_write_attempt", "response_parity", "no_leak",
               "rendered_behavior", "ordinary"}
SURFACE_STATUSES = {"planned", "observed", "gap"}
SEQUENCE_PHASES = ("before_read", "action", "completion", "after_read")


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _declared_refs(values):
    refs = set()
    for value in values or []:
        if isinstance(value, str) and value:
            refs.add(value)
        elif isinstance(value, dict):
            refs.update(value[key] for key in ("id", "ref", "scenario_id", "step_id", "check_id")
                        if isinstance(value.get(key), str) and value[key])
            refs.update(_declared_refs(value.get("steps")))
            refs.update(_declared_refs(value.get("checks")))
    return refs


def _known_refs(obligation):
    refs = set(obligation.get("planned_check_refs") or [])
    refs.update(_declared_refs(obligation.get("applicable_scenarios")))
    for link in obligation.get("coverage_links") or []:
        if isinstance(link, dict):
            refs.update(link.get("assertion_refs") or [])
            refs.update(value for value in (link.get("candidate_id"), link.get("test_ref")) if value)
    for part in obligation.get("parts") or []:
        if isinstance(part, dict) and part.get("part_id"):
            refs.add(part["part_id"])
    return refs


def validate_observation_contract(obligation, required=False):
    """Return structural errors for one obligation's observation contract."""
    oid = obligation.get("obligation_id", "<unknown>")
    value = obligation.get("observation_contract")
    if value is None:
        return [f"{oid}: observation_contract required by coverage contract revision"] if required else []
    if not isinstance(value, dict):
        return [f"{oid}: observation_contract must be an object"]
    errors = []
    kinds = value.get("claim_kind")
    if not _strings(kinds) or not kinds or not set(kinds).issubset(CLAIM_KINDS):
        errors.append(f"{oid}: observation claim_kind must use the closed vocabulary")
        kinds = []
    oracle = value.get("oracle_ref")
    if not isinstance(oracle, dict) or not oracle.get("ref") or not oracle.get("revision"):
        errors.append(f"{oid}: observation oracle_ref must bind ref and revision")
    surfaces = value.get("surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append(f"{oid}: observation surfaces must be nonempty")
        surfaces = []
    surface_ids = set()
    has_gap = False
    for surface in surfaces:
        if not isinstance(surface, dict):
            errors.append(f"{oid}: observation surface must be an object")
            continue
        sid = surface.get("id")
        if not isinstance(sid, str) or not sid or sid in surface_ids:
            errors.append(f"{oid}: observation surface IDs must be nonempty and unique")
        if isinstance(sid, str):
            surface_ids.add(sid)
        if not surface.get("boundary"):
            errors.append(f"{oid}: observation surface needs boundary")
        status = surface.get("status")
        if status not in SURFACE_STATUSES:
            errors.append(f"{oid}: observation surface status is invalid")
        if status == "gap":
            has_gap = True
            if not surface.get("gap_reason"):
                errors.append(f"{oid}: gap surface needs gap_reason")
        elif surface.get("gap_reason"):
            errors.append(f"{oid}: gap_reason is allowed only for a gap surface")
        elif not surface.get("assertion_ref"):
            errors.append(f"{oid}: planned or observed surface needs assertion_ref")
    refs = _known_refs(obligation)
    if any(isinstance(surface, dict) and surface.get("assertion_ref") and
           surface.get("assertion_ref") not in refs for surface in surfaces):
        errors.append(f"{oid}: surface assertion_ref must reference an existing check or step")
    controls = value.get("controls")
    if not _strings(controls) or not set(controls).issubset(refs):
        errors.append(f"{oid}: controls must reference existing checks or steps")
    completion_ref = value.get("completion_ref")
    if not isinstance(completion_ref, str) or not completion_ref or completion_ref not in refs:
        errors.append(f"{oid}: completion_ref must reference an existing check or step")
    expectations = value.get("independent_expectations")
    if not isinstance(expectations, list):
        errors.append(f"{oid}: independent_expectations must be an array")
        expectations = []
    for expected in expectations:
        if not isinstance(expected, dict) or not all(expected.get(field) for field in
                ("partition_ref", "expected_ref", "attribution_assertion_ref")):
            errors.append(f"{oid}: independent expectation needs partition, expected, and attribution refs")
        elif expected["attribution_assertion_ref"] not in refs:
            errors.append(f"{oid}: expectation attribution must reference an existing assertion")
    if "response_parity" in kinds and len(expectations) < 2:
        errors.append(f"{oid}: response parity needs independent expectations for each partition")
    elif "response_parity" in kinds and len({item.get("partition_ref") for item in expectations
            if isinstance(item, dict)}) != len(expectations):
        errors.append(f"{oid}: response parity partition refs must be unique")
    conflicts = value.get("source_conflicts")
    if not _strings(conflicts):
        errors.append(f"{oid}: source_conflicts must be an explicit array of decision IDs")
        conflicts = []
    if isinstance(oracle, dict):
        requirements = {(item.get("ref"), item.get("revision"))
                        for item in obligation.get("requirement_refs") or [] if isinstance(item, dict)}
        declared_conflicts = _declared_refs(obligation.get("source_conflict_refs"))
        if oracle.get("ref") in {ref for ref, _ in requirements} and (oracle.get("ref"), oracle.get("revision")) not in requirements:
            errors.append(f"{oid}: oracle_ref revision must match the requirement revision")
        elif oracle.get("ref") not in {ref for ref, _ in requirements} | declared_conflicts:
            errors.append(f"{oid}: oracle_ref must join a requirement or source-conflict decision")
        if not set(conflicts).issubset(declared_conflicts):
            errors.append(f"{oid}: source_conflicts must join declared question or decision refs")
    sequence = value.get("sequence")
    if any(kind in kinds for kind in ("state_unchanged", "no_write_attempt")):
        if (not isinstance(sequence, list) or
                [item.get("phase") for item in sequence if isinstance(item, dict)] != list(SEQUENCE_PHASES) or
                len(sequence) != len(SEQUENCE_PHASES) or any(not item.get("ref") for item in sequence)):
            errors.append(f"{oid}: no-write sequence must be before_read, action, completion, after_read")
        elif any(item["ref"] not in refs for item in sequence):
            errors.append(f"{oid}: no-write sequence refs must name existing checks or steps")
        positive = value.get("positive_control_ref")
        if not positive or positive not in refs:
            errors.append(f"{oid}: no-write observation needs a separate mutating positive control")
        elif isinstance(sequence, list) and positive in {item.get("ref") for item in sequence
                if isinstance(item, dict)}:
            errors.append(f"{oid}: mutating positive control must be separate from the no-write sequence")
        reachability = value.get("reachability_assertion_ref")
        if not reachability or reachability not in refs:
            errors.append(f"{oid}: no-write observation needs a path reachability assertion")
    if "no_leak" in kinds:
        payload = value.get("payload_assertion_ref")
        if not payload or payload not in refs:
            errors.append(f"{oid}: no-leak observation must inspect the denied response payload")
    if has_gap and (any(link.get("assessment") == "sufficient" for link in obligation.get("coverage_links") or []
                        if isinstance(link, dict)) or
                    bool(obligation.get("parts")) and all(part.get("status") == "sufficient"
                        for part in obligation.get("parts") or [] if isinstance(part, dict))):
        errors.append(f"{oid}: gap surface cannot be represented as sufficient coverage")
    return errors
