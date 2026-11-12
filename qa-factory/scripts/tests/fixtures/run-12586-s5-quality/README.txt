Fixture for test_quality_demand.py (HF4-10): the S5 quality demand of live run TP1-12586.

Source (the stand, read only): testproject1-dev-010/testproject1-sdk/test-harness/qa-factory/
  artifacts/TP1-12586/work/windows/S5-qa-code-critic-2.json, -3.json, -4.json   -> project/qa-factory/artifacts/TP1-12586/work/windows/
  artifacts/TP1-12586/state/controller.json  (only required_quality_checks, source_revision, coverage_contract_version) -> controller-excerpt.json
  artifacts/TP1-12586/work/automation-manifest.json  (obligation_bindings, obligation_id OB-1)                           -> binding-OB-1.json
  state/readiness.json  (capability names with status and owner only)                                                       -> project/qa-factory/state/readiness.json

Replaced: every Cyrillic character in window 4 (66 characters, in the test names / texts) became the Latin letter x, same length
(FR-30, selftest --lang). Ids, hashes and the structure of every record are as recorded. Windows 2 and 3 hold no Cyrillic.
project/qa-factory/config.json is a stub ({"schema_version": 1}): it only marks the project for runtime_paths.nearest_project.
Not copied: secrets, the rest of controller.json, thinking signatures, api-request lines.

The recorded binding OB-1 names a probe receipt of a later round than the window; the test points probe_receipt_ref at the
window's own probe of the first instance (own_probe in test_quality_demand.py) so the binding is false for the quality branch only.
