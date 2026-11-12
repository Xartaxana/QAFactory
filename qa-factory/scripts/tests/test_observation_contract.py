"""observation_contract.validate_observation_contract: typed design-time observation
contracts for coverage obligations. Per the module's own docstring, this proves shape
and reference joins only — never whether the oracle is semantically right. Builds one
minimal valid obligation, then breaks exactly one field at a time to check the refused
shape names the right thing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import observation_contract as OC  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check_eq, check_in, finish  # noqa: E402


def valid():
    return {
        "obligation_id": "OB-1",
        "requirement_refs": [{"ref": "R-2", "revision": "v1"}],
        "planned_check_refs": ["TC-1"],
        "observation_contract": {
            "claim_kind": ["ordinary"],
            "oracle_ref": {"ref": "R-2", "revision": "v1"},
            "surfaces": [{"id": "S-1", "boundary": "response body",
                          "status": "observed", "assertion_ref": "TC-1"}],
            "controls": ["TC-1"],
            "completion_ref": "TC-1",
            "independent_expectations": [],
            "source_conflicts": [],
        },
    }


base = valid()
check_eq("a minimal well-formed contract has no errors", OC.validate_observation_contract(base), [])

check_eq("observation_contract absent and not required -> no error",
         OC.validate_observation_contract({"obligation_id": "OB-2"}), [])
check_in("observation_contract absent and required -> named as required",
         "observation_contract required", OC.validate_observation_contract({"obligation_id": "OB-2"}, required=True))
check_in("observation_contract that is not an object is refused",
         "must be an object",
         OC.validate_observation_contract({"obligation_id": "OB-3", "observation_contract": "text"}))

bad_kind = valid()
bad_kind["observation_contract"]["claim_kind"] = ["not-a-real-kind"]
check_in("claim_kind outside the closed vocabulary is refused",
         "closed vocabulary", OC.validate_observation_contract(bad_kind))

bad_oracle = valid()
bad_oracle["observation_contract"]["oracle_ref"] = {"ref": "R-2"}
check_in("oracle_ref missing its revision is refused",
         "must bind ref and revision", OC.validate_observation_contract(bad_oracle))

bad_surfaces = valid()
bad_surfaces["observation_contract"]["surfaces"] = []
check_in("an empty surfaces list is refused",
         "surfaces must be nonempty", OC.validate_observation_contract(bad_surfaces))

gap_no_reason = valid()
gap_no_reason["observation_contract"]["surfaces"] = [{"id": "S-1", "boundary": "x", "status": "gap"}]
check_in("a gap surface with no gap_reason is refused",
         "gap surface needs gap_reason", OC.validate_observation_contract(gap_no_reason))

gap_marked_sufficient = valid()
gap_marked_sufficient["observation_contract"]["surfaces"] = [
    {"id": "S-1", "boundary": "x", "status": "gap", "gap_reason": "no stand for this"}]
gap_marked_sufficient["coverage_links"] = [{"assessment": "sufficient"}]
check_in("a gap surface cannot be laundered into sufficient coverage",
         "cannot be represented as sufficient", OC.validate_observation_contract(gap_marked_sufficient))

bad_controls = valid()
bad_controls["observation_contract"]["controls"] = ["NOWHERE"]
check_in("controls must reference a real check or step",
         "must reference existing checks or steps", OC.validate_observation_contract(bad_controls))

bad_completion = valid()
bad_completion["observation_contract"]["completion_ref"] = ""
check_in("a missing completion_ref is refused",
         "completion_ref must reference", OC.validate_observation_contract(bad_completion))

parity = valid()
parity["observation_contract"]["claim_kind"] = ["response_parity"]
check_in("response_parity with fewer than 2 independent expectations is refused",
         "response parity needs independent expectations", OC.validate_observation_contract(parity))

parity_dup = valid()
parity_dup["observation_contract"]["claim_kind"] = ["response_parity"]
parity_dup["observation_contract"]["independent_expectations"] = [
    {"partition_ref": "owner", "expected_ref": "E-1", "attribution_assertion_ref": "TC-1"},
    {"partition_ref": "owner", "expected_ref": "E-2", "attribution_assertion_ref": "TC-1"},
]
check_in("response_parity partitions must be distinct, not duplicated",
         "partition refs must be unique", OC.validate_observation_contract(parity_dup))

no_leak = valid()
no_leak["observation_contract"]["claim_kind"] = ["no_leak"]
check_in("a no_leak claim needs a payload_assertion_ref",
         "must inspect the denied response payload", OC.validate_observation_contract(no_leak))

no_write = valid()
no_write["observation_contract"]["claim_kind"] = ["state_unchanged"]
check_in("a no-write claim needs the four-phase sequence",
         "no-write sequence must be before_read, action, completion, after_read",
         OC.validate_observation_contract(no_write))

no_write_ok = valid()
no_write_ok["planned_check_refs"] = ["TC-1", "TC-2", "TC-3"]
no_write_ok["observation_contract"]["claim_kind"] = ["state_unchanged"]
no_write_ok["observation_contract"]["controls"] = ["TC-1", "TC-2"]
no_write_ok["observation_contract"]["sequence"] = [
    {"phase": "before_read", "ref": "TC-1"}, {"phase": "action", "ref": "TC-2"},
    {"phase": "completion", "ref": "TC-2"}, {"phase": "after_read", "ref": "TC-1"}]
no_write_ok["observation_contract"]["positive_control_ref"] = "TC-3"
no_write_ok["observation_contract"]["reachability_assertion_ref"] = "TC-1"
errs = OC.validate_observation_contract(no_write_ok)
check_eq("a fully-formed no-write contract (sequence, positive control, reachability) is clean", errs, [])

no_write_same_control = valid()
no_write_same_control["observation_contract"]["claim_kind"] = ["state_unchanged"]
no_write_same_control["observation_contract"]["sequence"] = [
    {"phase": "before_read", "ref": "TC-1"}, {"phase": "action", "ref": "TC-1"},
    {"phase": "completion", "ref": "TC-1"}, {"phase": "after_read", "ref": "TC-1"}]
no_write_same_control["observation_contract"]["positive_control_ref"] = "TC-1"
no_write_same_control["observation_contract"]["reachability_assertion_ref"] = "TC-1"
check_in("the mutating positive control must be a step OUTSIDE the no-write sequence itself",
         "must be separate from the no-write sequence",
         OC.validate_observation_contract(no_write_same_control))

finish("test_observation_contract")
