# Critic findings - S5-qa-code-critic-3 (CART-1_TC_005..008)

Roll-call: TC_005 -> cart-isolation.spec.ts (OB-5, cv_3767896d512c623e0b59); TC_006 -> cart-merge.spec.ts (OB-6, cv_3736b2c697846070acdd); TC_007 -> cart-update-delete.spec.ts (OB-7, cv_2d9d27c7521bc3c4edcf); TC_008 -> cart-ownership.spec.ts (OB-8, cv_ce42982f1616cbc645f9). All Thens asserted; values from the cases.
Pinned case copies in work/test-cases/cart match the pinned versions (sha256 equal for all four).

- F-1 [tooling] probe_by_code refused all four instances (no selector_args / report_test_id; selectors.verified absent). Probe not run: unverified, sensitivity_proof_missing_reason. Conductor takes the person's word.
- F-2 [tooling] precheck C3 findings are a title-spelling mismatch (plan "CART-1_TC_005 ..." vs title with tags "@api @regression ..."), plus PR-2 plan_remarks row missing. Not a test defect.
- F-3 [mechanical] cart-update-delete.spec.ts:9 and cart-ownership.spec.ts:10 destructure `[row]` / `[rowA]` before any assert; an empty read raises without naming a Then. Assert the count first.
- F-4 [note] obligation_hash values appear only in the manifest; no independent source in the artifacts to recompute them: not verified.
- Expectation change (TC_005): legitimate_correction. No assertion changed; fixture jar fix (empty storageState) removes shared guest session between G1 and G2.
