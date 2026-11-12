#!/usr/bin/env python3
"""t-069 (B-013 analogs): the role-read texts that still taught the old `TC-NNN` case id shape.

The comparison run is on a project whose case ids look like `TP1-13797_TC_001`
(config.case_id_form). t-068 moved the designer's brief, card, charter and the case-file section
of the contract to `<case id>` plus "in the form your brief names"; this file was the same sweep
over the remaining texts a role or a person reads. The role-text phrases of that sweep (S2, S6) moved to
design/role-rules.json; the absence scans of the `TC-NNN` shape (S1, S3, S4) were dropped by the TD-5 rules.

Keys kept here:
  S4  contract_slices reports nothing stale.
  S5  qa-automator's whole start load stays within the role_load threshold (role_load.static_load, tokens; the charter is
      one layer of it); the old 9000-byte per-file cap is retired (t-286, as K19 of
      test_case_id_form_texts.py), audit A22 bounds the whole start load.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import contract_slices  # noqa: E402
from content_size import content_bytes  # noqa: E402

PLUGIN = harness.PLUGIN_ROOT


def main() -> None:
    # S4
    check_eq("S4 contract_slices reports no stale or missing slice", contract_slices.findings(PLUGIN), [])

    # S5
    size = content_bytes(PLUGIN / "agents/qa-automator.md")
    import role_load
    load = role_load.static_load("qa-automator", plugin_root=PLUGIN)
    check(f"S5 qa-automator's whole start load is within the role_load threshold ({load['tokens']} <= {load['threshold_tokens']} tokens)",
          load["verdict"] == "within", str(load["tokens"]))
    check("S5 the charter is a layer of that load", next(l["bytes"] for l in load["layers"] if l["name"] == "charter") == size)

    data = Path(__file__).read_bytes()
    check("FR-29 this file carries no 0x07/0x08/0x0b/0x0c byte", not any(b in data for b in (7, 8, 11, 12)))
    check("FR-30 this file is ASCII", all(b < 128 for b in data))
    harness.finish("test_case_id_texts_sweep")


if __name__ == "__main__":
    main()
