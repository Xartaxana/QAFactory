# Case critic round 2 - LOCAL-1 (S4-qa-case-critic-2)

Verdict: approve_with_concerns

Review basis: repaired cases at the pinned versions in state/case-versions (TC_002 cv_d0150be267e7a21396f3, TC_005 cv_1e2fe984a158845705a5, TC_007 cv_046af312329b03af6938, TC_008 cv_399811ae764fa23a33a4, TC_009 cv_a7a0796939a1b5bab25c, TC_019 cv_52d16ccfe2ee80471805, TC_020 cv_3599058ee1132918ddd6, TC_021 cv_beee818c5ed0c652255b, TC_022 cv_050e8c970fb400e8ca43, TC_023 cv_931e0a5df2fd8baabb25, TC_024 cv_f8fbf2461e7153566924), test-plan.md, requirements-register.md. proof_kind: design_analysis for every sensitivity statement (no probe executed). Round 2 of 2. Round-1 items verified repaired: TC_002 API attempt split into Then 3 and BN-1 moved to Then 2; TC_005 persistence Then 4 added; TC_007/008/009 "keeps focus" dropped, P-non-integer branch row added, typing mechanism stated; TC_020 reachable via stock change after render and admin precondition; TC_021 admin precondition, Given order and Q6 oracle added.

## Roll-call

| plan row | case | reviewed | verdict | note | fix |
|---|---|---|---|---|---|
| TS-2 | LOCAL-1_TC_002 | yes | approve | Round-1 concerns repaired. Seeded defect (stock check removed): API add returns 2xx and a line appears, Then 1 and 3 fail. Wording Then 2 is reading-neutral, BN-1 homed on Then 2. | |
| TS-5 | LOCAL-1_TC_005 | yes | approve | Seeded defect (shared global cart) fails Then 3; session-only cookie fails Then 4. Browser restart not performed, named as residual. | |
| TS-8 | LOCAL-1_TC_007 | yes | approve | Seeded defect (0 coerced to 1, a line appears) fails Then 2. Red by the person's decision, not a designer defect. | |
| TS-9 | LOCAL-1_TC_008 | yes | approve | Both partitions have branch rows; rounding or coercion fails Then 2 and 3. Red by the person's decision. | |
| TS-10 | LOCAL-1_TC_009 | yes | approve_with_concerns | C1: Then 3 is hedged ("abc" kept whole, or an empty number input) and cannot fail on its own; the case rests on Then 1 and 2, which do discriminate (coercion to 1 adds a line). Typing mechanism now stated. | Rewrite Then 3 as "the field does not hold a number the shopper did not type" or drop it in favour of Then 1 and 2. |
| TS-20 | LOCAL-1_TC_019 | yes | approve_with_concerns | C1: Then 2 (quantity exactly 1) asserts nothing until Q6 is answered, so a card that adds 2 copies passes Then 1 (dimension 8 only after Q6). Correctly marked oracle_unknown via question_thens; Gate A must show TS-20 as not covering the quantity yet. | none; answer Q6 |
| TS-21 | LOCAL-1_TC_020 | yes | approve_with_concerns | C1: the branch is now reachable, but the completion boundary (the add request of step 4 answered with a refusal) lives only in the Notes; the automator must make it a When/Then step or Then 3 may read the wishlist before the refusal. C2: Thens 2 and 3 carry no literal until Q6; the no-item-lost floor for the refused move is still unasserted. Seeded defect (wishlist item deleted after a failed add) is caught by Then 3 only once Q6 = now. | Add to When step 4: "wait for the POST /api/cart response and assert it is a 4xx" and list it as a Then. |
| TS-22 | LOCAL-1_TC_021 | yes | approve_with_concerns | C1: all three Thens are conditional on Q6 (oracle_unknown, R-6 does not cover guest merge); until the answer the case asserts nothing and the data-loss floor (guest item survives sign-in) is unprotected. Values 2/4/10 separate max, sum and replace, a good design for after Q6. | none; answer Q6 |
| TS-24 | LOCAL-1_TC_022 | yes | approve_with_concerns | C1: Then 1 asserts no literal until Q4; Then 2 (price is 10.00 or 12.00, no 5xx) catches a third value or a crash only. C2: the update is sequenced before the click, not a true race; declared as residual. C3: evidence_policy api with a page click: the add response and cart read are the evidence, acceptable. | none; answer Q4 |
| TS-25 | LOCAL-1_TC_023 | yes | approve_with_concerns | C1: the abort is a browser route rule, so the request never reaches the server; "the system completes the action" (Q4 = a) can only happen through a client retry, so Then 3 (no duplicate) is trivially met unless a retry runs. Then 1 holds under both readings and catches a silent failure. | State in When 4 whether a client retry is followed, so Then 3 can fail on a duplicated retry. |
| TS-26 | LOCAL-1_TC_024 | yes | approve_with_concerns | C1: Then 2 is a disjunction ("one line for B, or a visible message"): an add that is dropped while any message shows passes, which contradicts "never loses the product". Then 1 is open until Q4. | Make Then 2: after re-authentication or extension the cart holds one line for B quantity 1, or the page shows a visible message and the cart holds no line for B and no duplicate. |

