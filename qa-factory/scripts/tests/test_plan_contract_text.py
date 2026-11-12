#!/usr/bin/env python3
"""The plan contract names the fields the plan validator checks (FR-38, FR-11, t-206).

The S3 strategist has no shell (FR-56), so it cannot run `planning_contract.py`; it learns what the
validator refuses on from `references/artifact-contract-plan.md` and nothing else. cmp2 found the
file silent on `coverage_delta` and `observation_contract`. This file holds the section down:

  * the heading `## Fields the plan validator checks (coverage-observation-v1)` exists and sits
    under a roles marker that sends it to the strategist (rendered in memory, as `contract_slices`
    does, so the check does not depend on the generated slice being fresh);
  * every key and every closed-vocabulary word the validators hold is in the section, the
    vocabularies being read from the validators' own constants, never retyped here;
  * the JSON example in the section satisfies the real validators;
  * the file stays inside the 12,000-byte reference cap (builder-rules item 5, `wc -c`).

The keys are quoted verbatim from the DoD of t-206, written before the first run. The last block is
the NEGATIVE CONTROL: a key in no text is reported absent, and a copy of the contract with
`coverage_delta` removed fails the same check.

Run on its own: `python -B scripts/tests/test_plan_contract_text.py`.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract_slices as CS  # noqa: E402
import observation_contract as OC  # noqa: E402
import planning_contract as PC  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT
CONTRACT = PLUGIN / "references" / "artifact-contract-plan.md"
HEADING = "## Fields the plan validator checks (coverage-observation-v1)"
CAP_BYTES = 12_000   # selftest.py REFERENCE_MD_MAX_BYTES

# The keys, verbatim from the DoD of t-206 (rule 11, doc witness: chosen BEFORE the run).
KEYS = ["coverage_delta", "observation_contract", "baseline_kind", "planned_instance_ids",
        "replace_redundant", "claim_kind", "oracle_ref", "assertion_ref", "positive_control_ref",
        "reachability_assertion_ref", "before_read"]


def flat(text: str) -> str:
    """One line per text: a key broken across two lines of a wrapped paragraph is still in it."""
    return " ".join(text.split())


def present(key: str, text: str) -> bool:
    """The one presence predicate: the real checks and the negative control both go through it."""
    return key in flat(text)


def section_of(text: str) -> str:
    """The text from the heading to the end of the file (the section is the file's last)."""
    at = text.find(HEADING)
    return text[at:] if at >= 0 else ""


def main() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    section = section_of(text)
    check("the contract has the section heading", bool(section), HEADING)

    # --- the DoD's keys ----------------------------------------------------------------------------
    for key in KEYS:
        check(f"the section holds `{key}`", present(key, section))

    # --- every closed vocabulary word, read from the validator's own constant ----------------------
    for word in sorted(PC.DELTA_DISPOSITIONS):
        check(f"the section holds the delta disposition `{word}`", present(word, section))
    for word in ("initial", "accepted"):
        check(f"the section holds the baseline kind `{word}`", present(word, section))
    for word in sorted(OC.CLAIM_KINDS):
        check(f"the section holds the claim kind `{word}`", present(word, section))
    for word in sorted(OC.SURFACE_STATUSES):
        check(f"the section holds the surface status `{word}`", present(word, section))
    for word in OC.SEQUENCE_PHASES:
        check(f"the section holds the phase `{word}`", present(word, section))
    check("the four phases are written in the validator's order",
          present(", ".join(f"`{w}`" for w in OC.SEQUENCE_PHASES), section))
    for word in ("logical_cases_before", "logical_cases_after", "executable_instances_before",
                 "executable_instances_after", "initial_scope_rationale",
                 "accepted_scope_expansion_ref", "existing_case_refs", "gap_reason",
                 "payload_assertion_ref", "completion_ref", "independent_expectations",
                 "source_conflicts", "planned_check_refs", "coverage-observation-v1"):
        check(f"the section holds `{word}`", present(word, section))

    # --- the rules the validator refuses on, as sentences ------------------------------------------
    check("it says `executable_instances_after` equals the number of planned ids",
          present("`executable_instances_after` equals their number", section))
    check("it says an assertion_ref must name an existing check of the obligation",
          present("names an existing check of this obligation", section))

    # --- the section reaches the strategist (rendered in memory, as the slice generator does) ------
    rendered = CS.render("artifact-contract-plan.md", "qa-test-strategist", text)
    check_in("the strategist's slice would carry the section", HEADING, rendered)
    check("and the requirements tester's would not",
          HEADING not in CS.render("artifact-contract-plan.md", "qa-requirements-tester", text))

    # --- TR2-8 (B-9): the strategist is told the row key BEFORE the work, in its slice, and the example carries it ------
    check("the strategist's slice carries the row key and its value", "carries `schema_version: 2`" in flat(rendered))
    on_disk = (PLUGIN / "references" / "slices" / "qa-test-strategist" / "artifact-contract-plan.md").read_text(encoding="utf-8")
    check("the committed slice carries it too (the generator was run)", "carries `schema_version: 2`" in flat(on_disk))
    check("control: a copy of the source without the phrase does not carry it",
          "carries `schema_version: 2`" not in flat(CS.render("artifact-contract-plan.md", "qa-test-strategist",
                                                              text.replace("schema_version: 2", "schema_version"))))

    # --- the example in the section satisfies the real validators ----------------------------------
    blocks = re.findall(r"```json\n(.*?)\n```", section, re.S)
    check_eq("the section carries one JSON example", len(blocks), 1)
    if blocks:
        example = json.loads(blocks[0])
        check("the example is at most 25 lines", len(blocks[0].splitlines()) <= 25,
              str(len(blocks[0].splitlines())))
        check_eq("TR2-8: the example row carries `schema_version: 2` (the number)", example.get("schema_version"), 2)
        check_eq("the example's delta passes planning_contract", PC._validate_coverage_delta(example), [])
        for ob in example["coverage_obligations"]:
            check_eq(f"the example's obligation {ob['obligation_id']} passes observation_contract",
                     OC.validate_observation_contract(ob, required=True), [])

    # --- the file stays under the cap ----------------------------------------------------------------
    size = len(text.encode("utf-8"))
    check(f"the contract is within {CAP_BYTES} bytes ({size} B)", size <= CAP_BYTES)

    # --- NEGATIVE CONTROL: a check that cannot fail is indistinguishable from a broken one ---------
    absent_key = "zz-not-in-the-contract-zz"
    check(f"control: `{absent_key}` is reported absent from the contract", not present(absent_key, text))
    tmp = harness.temp_dir("qa-plan-contract-text-")
    try:
        check("control: the key to remove is in the contract to begin with", present("coverage_delta", text))
        stripped = tmp / "artifact-contract-plan.md"
        stripped.write_text(text.replace("coverage_delta", ""), encoding="utf-8")
        check("control: a copy of the contract without `coverage_delta` FAILS the same check",
              not present("coverage_delta", section_of(stripped.read_text(encoding="utf-8"))))
        check("control: and the real contract passes it", present("coverage_delta", section))
        broken = dict(example, coverage_delta={**example["coverage_delta"], "planned_instance_ids": ["x", "y"]}) \
            if blocks else {}
        check("control: an example with one instance id too many FAILS the real delta validator",
              bool(PC._validate_coverage_delta(broken)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    harness.finish("test_plan_contract_text")


if __name__ == "__main__":
    main()
