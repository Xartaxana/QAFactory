# Round 2 - LOCAL-1, dispatch S4-qa-case-critic-2, area cart

Verdict: approve_with_concerns

10 of 10 reviewed. Pinned versions read: TC_005 cv_63c288a61eb8991687ce, TC_006 cv_53582e9fd2b6ca89c1d8, TC_007 cv_c9db7e5d30cd72586fd9, TC_009 cv_076607482889f76c8067, TC_011 cv_1034782aa1322af81825, TC_012 cv_449be24f68e1f4525921, TC_013 cv_a66f995d657e98e066b3, TC_014 cv_6a7b2dde6d47ad7bccd9, TC_015 cv_d5f8d0a9c43032173271, TC_016 cv_f3d9f6c5056b38862707.

The round-1 Q4 placeholders are gone: Thens now carry concrete values (201 / one line quantity 5; OUT_OF_STOCK / INSUFFICIENT_STOCK; badge 3/4; owner absence). Remaining concerns are about level notes and small wording only.

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-5 | LOCAL-1_TC_005 | yes | approve | Stock lowered after the add makes P-cap reachable; Thens 1-5 independent (GET /api/cart). Equal quantities remain a declared gap. |
| TS-6 | LOCAL-1_TC_006 | yes | approve_with_concerns | Then 1 can fail (success-only outcome). Then 2 "account header/menu" is a loose observable: name the element. lower level: impossible - the defect is what the login page shows after an intercepted merge call. |
| TS-7 | LOCAL-1_TC_007 | yes | approve | 201, 201, one line quantity 5 on an independent GET; planted "replace" or "two lines" defect fails Then 3. |
| TS-9 | LOCAL-1_TC_009 | yes | approve | Codes named, PUT named, independent GET after each refusal; stock and stock+1 present. |
| TS-11 | LOCAL-1_TC_011 | yes | approve | Absence Thens plus unchanged own line via an allowed same-account GET; refusal code deliberately not asserted (no source). |
| TS-12 | LOCAL-1_TC_012 | yes | approve | Now api only, declared gap for the page message; 400 INSUFFICIENT_STOCK per Q9 a, unchanged value on GET. |
| TS-13 | LOCAL-1_TC_013 | yes | approve_with_concerns | Values written (badge 3/4/2, price formulas), GET /api/cart as independent channel. lower level: impossible - badge and total are rendered by UI providers. Rounding of totals is a declared gap. |
| TS-14 | LOCAL-1_TC_014 | yes | approve_with_concerns | Account-cart-empty precondition and evidence policy added. lower level: api - merge rules are TC_005; kept for the UI sign-in walk (P19). Then 1-3 numbers (3/5, not 6/4) can fail. |
| TS-15 | LOCAL-1_TC_015 | yes | approve_with_concerns | R-8 step 4 and invariant Then 1 added. lower level: api - status rules are TC_007..TC_010; kept for double click and typed input (P19). Timing between tabs is nondeterministic (declared). |
| TS-16 | LOCAL-1_TC_016 | yes | approve_with_concerns | R-9 expected now written (guest holds neither A nor B; empty after cookies cleared). lower level: api - separation is TC_011; kept for cookies and two browsers (P19). |

## Merge candidates

| cases | verdict | reason |
|---|---|---|
| LOCAL-1_TC_005, LOCAL-1_TC_014 | keep | P19: api merge rules versus the UI sign-in walk |
| LOCAL-1_TC_006, LOCAL-1_TC_014 | keep | P19: automated fault injection (R-12) versus manual walk (R-4) |
| LOCAL-1_TC_007, LOCAL-1_TC_015 | keep | P19: api re-add versus manual real-input walk |
| LOCAL-1_TC_009, LOCAL-1_TC_015 | keep | P19: api stock codes versus manual sold-out walk |
| LOCAL-1_TC_011, LOCAL-1_TC_016 | keep | P19: api owner separation versus cookie and two-browser walk |

## Branch homes