## Dimension scores (scope as a whole)

1 Coverage pass. 2 Atomicity pass. 3 Clarity concern (TC_020 completion boundary in Notes; TC_009 Then 3 hedged). 4 Edge cases pass. 5 Negative scenarios pass (TC_020 branch now reachable). 6 Traceability pass (BN-1, BN-2, BN-3, BN-9, BN-10, BN-11 homed). 7 Completeness pass, every dispatched row has a case. 7b concern: TC_019 to TC_024 Thens rest on open Q4/Q6 and are raised to Gate A as the owner's questions, not scored against the designer; no Then contradicts a source. 7c not applicable. 8 concern (TC_024 Then 2 disjunction, TC_019/021 until Q6).

## Branch homes

| BN | home | reason |
|---|---|---|
| BN-1 | LOCAL-1_TC_002 | wording branch is Then 2 |
| BN-2 | LOCAL-1_TC_007 | Then 1 (P-zero) |
| BN-3 | LOCAL-1_TC_008 | Then 1 (P-negative, P-non-integer) |
| BN-9 | LOCAL-1_TC_005 | Then 3 (first-add wording left unasserted) |
| BN-10 | LOCAL-1_TC_023 | Then 2 |
| BN-11 | LOCAL-1_TC_024 | Then 1 |

Sensitivity records (proof_kind: design_analysis, no observed_failure_ref): TS-2 site stock check, expected failure Then 1 and 3; TS-5 site guest cookie ownership and lifetime, Then 3 and 4; TS-8 site quantity coercion, Then 2; TS-9 same site, Then 2; TS-10 same site, Then 2; TS-20 site card quantity, not detectable until Q6; TS-21 site wishlist delete after refused add, Then 3 once Q6 answered; TS-22 site price source, Then 2; TS-25 site silent failure, Then 1; TS-26 site dropped add, weakly Then 2.

Unreviewed for Gate A: none (11 of 11 reviewed).

---

# Case critic round 1 - LOCAL-1 (S4-qa-case-critic-1)

Verdict: reject

Review basis: author cases at pinned versions (state/case-versions), plan test-plan.md, register, code BookDetailPage.tsx:155-164, WishlistPage.tsx:81-96, LoginPage.tsx:36. proof_kind: design_analysis for every sensitivity statement below (no probe was executed). Round 1 of 2.

## Roll-call

