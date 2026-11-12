# LOCAL-1 — checks ledger

| Ref | Kind | State | Detail |
|---|---|---|---|
| TS-1 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_001 |
| TS-2 | plan_row | `partial` | LOCAL-1_TC_002 |
| TS-3 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_003 |
| TS-4 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_004 |
| TS-5 | plan_row | `partial` | LOCAL-1_TC_005 |
| TS-6 | plan_row | `partial` | LOCAL-1_TC_006 |
| TS-7 | plan_row | `skipped:cosmetic, badge sum asserted inside TS-1 and TS-3; toast text goes to the Developers line` |  |
| TS-8 | plan_row | `failed:APP_BUG` | LOCAL-1_TC_007 |
| TS-9 | plan_row | `failed:APP_BUG` | LOCAL-1_TC_008 |
| TS-10 | plan_row | `failed:APP_BUG` | LOCAL-1_TC_009 |
| TS-11 | plan_row | `partial` | LOCAL-1_TC_010 |
| TS-12 | plan_row | `partial` | LOCAL-1_TC_011 |
| TS-13 | plan_row | `failed:APP_BUG` | LOCAL-1_TC_012 |
| TS-14 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_013 |
| TS-15 | plan_row | `passed_green` | LOCAL-1_TC_014 |
| TS-16 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_015 |
| TS-17 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_016 |
| TS-18 | plan_row | `passed_green` | LOCAL-1_TC_017 |
| TS-19 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_018 |
| TS-20 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_019 |
| TS-21 | plan_row | `failed:CASE_DEFECT` | LOCAL-1_TC_020 |
| TS-22 | plan_row | `passed_green` | LOCAL-1_TC_021 |
| TS-23 | plan_row | `skipped:the owner's answer leaves no implemented quick-view add path to verify inside add-to-cart scope` |  |
| TS-24 | plan_row | `not_executed:no result recorded for this row's cases` | LOCAL-1_TC_022 |
| TS-25 | plan_row | `not_executed:no result recorded for this row's cases` | LOCAL-1_TC_023 |
| TS-26 | plan_row | `skipped:unverifiable — no observable, two readings (BN-11); owner decides at gate A` |  |
| cart.spec.@api @regression LOCAL-1_TC_004 cart unit price and total equal the catalog price | test | `failed:CASE_DEFECT` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_004 |
| cart.spec.@api @regression LOCAL-1_TC_005 guest adds without login and the cart follows the cookie | test | `review_unverified` | [1] |
| cart.spec.@api @regression LOCAL-1_TC_011 an add that exceeds stock is refused and the cart is unchanged | test | `review_unverified` | [2] |
| cart.spec.@api @regression LOCAL-1_TC_013 maximum quantity is added with the right subtotal | test | `failed:CASE_DEFECT` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_013 |
| cart.spec.@api @regression LOCAL-1_TC_014 an extremely large quantity gives an error or a limit and the app stays up | test | `review_unverified` | [3] |
| cart.spec.@api @regression LOCAL-1_TC_015 adding the same product twice gives one line with the summed quantity | test | `failed:CASE_DEFECT` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_015 |
| cart.spec.@api @regression LOCAL-1_TC_016 several products give one line each and a summed total | test | `failed:CASE_DEFECT` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_016 |
| cart.spec.@api @regression LOCAL-1_TC_017 a nonexistent book is refused with 404 BOOK_NOT_FOUND | test | `review_unverified` | [4] |
| LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_001 |
| LOCAL-1_TC_002 an out-of-stock book cannot be added to the cart | test | `review_unverified` | [5] |
| LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_003 |
| LOCAL-1_TC_006 a signed-in cart survives logout and login | test | `review_unverified` | [6] |
| cart.spec.@regression LOCAL-1_TC_007 invalid_quantity_rejected[tc007_zero] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_007 |
| cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_negative] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008 |
| cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_non_integer] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008 |
| cart.spec.@regression LOCAL-1_TC_009 invalid_quantity_rejected[tc009_non_numeric] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_009 |
| LOCAL-1_TC_010 a quantity above stock is refused with the available number shown | test | `review_unverified` | [7] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_one] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_ten] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_234] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_contains_zero] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_multi_digit] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_stock_boundary] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_zero] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012 |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_above_stock] | test | `review_unverified` | [8] |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_negative] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012 |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_integer] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012 |
| cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_numeric] | test | `failed:APP_BUG` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012 |
| cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[product_page] | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018 |
| cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[catalog_card] | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018 |
| cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[wishlist_move] | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018 |
| cart.spec.@regression LOCAL-1_TC_019 the catalog card adds the book to the cart with the right line | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_019 |
| cart.spec.@regression LOCAL-1_TC_020 moving a wishlist item to the cart adds it and removes it from the wishlist | test | `failed:CASE_DEFECT` | tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_020 |
| cart.spec.@regression LOCAL-1_TC_021 a guest cart is merged at sign-in without losing items | test | `review_unverified` | [9] |