| BN | home | reason |
|---|---|---|
| BN-5 | LOCAL-1_TC_005 | Then 1-3 |
| BN-6 | LOCAL-1_TC_005 | Then 5 |
| BN-8 | LOCAL-1_TC_009 | Then 1 |
| BN-9 | LOCAL-1_TC_011 | Then 3 |

## Dimensions

Coverage pass; atomicity/duplicates pass (pairs kept for P19); clarity pass with the TC_006 Then 2 concern; edge cases pass; negative scenarios pass (TC_011 has an allowed same-account GET); traceability pass; completeness against the plan pass; seed-the-defect pass.

# Round 1 - LOCAL-1, dispatch S4-qa-case-critic-1, area cart

Verdict: approve_with_concerns

10 of 10 reviewed. Pinned versions read: TC_005 cv_2f86bbc08f746fb5c1b6, TC_006 cv_0d8c83b22a99a8e6390b, TC_007 cv_123c0496becbde9af1c8, TC_009 cv_32d46944a9ca56b2ba99, TC_011 cv_628e66c0b4330bca3086, TC_012 cv_8f518f2030802670d131, TC_013 cv_b2b90e5ca1bf7455dbb8, TC_014 cv_2c52556ff55fcd53e894, TC_015 cv_0b5c0fde84a74590c05e, TC_016 cv_203088c70403eb2a330e.

Recurring concern (TC_006, 007, 009, 011, 012, 013, 014, 015, 016): the Then points at "what Q4 gives" / "the raised question gives". Q4 is the register's generic before/now question ("before: unknown"), so the body states no value and a reader cannot tell a red from a green until the question is answered. Where a source already names the value (R-5: 201 and one summed line; R-7: OUT_OF_STOCK / INSUFFICIENT_STOCK and unchanged cart; R-9: never visible to or changed by another owner; R-11: sum of quantities, sum of price x quantity) the Then should say it and the `then_oracles` ref should be that R-n or `external:`, not `unknown`. The `now` readings in `question_thens` do carry concrete values, so the cases can run; the automator answers each concern.

## Roll-call