| plan row | case | reviewed | verdict | note | fix |
|---|---|---|---|---|---|
| TS-2 | LOCAL-1_TC_002 | yes | approve_with_concerns | C1: Then 1 asserts a 4xx status the register does not state (R-2 says only "cannot be added"); assert "no line / no 2xx" and keep the status as informative. C2: Then 1 mixes a UI attempt and a direct API attempt (two scenarios); the "if enabled" click is conditional. C3: branches maps BN-1 to Then 1, but BN-1 (message vs disabled button) is carried by Then 2. Seeded defect (stock check removed): API returns 2xx and a line appears, Then 1 fails. | Split the API attempt into its own Then; move BN-1 to then 2. |
| TS-4 | LOCAL-1_TC_004 | yes | approve | Price is read from the catalog (independent channel), total computed by the test from 19.99 x 2; seeded defect (cart uses another price or rounds) fails Then 1 or 2. | |
| TS-5 | LOCAL-1_TC_005 | yes | approve_with_concerns | C1: plan defect site is the guest session cookie, but only cookie reuse is proven; a session-only cookie (lost on browser close, the R-5 clause) passes every Then. Design gap, named by the author as residual. C2: Given PC-2 is a `data` kind with case_seeds, fine; Then 3 is a good seeded-defect check for a shared global cart. | Add a Then: the Set-Cookie of the guest add carries Max-Age or Expires (persistent), or mark the persistence part of R-5 as not proven at Gate A. |
| TS-8 | LOCAL-1_TC_007 | yes | approve_with_concerns | C1: Then 3 asserts "keeps focus", stated by no source (R-8 says only that 0 is rejected and not turned into 1); oracle_unknown, not an assertion. C2: the UI today holds quantity as a number state clamped to >= 1 (BookDetailPage.tsx:164), so "0 whole" can never be displayed, red is by design (person's decision, source_conflict). Seeded defect (coercion to 1): Then 2 fails (a line for B appears). | Drop "and keeps focus" from Then 3. |
| TS-9 | LOCAL-1_TC_008 | yes | approve_with_concerns | C1: two partitions (-1 and 1.5) in one case; branches carry only P-negative, P-non-integer has no branch row. C2: "keeps focus" in Then 3 has no source. C3: Then 3 "field shows -1 / 1.5 whole" is the UI form of R-9's "never coerced", acceptable. Seeded defect (round 1.5 to 2 or 1): Then 2 fails. | Drop "and keeps focus"; add a branches row for the P-non-integer partition. |
| TS-10 | LOCAL-1_TC_009 | yes | approve_with_concerns | C1: reachability of the input. The field is `type="number"` (BookDetailPage.tsx:159); a Playwright fill of "abc" throws, and typed letters are dropped by the browser, so the value is empty and the clamp makes it 1. The step must say how "abc" is entered (keyboard typing) and that the dropped text is not a pass. C2: "keeps focus" has no source. Seeded defect (non-numeric turned into 1): Then 2 fails. | State the typing mechanism and drop "and keeps focus". |
| TS-11 | LOCAL-1_TC_010 | yes | approve | Stock 4 / request 5 separates the boundary; cart read via API after completion; message carries the available number (R-11). A defect letting stock+1 through fails Then 2. The partial-add reading (BN-4) is left open honestly. | |
| TS-14 | LOCAL-1_TC_013 | yes | approve | Stock 50 below the 999 cap: the assertion holds under both readings of "maximum" (Q3), and an off-by-one that rejects quantity == stock fails Then 1. | |
| TS-20 | LOCAL-1_TC_019 | yes | approve_with_concerns | C1: the plan defect class is a wrong catalog-card quantity, but Then 1 does not see it (a card adding 2 copies passes) and Then 2 asserts nothing until Q6 is answered. The row is correctly oracle_unknown (code claim, Q6); it must reach Gate A as the owner's question, not as a covered quantity check. | At Gate A show TS-20 as not covering the quantity until Q6; no case change. |
| TS-21 | LOCAL-1_TC_020 | yes | reject | F-1 (dimension 8, reachability): the negative branch cannot be reached as written. WishlistPage.tsx:81 sets `out = stockQuantity === 0` and line 96 renders the move button `disabled={out}`, so step 2 "click move to cart for X (the add is refused)" with X out of stock clicks a disabled control; Then 3 would be checking a branch that never ran. Seeded defect (the wishlist item deleted after a failed add, WishlistPage.tsx:54-58): never exercised. | Make X in stock when the wishlist page renders, then set its stock to 0 (or fill the cart to stock) before the click; assert the add is refused (4xx) and X stays; add a precondition for the stock-changing account (admin) or API. |
| TS-22 | LOCAL-1_TC_021 | yes | approve_with_concerns | C1: Then 1 rests on R-6 ("cart persists across logout and login"), which says nothing about merging a guest cart; the guest item surviving login is a Q6/R-22 rule. Oracle imported, treat as oracle_unknown (7b). C2: Given needs to change Z's stock to 0 and seed the user's cart (H x4) while signed in, but no admin or stock-changing precondition is declared (the stand holds an admin account). C3: order of the Given steps (seed user cart, log out, build guest cart) is unstated. Merge is reachable: LoginPage.tsx:36 calls /api/cart/merge. | Re-point Then 1 to Q6 in then_oracles; declare a `stand_account: admin` precondition; write the Given order. |

## Dimension scores (scope as a whole)

1 Coverage pass (every dispatched R has a case). 2 Atomicity concern (TC_002, TC_008). 3 Clarity concern (TC_021 admin precondition; TC_009 input mechanism). 4 Edge cases pass. 5 Negative scenarios fail (TC_020 unreachable branch). 6 Traceability concern (BN-1 and P-non-integer mapping; TC_019/020/021 basis are R-19/R-6 while covers is R-20/21/22, consistent with the plan row). 7 Completeness pass. 7b concern (TC_021 Then 1, focus clauses). 7c not applicable, no "as before" Then. 8 fail (TC_020).

Contradiction handling: TS-8 to TS-10 are expected red by the person's decision (requirement over code, matrix cells R-8..R-10); not a designer defect, goes to Gate B as a candidate bug.

## Branch homes

| BN | home | reason |
|---|---|---|
| BN-1 | LOCAL-1_TC_002 | wording branch is Then 2; the case maps it to Then 1, to be corrected |
| BN-4 | LOCAL-1_TC_010 | Then 2 (whole rejection reading) |
| BN-7 | LOCAL-1_TC_013 | Then 1 (stock reading) |
| BN-9 | LOCAL-1_TC_005 | Then 3 (first-add wording left unasserted) |

Sensitivity records (proof_kind: design_analysis): TS-2 site stock check, expected failure Then 1; TS-4 site cart price source, Then 1/2; TS-8 site quantity coercion, Then 2; TS-11 site stock comparison, Then 2; TS-14 site stock boundary, Then 1; TS-21 site wishlist delete after failure, NOT reached (see F-1).

Unreviewed for Gate A: none (11 of 11 reviewed).