[1] tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 — probe incomplete: probe tool cannot read TypeScript failure wording (cause: tooling, language: typescript)
[2] tests/api/cart/cart.spec.ts::LOCAL-1_TC_011 — probe not_executed: probe tool could not write its request file, path too long (cause: tooling, language: typescript)
[3] tests/api/cart/cart.spec.ts::LOCAL-1_TC_014 — probe incomplete: probe tool cannot read TypeScript (cause: tooling, language: typescript); person's word recorded
[4] tests/api/cart/cart.spec.ts::LOCAL-1_TC_017 — probe incomplete: probe tool cannot read TypeScript (cause: tooling, language: typescript); person's word recorded
[5] tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_002 — probe not applicable to TypeScript: person's word probe gap tooling:typescript
[6] tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_006 — probe not applicable to TypeScript: person's word probe gap tooling:typescript
[7] tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_010 — probe not applicable to TypeScript: person's word probe gap tooling:typescript; static review found no defect
[8] tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012 — probe not applicable to TypeScript: person's word probe gap tooling:typescript; static review found no defect
[9] tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_021 — probe not applicable to TypeScript: person's word probe gap tooling:typescript

## Behavior evidence

| Obligation | Design | Execution | Verified | Gap |
|---|---|---|---|---|
| OB-1 | unknown | inconclusive | False | none |
| OB-2 | unknown | inconclusive | False | none |
| OB-3 | unknown | inconclusive | False | none |
| OB-4 | unknown | failed | False | none |
| OB-5 | unknown | passed | False | none |
| OB-6 | unknown | inconclusive | False | none |
| OB-7 | unknown | not_run | False | toast text not asserted by an automated check |
| OB-8 | unknown | failed | False | none |
| OB-9 | unknown | failed | False | none |
| OB-10 | unknown | failed | False | none |
| OB-11 | unknown | inconclusive | False | none |
| OB-12 | unknown | passed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-13 | unknown | failed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-14 | unknown | failed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-15 | unknown | passed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-16 | unknown | failed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-17 | unknown | failed | False | none |
| OB-18 | unknown | passed | False | none |
| OB-19 | unknown | failed | False | none |
| OB-20 | unknown | failed | False | none |
| OB-21 | unknown | failed | False | none |
| OB-22 | unknown | passed | False | reused candidate assertion evidence is missing, nonexecutable, or mismatched |
| OB-23 | unknown | not_run | False | no implementation or observable |
| OB-24 | unknown | not_run | False | none |
| OB-25 | unknown | not_run | False | none |
| OB-26 | unknown | not_run | False | the expected result is not confirmed by anyone; it is left with you: your answer to Q9 is needed |

`delivery_ready: no`

**What blocks delivery on the product side**