| plan row | case | reviewed | verdict | note |
|---|---|---|---|---|
| TS-5 | LOCAL-1_TC_005 | yes | approve_with_concerns | Seeding guest A=12 above stock 10 is unreachable through POST /api/cart (R-7 refuses it); Given must say stock is lowered after the add (admin or seed), else the P-cap branch is not reachable. Equal quantities not covered (R-4 silent, declared). |
| TS-6 | LOCAL-1_TC_006 | yes | approve_with_concerns | Then 1 can fail (success-only outcome, guest item gone, no text); Then 2 "the page Q4 gives" cannot fail - state an observable (signed-in page reached, not blank). Step 2 reads the guest cart with the guest cookie after sign-in: say which owner that returns. Expected red is declared. lower level: impossible - the defect is what the login page shows after an intercepted merge call; no api call sees the page. |
| TS-7 | LOCAL-1_TC_007 | yes | approve_with_concerns | Source is openapi (R-5) but then_oracles are `unknown/Q4`; write Then as 201, 201, one line quantity 5, then_oracles external:openapi. Planted defect "re-add replaces quantity" is only caught once the value is written. |
| TS-9 | LOCAL-1_TC_009 | yes | approve_with_concerns | R-7 names the two codes; write them in Then 1 (Z 400 OUT_OF_STOCK, A+2 accepted, A+3 400 INSUFFICIENT_STOCK). Step 3 "Reset A to 3" names no call; say PUT. Independent GET channel present. |
| TS-11 | LOCAL-1_TC_011 | yes | approve_with_concerns | R-9 states "never visible to or changed by another owner": write Then 1-3 as absent, Then 4 as item unchanged for its owner. Foreign PUT/DELETE refusal has no named status or reason code in any source - assert only "not changed" (the same account GET is present) and raise the code. |
| TS-12 | LOCAL-1_TC_012 | yes | approve_with_concerns | Step 3 and Then 3 are UI, plan row TS-12 is api: say lower level: api for Then 1-2 and keep the page check as its own parametrised UI step or move to TS-17. Then 3 cannot fail as worded. Source conflict PUT/PATCH is shown at Gate A. |
| TS-13 | LOCAL-1_TC_013 | yes | approve_with_concerns | Good independent channel (seeded prices, GET /api/cart) and lines-vs-units seed. Then values are "Q4 gives": write badge 3 / 4 and the price formulas. Rounding of totals is a declared gap. lower level: impossible - the badge and total are rendered by the UI providers; the api shows only the stored cart. |
| TS-14 | LOCAL-1_TC_014 | yes | approve_with_concerns | lower level: api - merge itself is TC_005; the walk is kept for the UI sign-in path (P19). Given does not state the account cart before sign-in, so "both guest books are in the account cart" is not checkable: add a precondition (account cart empty). Covers R-12 but no Then asserts it (TC_006 owns it): drop R-12 from covers or say so. No evidence_policy (ui: before/after captures + actual steps) is recorded. |
| TS-15 | LOCAL-1_TC_015 | yes | approve_with_concerns | lower level: api - TS-7..TS-10 cover the status rules; the walk is for UI behaviour (double click, typed values). Covers R-8 but no step adds an unknown book id: add the step or drop R-8 from covers. Then 3 keeps value and focus (good). Then 1 "never above stock" is the invariant, write it. No evidence_policy recorded. |
| TS-16 | LOCAL-1_TC_016 | yes | approve_with_concerns | lower level: api - separation is TC_011; walk kept for cookies and two browsers (P19). Then 1 "no previous cart reopens" and Then 2 are Q4 placeholders: write R-9 expected (guest cart after sign-out holds none of the user's items). Add evidence_policy (ui, cookie state captured). |

## Merge candidates

| cases | verdict | reason |
|---|---|---|
| LOCAL-1_TC_005, LOCAL-1_TC_014 | keep | P19: api merge rules versus the UI sign-in walk |
| LOCAL-1_TC_006, LOCAL-1_TC_014 | keep | P19: expected-red automated fault injection versus manual walk; R-12 asserted only in TC_006 |
| LOCAL-1_TC_007, LOCAL-1_TC_015 | keep | P19: api re-add versus manual real-input walk |
| LOCAL-1_TC_009, LOCAL-1_TC_015 | keep | P19: api stock codes versus manual sold-out walk |
| LOCAL-1_TC_011, LOCAL-1_TC_016 | keep | P19: api owner separation versus cookie and two-browser walk |
| LOCAL-1_TC_008, LOCAL-1_TC_015 | keep | P19: TC_008 is the api partition check of R-6; TC_015 is the manual UI walk of typed values and focus |
| LOCAL-1_TC_010, LOCAL-1_TC_015 | keep | P19: TC_010 is the api 404 check of R-8; TC_015 is the manual UI walk (and has no R-8 step, see its note) |

## Branch homes

| BN | home | reason |
|---|---|---|
| BN-5 | LOCAL-1_TC_005 | Then 1-3 |
| BN-6 | LOCAL-1_TC_005 | Then 5 |
| BN-8 | LOCAL-1_TC_009 | Then 1 |
| BN-9 | LOCAL-1_TC_011 | Then 3 |

## Dimensions

Coverage: pass for the scope (R-4, R-5, R-7, R-9, R-10, R-11, R-12; R-8 claimed by TC_015 without a step - concern). Atomicity/duplicates: pass, pairs kept for P19. Clarity: concern (Q4 placeholders; reachability of TC_005 P-cap). Edge cases: pass (stock and stock+1, 0/1000/2.5, units vs lines). Negative scenarios: pass; TC_011 has an allowed GET by the same account. Traceability: pass. Completeness against the plan: pass. Seed-the-defect: concern on TC_006 Then 2, TC_012 Then 3, TC_016.
