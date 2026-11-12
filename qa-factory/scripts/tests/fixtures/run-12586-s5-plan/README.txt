s5-plan.json: the REAL output of the S5 plan author of run TP1-12586 (package 0.10.3), copied byte for byte (nothing replaced,
nothing trimmed) from
  testproject1-dev-010/testproject1-sdk/test-harness/qa-factory/artifacts/TP1-12586/work/s5-plan.json
on 2026-10-28 (the file there was last written 2026-10-28 13:10).

Why it is here: the join key of the test-grouping change (t-1502) is that the producer's real output passes through its
consumers (s5_plan.check_report / grouping_hints / render_slice / --check, s5_precheck.plan_result, brief_pack), not only a
hand-built input. Shape of the file: 10 tests, one case each; seven of them (TC-001, 002, 004, 005, 006, 007, 011) are
`api` tests in testproject1_test_harness/tests/integrations/project/test_integration_project_change.py with shape new/parameterize;
TC-003 extends a test in another file; TC-008 and TC-009 are `e2e-ui` extends in one UI file. No test has `uses`, `params`,
`deviation` or `apart_reason`.

Known gap (queued, not designed here): a consolidated scenario for NEW cases with a different set of Thens needs
`consolidates` to name tests that do not exist yet (spec t-1502 F-7).