- traceability: R-1 has no terminal outcome (LOCAL-1_TC_001: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-2 has no terminal outcome (LOCAL-1_TC_002: run result 'partial' is not terminal)
- traceability: R-3 has no terminal outcome (LOCAL-1_TC_003: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-4 has no terminal outcome (LOCAL-1_TC_004: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-5 has no terminal outcome (LOCAL-1_TC_005: run result 'partial' is not terminal)
- traceability: R-6 has no terminal outcome (LOCAL-1_TC_006: run result 'partial' is not terminal)
- traceability: R-8 has no terminal outcome (LOCAL-1_TC_007: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-9 has no terminal outcome (LOCAL-1_TC_008: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-10 has no terminal outcome (LOCAL-1_TC_009: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-11 has no terminal outcome (LOCAL-1_TC_010: run result 'partial' is not terminal)
- traceability: R-12 has no terminal outcome (LOCAL-1_TC_011: run result 'partial' is not terminal)
- traceability: R-13 has no terminal outcome (LOCAL-1_TC_012: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-14 has no terminal outcome (LOCAL-1_TC_013: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-16 has no terminal outcome (LOCAL-1_TC_015: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-17 has no terminal outcome (LOCAL-1_TC_016: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-19 has no terminal outcome (LOCAL-1_TC_018: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-20 has no terminal outcome (LOCAL-1_TC_019: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-21 has no terminal outcome (LOCAL-1_TC_020: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-24 has no terminal outcome (LOCAL-1_TC_022: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-25 has no terminal outcome (LOCAL-1_TC_023: neither in automation-manifest tests[] nor unresolved[])
- ledger: TS-2 is `partial` (LOCAL-1_TC_002)
- ledger: TS-5 is `partial` (LOCAL-1_TC_005)
- ledger: TS-6 is `partial` (LOCAL-1_TC_006)
- ledger: TS-8 is `failed:APP_BUG` (LOCAL-1_TC_007)
- ledger: TS-9 is `failed:APP_BUG` (LOCAL-1_TC_008)
- ledger: TS-10 is `failed:APP_BUG` (LOCAL-1_TC_009)
- ledger: TS-11 is `partial` (LOCAL-1_TC_010)
- ledger: TS-12 is `partial` (LOCAL-1_TC_011)
- ledger: TS-13 is `failed:APP_BUG` (LOCAL-1_TC_012)
- ledger: TS-24 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_022)
- ledger: TS-25 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_023)
- ledger: cart.spec.@regression LOCAL-1_TC_007 invalid_quantity_rejected[tc007_zero] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_007)
- ledger: cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_negative] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008)
- ledger: cart.spec.@regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_non_integer] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_008)
- ledger: cart.spec.@regression LOCAL-1_TC_009 invalid_quantity_rejected[tc009_non_numeric] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_009)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_zero] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_negative] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_integer] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- ledger: cart.spec.@regression LOCAL-1_TC_012 quantity_class_behaves[p_non_numeric] is `failed:APP_BUG` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_012)
- coverage red: OB-4 — none
- coverage red: OB-8 — none
- coverage red: OB-9 — none
- coverage red: OB-10 — none
- coverage red: OB-13 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-14 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-16 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage red: OB-17 — none
- coverage red: OB-19 — none
- coverage red: OB-20 — none
- coverage red: OB-21 — none
- coverage red: OB-23 — no implementation or observable

**Factory defects (not the product's — nothing is wanted from you)**

- 13 behaviour(s) no test proves because of the factory's tools or coverage; they stay unproven
- test instance LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal requires current sensitivity proof: no sensitivity receipt
- factory: LOCAL-1_TC_004 cart unit price and total equal the catalog price — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_005 guest adds without login and the cart follows the cookie — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_011 an add that exceeds stock is refused and the cart is unchanged — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: LOCAL-1_TC_013 maximum quantity is added with the right subtotal — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_002 an out-of-stock book cannot be added to the cart — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_006 a signed-in cart survives logout and login — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- factory: cart.spec.@regression LOCAL-1_TC_010 a quantity above stock is refused with the available number shown — INSTANCE_MANIFEST_JOIN_FAILED: no manifest row
- ledger: TS-1 is `failed:CASE_DEFECT` (LOCAL-1_TC_001)
- ledger: TS-3 is `failed:CASE_DEFECT` (LOCAL-1_TC_003)
- ledger: TS-4 is `failed:CASE_DEFECT` (LOCAL-1_TC_004)
- ledger: TS-14 is `failed:CASE_DEFECT` (LOCAL-1_TC_013)
- ledger: TS-16 is `failed:CASE_DEFECT` (LOCAL-1_TC_015)
- ledger: TS-17 is `failed:CASE_DEFECT` (LOCAL-1_TC_016)
- ledger: TS-19 is `failed:CASE_DEFECT` (LOCAL-1_TC_018)
- ledger: TS-20 is `failed:CASE_DEFECT` (LOCAL-1_TC_019)
- ledger: TS-21 is `failed:CASE_DEFECT` (LOCAL-1_TC_020)
- ledger: cart.spec.@api @regression LOCAL-1_TC_004 cart unit price and total equal the catalog price is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_004)
- ledger: cart.spec.@api @regression LOCAL-1_TC_013 maximum quantity is added with the right subtotal is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_013)
- ledger: cart.spec.@api @regression LOCAL-1_TC_015 adding the same product twice gives one line with the summed quantity is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_015)
- ledger: cart.spec.@api @regression LOCAL-1_TC_016 several products give one line each and a summed total is `failed:CASE_DEFECT` (tests/api/cart/cart.spec.ts::LOCAL-1_TC_016)
- ledger: LOCAL-1_TC_001 an in-stock book is added once with the right price from the product page is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_001)
- ledger: LOCAL-1_TC_003 quantity 3 is added and the cart shows 3 with the right subtotal is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_003)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[product_page] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[catalog_card] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_018 add_path_obeys_the_add_rules[wishlist_move] is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_018)
- ledger: cart.spec.@regression LOCAL-1_TC_019 the catalog card adds the book to the cart with the right line is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_019)
- ledger: cart.spec.@regression LOCAL-1_TC_020 moving a wishlist item to the cart adds it and removes it from the wishlist is `failed:CASE_DEFECT` (tests/e2e/cart/cart.spec.ts::LOCAL-1_TC_020)
- coverage: OB-1 — none
- coverage: OB-2 — none
- coverage: OB-3 — none
- coverage: OB-5 — none
- coverage: OB-6 — none
- coverage: OB-7 — toast text not asserted by an automated check
- coverage: OB-11 — none
- coverage: OB-12 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-15 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-18 — none
- coverage: OB-22 — reused candidate assertion evidence is missing, nonexecutable, or mismatched
- coverage: OB-24 — none
- coverage: OB-25 — none
