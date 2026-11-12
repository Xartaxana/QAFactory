# Critic findings - S5-qa-code-critic-2 (CART-1_TC_001..004)

## Static review (all 4 spec files, cartApi.ts, cartApi.fixture.ts)
Oracles: traceability --oracles gives every Then of TC_001..004 as settled (R-3..R-6); no invented_expectation.
Layering good: one CartApi/CatalogAdminApi client and one fixture reused by all specs, no waits, own books created and deleted, fresh cookie jar per test, read-back through GET /api/cart (independent of POST response). PR-1 applied (TC_004 parameterized per partition). PR-2 met (helpers in core).

Roll-call:
- CART-1_TC_001 -> add-rejections.spec.ts (Then 1-3)
- CART-1_TC_002 -> add-stock-limit.spec.ts (Then 1-4)
- CART-1_TC_003 -> add-accumulate.spec.ts (Then 1-2)
- CART-1_TC_004 -> add-boundaries.spec.ts, 9 parameter instances (Then 1 for min/max; Then 2/3/4 for 7 rejections)

Notes (no cause, not findings):
- TC_002 Then 4 asserts the same value as Then 3 (quantity 5 == stock 5); the Then is satisfied but adds nothing over Then 3. Not stricter than R-4.
- TC_004 rejection body asserts only that error/code are strings, not specific codes: matches the Then.

## Findings
- F-1 cause: tooling (not blocking, nobody's round). probe_by_code.py refused for all instances: TS instances carry no `selector_args` / `report_test_id` in the manifest and profile web does not say selectors.verified. Detail: work/probes not written. Needs the author to record them via manifest_put.py (factory data gap) or the person to confirm selectors.verified.
- F-2 cause: tooling. TC_004 tests are declared inside `for` loops with template-literal titles; the typescript `test_declaration` detector did not match the title as rendered (`... accepted [P-qty-min]`). Probe cannot locate the declaration. Would settle: detector row for template titles, or explicit test-per-parameter.
- F-3 cause: mechanical/author form. s5_precheck lists C3 deviations: manifest instance ids carry the "@api @regression" tag prefix while the plan names the function without tags, and plan_remarks PR-1/PR-2 rows and deviation rows are not in the author's form. Not judged here (checked by code).

## Not verified
All 12 instances: no live probe receipt (could not verify; tooling). Author green receipt: window_record notes "run recorded no per-test identity".
