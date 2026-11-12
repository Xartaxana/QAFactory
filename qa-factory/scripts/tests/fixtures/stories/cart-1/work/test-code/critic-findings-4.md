# Critic findings - S5-qa-code-critic-4 (CART-1_TC_009)

Roll-call: CART-1_TC_009 -> tests/api/cart/cart-quote-order.spec.ts "@api @regression CART-1_TC_009 quote and order from cart" (OB-9, cv_2b3ebd621560f9547704). Then 1-5 each asserted with a Then-named message; values from the case (R-15), none from code. Cart read-back through GET /api/cart; status classes 400/409/422 plus error/code shape, no exact code (Q1).

- F-1 [tooling] probe_by_code cannot read Playwright TypeScript: unverified, sensitivity_proof_missing_reason. Person's waiver "probe gap: CART-1_TC_009" applies.
- F-2 [tooling] window_record: empty_scope. The manifest `tests[]` holds no instance for CART-1_TC_009 (only the contradicts_requirement row, Then 2); no obligation_bindings. The author's fragment must carry the instance (red, contradicts_requirement) so the receipt can be built. Not a test defect.
- Red test judgement: Then 2 asserts quote items equal the cart read, as the approved case says. Faithful; accepted RED with contradicts_requirement (quote body has no items array). Not bent to the code.
- F-3 [note] Soft asserts keep Then 1-5 independent; no unpack before an assert. Then 1/3 "no items" holds trivially if the body has no items array in any case (also true for rejected quotes), acceptable per the case wording.
- TC_007 / TC_008 mechanical fix (F-3 of window 3): landed. Both assert `toHaveLength(1)` on the filtered rows before `[row]` / `[rowA]`. Those two files were NOT re-run; reviewed statically only.

## S5-qa-code-critic-5 re-review
Then 2 quote-vs-cart assert only moved to the end (soft asserts); value and text unchanged, not fitted to code. Test still red on Then 2 alone (evidence/runs/c7f56259e689c93a9ddf). Probe not applicable: red. F-2 (empty_scope) addressed by the author's instance row.
