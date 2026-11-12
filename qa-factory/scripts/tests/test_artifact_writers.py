#!/usr/bin/env python3
"""One artifact, one writer - and the factory says out loud whose each file is.

The defect this holds against is real and it was silent: the ticket probe wrote its receipt
into `source-inventory.json`, the file it was adding to, and erased the sources the scout had
already collected (TP1-13797, F8). Nothing refused it, because nothing anywhere stated who
owns that file.

A static "who writes this path" scan over the scripts is a false-positive machine - it flags
every script that reads the file near a write of its own - so what is checked here is the
STATEMENT: every artifact a stage declares has a named owner, every owner exists, and the one
guard that came out of F8 is still in the code.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, check, check_eq, check_in, finish  # noqa: E402

OWNERS = json.loads((PLUGIN_ROOT / "references" / "artifact-writers.json").read_text(encoding="utf-8"))
STAGES = json.loads((PLUGIN_ROOT / "references" / "stages.json").read_text(encoding="utf-8"))["stages"]


def every_declared_artifact_has_an_owner() -> None:
    declared = []
    for stage in STAGES:
        declared += [out for out in stage.get("outputs", [])]
    missing = sorted({out for out in declared if out not in OWNERS["artifacts"]})
    check_eq("every artifact stages.json declares names its writer", missing, [])
    # The map is wider than `stages.json` on purpose: a stage declares what it must produce,
    # while files like the source inventory, the pins and the handoff forms are produced all
    # the same and were exactly the ones nobody owned. What it may not do is invent a file.
    extra = sorted(set(OWNERS["artifacts"]) - set(declared))
    sources = list((PLUGIN_ROOT / "scripts").glob("*.py")) + list((PLUGIN_ROOT / "references").glob("*.md"))
    haystack = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in sources)
    invented = [name for name in extra if name.rstrip("/").split("/")[-1] not in haystack]
    check_eq("every artifact the map adds beyond stages.json is a real one", invented, [])
    check("and the map covers the files that had no owner at all",
          {"work/source-inventory.json", "state/story-case-links.json", "work/handoffs/"} <= set(OWNERS["artifacts"]))


def every_owner_exists() -> None:
    roles = {p.stem for p in (PLUGIN_ROOT / "agents").glob("qa-*.md")}
    for name, entry in OWNERS["artifacts"].items():
        writer = entry["writer"]
        if writer.endswith(".py"):
            ok = (PLUGIN_ROOT / "scripts" / writer).is_file()
        else:
            ok = writer.split()[0] in roles
        if not ok:
            check(f"{name}: the writer `{writer}` exists", False)
            return
        for extra in entry.get("machinery", []):
            if extra.endswith(".py") and not (PLUGIN_ROOT / "scripts" / extra).is_file():
                check(f"{name}: the machinery `{extra}` exists", False)
                return
    check("every named writer is a script of this plugin or a role of it", True)


def a_receipt_never_writes_into_another_roles_artifact() -> None:
    """F8 itself: the map says why the probe's receipt has its own file."""
    entry = OWNERS["artifacts"]["work/source-inventory.json"]
    check_in("the map says why, so the next writer reads it before repeating F8",
             "ticket-probe.json", entry["why"])


def the_handoff_form_has_one_owner_too() -> None:
    entry = OWNERS["artifacts"]["work/handoffs/"]
    check_eq("the form is created by code", entry["writer"], "handoff_init.py")
    check_in("and repaired by the check, not by a second author", "handoff_check.py",
             entry.get("machinery", []))


def the_claim_projector_is_machinery_of_the_register_not_a_second_author() -> None:
    """G1-13: the S3 planner has no Bash and is not the register's writer; code copies its claims in. The writer stays the one role."""
    register = OWNERS["artifacts"]["work/requirements-register.md"]
    check_eq("the register's writer is still the one role", register["writer"], "qa-requirements-tester (the role)")
    check_eq("...and claim_projector.py is its machinery", register.get("machinery"), ["claim_projector.py"])
    check("...no strategist word anywhere in the register's entry", "strategist" not in json.dumps(register).lower())
    check_eq("the readiness file declares question_register.py as machinery (an undeclared writer before G1-13)",
             OWNERS["artifacts"]["work/requirements-readiness.json"].get("machinery"), ["question_register.py"])


def the_triage_register_names_every_field_code_writes_on_a_reorder_row() -> None:
    """t-1556 F8: `s7_reorder.py` writes `carried_attempts`/`carried_by` (finish) AND `fix_result: fixed` (mark_fixed) on a `reorder`
    row; the registry's why and the run contract name both, so a reader of `fix_result` finds its second writer."""
    why = OWNERS["artifacts"]["work/triage.json"]["why"]
    for key in ("mark_fixed", "fix_result: fixed", "carried_attempts"):
        check_in(f"F8: the triage entry's why names {key!r}", key, why)
    contract = (PLUGIN_ROOT / "references" / "artifact-contract-run.md").read_text(encoding="utf-8")
    check_in("F8: the run contract says who writes fix_result on a reorder row", "`fix_result: fixed` on a `reorder` row", contract)
    check_in("F8: ...and what it means", "the critic approved the reorder", contract)


def main() -> None:
    the_triage_register_names_every_field_code_writes_on_a_reorder_row()
    the_claim_projector_is_machinery_of_the_register_not_a_second_author()
    every_declared_artifact_has_an_owner()
    every_owner_exists()
    a_receipt_never_writes_into_another_roles_artifact()
    the_handoff_form_has_one_owner_too()
    finish("test_artifact_writers")


if __name__ == "__main__":
    main()
