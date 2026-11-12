# Round 2 - qa-case-critic S4-qa-case-critic-2 - CART-1

Verdict: approve_with_concerns

Scope: plan rows TS-5, TS-6, TS-8, TS-9. Pinned versions read: TC_005 cv_3767896d512c623e0b59, TC_006 cv_3736b2c697846070acdd, TC_008 cv_ce42982f1616cbc645f9 (unchanged since round 1), TC_009 cv_2b3ebd621560f9547704. Code read: MyBooks/src/lib/cartOwner.ts:6-8. Proof kind for every sensitivity record: design_analysis (no probe executed). confidence: medium (tracker unreachable; oracle is Q1 current code).

## Roll-call

| plan row | case | reviewed | verdict | note | fix |
|---|---|---|---|---|---|
| TS-5 | CART-1_TC_005 | yes | approve | F-1 resolved: JU carries G1's cookie plus U's session, cookie equality asserted before the read; a user-owner query also matching sessionId returns B x2 and fails Then 2 (OB-5, defect site ownerWhere, design_analysis). Control and G2 check intact. | |
| TS-6 | CART-1_TC_006 | yes | approve | C-1..C-3 resolved: PC-2 TEST_SECRET env check, B3 starts at 10 then lowered to 3, Then 5 lists exact rows. Sum, replace, no-cap and no-drop defects each fail a named partition (OB-6, design_analysis). | |
| TS-8 | CART-1_TC_008 | yes | approve | Unchanged from round 1 approval: before/after read, mutating positive control, quantity 7 within stock; missing owner check on PUT/DELETE fails Then 1-3 (OB-8, design_analysis). | |
| TS-9 | CART-1_TC_009 | yes | approve_with_concerns | Round 1 C-1, C-3, C-4 resolved (error/code shape, B1 named, paths pinned, PC-3). Open concern: PC-1 stand_account user is checked only for credential keys; "verified" is assumed in prose and left to S5, so a non-verified seed user fails POST /api/orders at S5, not at the preflight. Four partitions share one cart, accepted with named P- ids. Seeded defect (order not clearing cart, quote not reading cart) fails Then 5 / Then 2 (OB-9, design_analysis). | S5 automator: confirm the seed user is verified before the first run, or create a verified user in the case; no case text change required. |

## Dimension scores

| case | 1 coverage | 2 atomicity | 3 clarity | 4 edge | 5 negative | 6 trace | 7 completeness | 7b contradicts_source | 8 seed defect |
|---|---|---|---|---|---|---|---|---|---|
| TC_005 | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| TC_006 | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| TC_008 | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| TC_009 | pass | concern | concern | pass | pass | pass | pass | pass | pass |

## Gate A questions carried

- Q1 (current code as oracle) applies to all four rows; TC_009 asserts status classes only, so no imported oracle. No source contradiction found.

Round count: 2 of 2.

# Round 1 - qa-case-critic S4-qa-case-critic-1 - CART-1

Verdict: reject

Scope: plan rows TS-5, TS-6, TS-8, TS-9 (dispatch S4-qa-case-critic-1). Pinned versions read: TC_005 cv_e4ffb26106421321c1a6, TC_006 cv_1046d3cf7f7a7093f601, TC_008 cv_ce42982f1616cbc645f9, TC_009 cv_a9ed3ec0883c46ec8f19. Code read: MyBooks/src/lib/cartOwner.ts. Proof kind for all sensitivity records: design_analysis (no probe executed). confidence: medium (tracker and Jira unreachable; oracle is Q1 current code).

## Roll-call

| plan row | case | reviewed | verdict | note | fix |
|---|---|---|---|---|---|
| TS-5 | CART-1_TC_005 | yes | reject | F-1 seed-the-defect fails: U's jar never carries G1's guest cookie, so a user-owner query that also matches sessionId (defect at ownerWhere, cartOwner.ts:7) is not exercised; Then 2 would pass. | Add a step: U signs in in a jar that ALSO holds G1's bookstore_session_id cookie (the real "guest then sign-in" browser), then GET /api/cart and assert no row for B. |
| TS-6 | CART-1_TC_006 | yes | approve_with_concerns | C-1 test seed endpoint and its secret are needed (stock lowering) but PC-1 only says case_seeds; add an env/service precondition for the secret. C-2 Given says B3 stock 3 yet guest added x6; state B3 starts at stock 10, then is lowered to 3. C-3 Then 5 "no other rows" is unbounded; list the expected rows exactly (B1,B2,B3,B5). | Add PC-2 kind env check {"env": "<seed secret var name>"}; reword Given/Then 5 as above. |
| TS-8 | CART-1_TC_008 | yes | approve | Before/after read, mutating positive control and reachability present; seeded defect (missing owner check on PUT/DELETE) changes row, Then 1-3 fail. | |
| TS-9 | CART-1_TC_009 | yes | approve_with_concerns | C-1 Then 1 and 3 accept any 4xx: a wrong path, 401 or validation error satisfies them; require the error/code shape for Then 1 and assert Then 3 body names the insufficient item, or state oracle_unknown. C-2 PC-1 stand_account "user" must be a real credentials_by_role key and verified; unchecked. C-3 stock lowering needs the seed secret (no precondition). C-4 quote/order paths deferred to S5 ("automator binds"), so Given is not executable as written. | Pin paths from spec.ts:576 in When; add env precondition for the seed secret. |

## Dimension scores

| case | 1 coverage | 2 atomicity | 3 clarity | 4 edge | 5 negative | 6 trace | 7 completeness | 7b contradicts_source | 8 seed defect |
|---|---|---|---|---|---|---|---|---|---|
| TC_005 | pass | pass | pass | pass | concern | pass | pass | pass | fail |
| TC_006 | pass | pass | concern | pass | pass | pass | pass | pass | pass |
| TC_008 | pass | pass | pass | pass | pass | pass | pass | pass | pass |
| TC_009 | pass | concern | concern | pass | concern | pass | pass | pass | concern |

## Findings

- F-1 (TC_005, Given/When/Then 2, dimension 8, blocking): obligation OB-5, declared defect permission @ ownerWhere. Planted defect: signed-in owner query also matches the request's sessionId. Case result: U's jar has no guest cookie, so U sees nothing foreign and Then 2 passes. Expected: a signed-in request that carries G1's cookie returns no G1 rows (R-7: "a user never sees guest rows until merge"). Sensitivity record: proof_kind design_analysis, expected failure of Then 2 after the fix, no observed_failure_ref. The control (Then 1) and G2 check (Then 3) are sound.
- TC_009 atomicity concern: the case holds four scenarios (empty, quote, over-stock, order+clear); acceptable only because they share one cart; keep partitions named P-.

## Gate A questions carried

- Q1 (current code as oracle) applies to all four rows; Then values rest on R-7/R-8/R-12/R-15 derived from code, AUTH.md:8 and spec.ts summaries. No source contradiction found (matrix silent or ok); TC_009 asserts status classes only, so no imported oracle.

Round count: 1 of 2.
