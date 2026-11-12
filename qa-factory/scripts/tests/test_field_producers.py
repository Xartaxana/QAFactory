#!/usr/bin/env python3
"""FR-11: a field a contract requires has something that can produce it, or the gap is declared.

`not_verified:missing_sensitivity_proof` stood on nine instances of TP1-13797 and held
`delivery_ready: no` on a run where every case was green: the typed receipt comes from
`red_sandbox.py --probe` while the code critic is permitted `probe_by_code.py`. The rule that
came out of it is this one, and this is its systematic form — every required field of every
handoff contract, walked.

The class is not "a field holding a path": a role knows the path of the artifact it wrote. It is
a field whose value can only come from RUNNING something — a receipt, a content hash, a
provenance record, a count code computes. For each of those the producer is either a deriver in
`handoff_check` (code fills the field), or a row in `references/field-producers.json`. A row with
an empty `producer` is a declared gap with its reason, printed rather than hidden (FR-41).

Writing this walk found two fields where the deriver existed and was wired to two of the three
paths that ask for it (FR-17): `runtime.provenance` and `rounds[].verify.witness`.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import handoff_check as HC  # noqa: E402
import null_outcomes as NO  # noqa: E402

PRODUCERS = harness.PLUGIN_ROOT / "references" / "field-producers.json"
# Which fields need a tool - "a value no role can write out of its own prose" - is chosen by
# `null_outcomes.tool_fields` (t-305 N0): the null-outcome detector walks the same selection, so it is ONE
# copy, held there, and this walk only asks what produces each field it names.
SCRIPT_RE = re.compile(r"([a-z][a-z0-9_]*\.py)")


def derived_paths() -> set:
    """The fields code fills, read out of handoff_check rather than copied."""
    return set(HC.DERIVERS) | set(HC.LIST_DERIVERS)


def declared() -> list:
    rows = json.loads(PRODUCERS.read_text(encoding="utf-8")).get("fields") or []
    return [row for row in rows if isinstance(row, dict)]


def row_for(field: str, rows: list) -> dict | None:
    leaf = field.rsplit(".", 1)[-1]
    for row in rows:
        name = str(row.get("field") or "")
        if name == field or (name.endswith(".*") and field.startswith(name[:-1])):
            return row
        if name.split(" ")[0] == field or name.split(" ")[0].rsplit(".", 1)[-1] == leaf:
            return row
    return None


def walk() -> tuple:
    """(fields needing a tool, the ones with no producer at all) across every contract."""
    rows, derived = declared(), derived_paths()
    needs, gaps = [], []
    for contract, role, path, hint in NO.tool_fields():
        text = (harness.PLUGIN_ROOT / "handoffs" / f"{contract}.yaml").read_text(encoding="utf-8")
        leaf = path.rsplit(".", 1)[-1]
        producer = ""
        if path in derived or leaf in HC.BY_LEAF:
            producer = "handoff_check --fix"
        else:
            named = SCRIPT_RE.search(hint) or SCRIPT_RE.search(
                next((ln for ln in text.splitlines()
                      if ln.strip().startswith(leaf.rstrip("[]") + ":")), ""))
            if named:
                producer = named.group(1)
            else:
                row = row_for(path, rows)
                producer = str((row or {}).get("producer") or "")
                if row is None:
                    gaps.append((contract, role, path, hint))
        needs.append((contract, role, path, producer))
    return needs, gaps


def every_required_field_has_a_producer_or_a_declared_gap() -> None:
    needs, undeclared = walk()
    # SC1-2 removed five claims that nothing read (33 -> 28, then 27: RN1-2 dropped the S3 form revision field)
    check("the walk reaches every contract's fields", len(needs) >= 27, str(len(needs)))
    check_eq("no required field needing a tool is left unaccounted for",
             [f"{c}:{p}" for c, _r, p, _prod in undeclared], [])
    by_code = [row for row in needs if row[3] == "handoff_check --fix"]
    check(f"code fills most of them ({len(by_code)} of {len(needs)})",
          len(by_code) >= 17, str(len(by_code)))
    # Every producer that is a script must exist, and must not be one of the three commands the
    # guard closes to every role (FR-2: a door the refused party may not open is not an answer).
    for contract, role, path, producer in needs:
        for script in SCRIPT_RE.findall(producer):
            check(f"{path}: {script} exists", (harness.SCRIPTS / script).is_file(), contract)
    declared_rows = declared()
    for row in declared_rows:
        check(f"{row.get('field')}: the row says why", len(str(row.get("why") or "")) > 30,
              str(row.get("why"))[:60])
    # The declared gap is closed (D-0010, D-0012): the sensitivity receipt has a producer, and it
    # is the two probes, each of which exists. No row of the file is a declared gap any more.
    gap = [row for row in declared_rows if not str(row.get("producer") or "").strip()]
    check_eq("no required field is left declared as having no producer", len(gap), 0)
    sensitivity = [row for row in declared_rows if "sensitivity_proof" in str(row.get("field"))]
    check_eq("the sensitivity receipt is still a row of the file", len(sensitivity), 1)
    producer = str(sensitivity[0].get("producer") or "")
    for script in ("probe_by_code.py", "red_sandbox.py"):
        check_in(f"its producer names {script}", script, producer)
        check(f"and {script} exists in scripts/", (harness.SCRIPTS / script).is_file(), script)
    check_in("the live level is the default one", "the check is live", producer)
    check_in("the row says what reads the receipt", "semantic_sensitivity", sensitivity[0]["why"])
    check_in("and which decisions closed the gap", "D-0010", sensitivity[0]["why"])


def the_two_paths_this_walk_wired() -> None:
    """A deriver wired into two of the three paths that ask for it is not adopted (FR-17)."""
    derived = derived_paths()
    for path in ("artifacts.runtime_provenance", "probes.runtime_provenance", "runtime.provenance"):
        check(f"{path} is filled by code", path in derived, str(sorted(derived))[:120])
    for path in ("artifacts.run_witness", "run.witness", "rounds[].verify.witness"):
        check(f"{path} is filled by code", path in derived, str(sorted(derived))[:120])
    check_eq("and the same deriver answers each family",
             (HC.DERIVERS["runtime.provenance"] is HC.DERIVERS["artifacts.runtime_provenance"],
              HC.DERIVERS["rounds[].verify.witness"] is HC.DERIVERS["run.witness"]), (True, True))


def the_sensitivity_gap_is_reported_not_hidden() -> None:
    """The window check still refuses without the receipt — the gap is declared, not waived."""
    import acceptance
    window = {"schema_version": 2, "required_quality_checks": [], "input_hash": "h1",
              "instances": [
                  {"instance_id": "test_x[a]", "case": "TC-1", "status": "green",
                   "input_hash": "h1",
                   "evidence_refs": [{"path": "work/evidence/x.json", "sha256": "0" * 64}],
                   "probe": {}}]}
    gaps = acceptance.validate_window(window, harness.PLUGIN_ROOT)
    check("an instance with no probe receipt is still refused", bool(gaps), str(gaps))


def main() -> None:
    every_required_field_has_a_producer_or_a_declared_gap()
    the_two_paths_this_walk_wired()
    the_sensitivity_gap_is_reported_not_hidden()
    finish("test_field_producers")


if __name__ == "__main__":
    main()
