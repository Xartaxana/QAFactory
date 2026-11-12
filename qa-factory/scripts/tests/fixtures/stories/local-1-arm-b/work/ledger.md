# LOCAL-1 — checks ledger

| Ref | Kind | State | Detail |
|---|---|---|---|
| TS-1 | plan_row | `failed:ASSERT_STRICTER` | LOCAL-1_TC_001 |
| TS-2 | plan_row | `passed_green` | LOCAL-1_TC_002 |
| TS-3 | plan_row | `passed_green` | LOCAL-1_TC_003 |
| TS-4 | plan_row | `passed_green` | LOCAL-1_TC_004 |
| TS-5 | plan_row | `passed_green` | LOCAL-1_TC_005 |
| TS-6 | plan_row | `failed:untriaged` | LOCAL-1_TC_006 |
| TS-7 | plan_row | `passed_green` | LOCAL-1_TC_007 |
| TS-8 | plan_row | `passed_green` | LOCAL-1_TC_008 |
| TS-9 | plan_row | `passed_green` | LOCAL-1_TC_009 |
| TS-10 | plan_row | `passed_green` | LOCAL-1_TC_010 |
| TS-11 | plan_row | `passed_green` | LOCAL-1_TC_011 |
| TS-12 | plan_row | `passed_green` | LOCAL-1_TC_012 |
| TS-13 | plan_row | `passed_green` | LOCAL-1_TC_013 |
| TS-14 | plan_row | `not_executed:no result recorded for this row's cases` | LOCAL-1_TC_014 |
| TS-15 | plan_row | `not_executed:no result recorded for this row's cases` | LOCAL-1_TC_015 |
| TS-16 | plan_row | `not_executed:no result recorded for this row's cases` | LOCAL-1_TC_016 |
| TS-17 | plan_row | `failed:untriaged` | LOCAL-1_TC_017 |
| TS-18 | plan_row | `failed:APP_BUG` | LOCAL-1_TC_018 |
| TS-19 | plan_row | `passed_green` | LOCAL-1_TC_019 |
| TS-20 | plan_row | `passed_green` | LOCAL-1_TC_020 |
| @api @regression LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged | test | `not_verified:missing_sensitivity_proof` | [1] |
| @api @regression LOCAL-1_TC_007 re-adding a book sums into one line, answers 201 | test | `not_verified:missing_sensitivity_proof` | [2] |
| @api @regression LOCAL-1_TC_008 edge quantity 999 is accepted | test | `not_verified:missing_sensitivity_proof` | [3] |
| @api @regression LOCAL-1_TC_009 total exactly equal to stock is accepted | test | `not_verified:missing_sensitivity_proof` | [4] |
| @api @regression LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped | test | `not_verified:missing_sensitivity_proof` | [5] |
| @api @regression LOCAL-1_TC_005 guest quantity above stock is capped at stock | test | `not_verified:missing_sensitivity_proof` | [6] |
| @api @regression LOCAL-1_TC_008 quantity zero (0) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [7] |
| @api @regression LOCAL-1_TC_008 quantity negative (-1) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [8] |
| @api @regression LOCAL-1_TC_008 quantity above-max-1000 (1000) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [9] |
| @api @regression LOCAL-1_TC_008 quantity fraction (1.5) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [10] |
| @api @regression LOCAL-1_TC_008 bookId zero (0) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [11] |
| @api @regression LOCAL-1_TC_008 bookId negative (-3) is refused with VALIDATION_ERROR | test | `not_verified:missing_sensitivity_proof` | [12] |
| @api @regression LOCAL-1_TC_008 edge quantity 1 is accepted | test | `not_verified:missing_sensitivity_proof` | [13] |
| @api @regression LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged | test | `not_verified:missing_sensitivity_proof` | [14] |
| @api @regression LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged | test | `not_verified:missing_sensitivity_proof` | [15] |
| LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 |
| LOCAL-1_TC_005 guest quantity above stock is capped at stock | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 |
| LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 |
| LOCAL-1_TC_007 re-adding a book sums into one line, answers 201 | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_007 |
| LOCAL-1_TC_008 quantity ${name} (${qty}) is refused with VALIDATION_ERROR | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 |
| LOCAL-1_TC_008 bookId ${name} (${id}) is refused with VALIDATION_ERROR | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 |
| LOCAL-1_TC_008 edge quantity ${qty} is accepted | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 |
| LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 |
| LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 |
| LOCAL-1_TC_009 total exactly equal to stock is accepted | test | `review_skipped` | tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 |
| @api @regression LOCAL-1_TC_010 unknown book id is 404 BOOK_NOT_FOUND, cart untouched | test | `passed_green` | [16]; the check is live |
| @api @regression LOCAL-1_TC_011 user cart and guest carts do not see each other lines | test | `passed_green` | [17]; the check is live |
| @api @regression LOCAL-1_TC_011 admin cart and guest carts do not see each other lines | test | `passed_green` | [17]; the check is live |
| @api @regression LOCAL-1_TC_011 foreign PUT and DELETE leave the owner line unchanged | test | `passed_green` | [17]; the check is live |
| @api @regression LOCAL-1_TC_012 update to stock is accepted, one over is INSUFFICIENT_STOCK and keeps 5 | test | `passed_green` | [18]; the check is live |
| @regression LOCAL-1_TC_002 success message differs for quantity 1 and 3, cart holds 4 | test | `review_unverified` | [19] |
| @regression LOCAL-1_TC_002 out-of-stock book: button disabled, no POST /api/cart, no cart line | test | `review_unverified` | [19] |
| @regression LOCAL-1_TC_001 in-stock add shows success toast, badge 1 and one cart line | test | `review_unverified` | [20] |
| @regression LOCAL-1_TC_001 stock-0 book: error shown, no success, badge stays 1, no cart line | test | `failed:ASSERT_STRICTER` | tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_001 |
| @regression LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it | test | `not_verified:missing_sensitivity_proof` | [21] |
| @regression LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist | test | `not_verified:missing_sensitivity_proof` | [22] |
| @regression LOCAL-1_TC_006 P-merge500 merge failure is not silent, shopper is signed in | test | `review_unverified` | [23] |
| @regression LOCAL-1_TC_006 P-mergetimeout merge failure is not silent, shopper is signed in | test | `failed:APP_BUG` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_006 |
| @regression LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove | test | `not_verified:missing_sensitivity_proof` | [24] |
| LOCAL-1_TC_006 ${p.name} merge failure is not silent, shopper is signed in | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_006 |
| LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_013 |
| LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it | test | `review_skipped` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_003 |
| LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist | test | `review_skipped` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_004 |
| @regression LOCAL-1_TC_017 P-cartread-error500 failed cart read says so, not the empty-cart text | test | `failed:APP_BUG` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-cartread-timeout failed cart read says so, not the empty-cart text | test | `failed:APP_BUG` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-bookread-error500 failed book read shows an error or the lines, not a blank page | test | `failed:APP_BUG` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-bookread-timeout failed book read shows an error or the lines, not a blank page | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-putfail-error500 failed quantity change shows an error, stored quantity stays 1 | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-putfail-timeout failed quantity change shows an error, stored quantity stays 1 | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-deletefail-error500 failed remove shows a message, the line stays | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_017 P-deletefail-timeout failed remove shows a message, the line stays | test | `review_skipped` | tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017 |
| @regression LOCAL-1_TC_018 P-deletefail-error500 move with a failed wishlist delete is not reported as moved | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-deletefail-timeout move with a failed wishlist delete is not reported as moved | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-postfail-error500 move with a failed cart add keeps the book on the wishlist and says so | test | `review_skipped` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-postfail-timeout move with a failed cart add keeps the book on the wishlist and says so | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-removefail-error500 failed remove shows an error, the book stays on the wishlist | test | `review_skipped` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-removefail-timeout failed remove shows an error, the book stays on the wishlist | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-getfail-error500 failed wishlist read shows an error, not the empty-wishlist text | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_018 P-getfail-timeout failed wishlist read shows an error, not the empty-wishlist text | test | `failed:APP_BUG` | tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018 |
| @regression LOCAL-1_TC_019 P-error500 failed POST /api/cart: error shown, no success, badge 0, no cart line, Add works again | test | `review_unverified` | [25] |
| @regression LOCAL-1_TC_019 P-timeout failed POST /api/cart: error shown, no success, badge 0, no cart line, Add works again | test | `review_unverified` | [25] |
| @regression LOCAL-1_TC_020 P-addfail-error500 failed add of quantity 3: error shown, no success message, no cart line | test | `review_unverified` | [26] |
| @regression LOCAL-1_TC_020 P-readfail-error500 failed book read: the page shows a message, not a blank page | test | `review_unverified` | [26] |
| @regression LOCAL-1_TC_020 P-addfail-timeout failed add of quantity 3: error shown, no success message, no cart line | test | `review_unverified` | [26] |
| @regression LOCAL-1_TC_020 P-readfail-timeout failed book read: the page shows a message, not a blank page | test | `review_unverified` | [26] |

[1] tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged; sensitivity_proof.instance_id does not match the manifest instance
[2] tests/api/cart/cart.spec.ts::LOCAL-1_TC_007 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_007 re-adding a book sums into one line, answers 201
[3] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 edge quantity 999 is accepted; sensitivity_proof.instance_id does not match the manifest instance
[4] tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 total exactly equal to stock is accepted; sensitivity_proof.instance_id does not match the manifest instance
[5] tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped
[6] tests/api/cart/cart.spec.ts::LOCAL-1_TC_005 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 guest quantity above stock is capped at stock
[7] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity zero (0) is refused with VALIDATION_ERROR
[8] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity negative (-1) is refused with VALIDATION_ERROR
[9] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity above-max-1000 (1000) is refused with VALIDATION_ERROR
[10] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity fraction (1.5) is refused with VALIDATION_ERROR
[11] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 bookId zero (0) is refused with VALIDATION_ERROR
[12] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 bookId negative (-3) is refused with VALIDATION_ERROR
[13] tests/api/cart/cart.spec.ts::LOCAL-1_TC_008 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 edge quantity 1 is accepted
[14] tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged
[15] tests/api/cart/cart.spec.ts::LOCAL-1_TC_009 — its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged
[16] tests/api/cart/cart.spec.ts::LOCAL-1_TC_010 — run freshness not measured: the run recorded no per-test identity
[17] tests/api/cart/cart.spec.ts::LOCAL-1_TC_011 — run freshness not measured: the run recorded no per-test identity
[18] tests/api/cart/cart.spec.ts::LOCAL-1_TC_012 — run freshness not measured: the run recorded no per-test identity
[19] tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_002 — probe_by_code.py could not conclude on a Playwright toast/disabled assert (no_failure/wrong_location/incomplete); tooling
[20] tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_001 — probe_by_code.py could not conclude on a Playwright toast/disabled assert (no_failure/wrong_location/incomplete); tooling
[21] tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_003 — its receipt is for other bytes (test_content_hash 52e579f5278bd3ec84395593d474ad105c3559086f040101fae4efc3f69c6e5d, the test file now hashes f8d7d5297f4e545977a4fd77e80d5afed6d0b4d6f551a9b2b798600d3f9f7e0c) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it
[22] tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_004 — its receipt is for other bytes (test_content_hash 52e579f5278bd3ec84395593d474ad105c3559086f040101fae4efc3f69c6e5d, the test file now hashes f8d7d5297f4e545977a4fd77e80d5afed6d0b4d6f551a9b2b798600d3f9f7e0c) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist
[23] tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_006 — inverted probe at :87 no_failure (tooling E14: entry not compiled); static review found no defect
[24] tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_013 — its receipt is for other bytes (test_content_hash 395f28035d735e92d08510940ffe4dfbe034a1d9914b46cfcde99fb65cc528a6, the test file now hashes c1065221ef6a8f204e21866a6609424633fd29bddcf6b79d36bab778cce6129e) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove
[25] tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_019 — probe incomplete: failed at the mutated line in inverted form (cause data_row), detector wording mismatch
[26] tests/e2e/cart/add_to_cart.spec.ts::LOCAL-1_TC_020 — probe incomplete: failed at the mutated line in inverted form (cause data_row), detector wording mismatch

## Behavior evidence

| Obligation | Design | Execution | Verified | Gap |
|---|---|---|---|---|
| OB-1 | sufficient | failed | False | current sufficient evidence incomplete |
| OB-2 | sufficient | passed | False | the code critic could not verify the test that covers it; it is left with you: run it where you can, or accept the risk |
| OB-3 | unknown | passed | False | current sufficient evidence incomplete |
| OB-4 | unknown | passed | False | current sufficient evidence incomplete |
| OB-5 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-6 | sufficient | failed | False | current sufficient evidence incomplete |
| OB-7 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-8 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-9 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-10 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-11 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-12 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-13 | sufficient | passed | False | current sufficient evidence incomplete |
| OB-14 | unknown | not_run | False | current sufficient evidence incomplete |
| OB-15 | unknown | not_run | False | current sufficient evidence incomplete |
| OB-16 | unknown | not_run | False | current sufficient evidence incomplete |
| OB-17 | sufficient | failed | False | current sufficient evidence incomplete |
| OB-18 | sufficient | failed | False | current sufficient evidence incomplete |
| OB-19 | sufficient | passed | False | the code critic could not verify the test that covers it; it is left with you: run it where you can, or accept the risk |
| OB-20 | sufficient | passed | False | the code critic could not verify the test that covers it; it is left with you: run it where you can, or accept the risk |

`delivery_ready: no`

**What blocks delivery on the product side**

- traceability: R-4 has no terminal outcome (LOCAL-1_TC_005: passed; LOCAL-1_TC_014: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-6 has no terminal outcome (LOCAL-1_TC_008: passed; LOCAL-1_TC_015: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-7 has no terminal outcome (LOCAL-1_TC_009: passed; LOCAL-1_TC_015: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-8 has no terminal outcome (LOCAL-1_TC_010: passed; LOCAL-1_TC_015: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-9 has no terminal outcome (LOCAL-1_TC_011: passed; LOCAL-1_TC_016: neither in automation-manifest tests[] nor unresolved[])
- traceability: R-12 has no terminal outcome (LOCAL-1_TC_006: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-13 has no terminal outcome (LOCAL-1_TC_018: unresolved (contradicts_requirement) with no decision attached)
- traceability: R-14 has no terminal outcome (LOCAL-1_TC_017: unresolved (contradicts_requirement) with no decision attached)
- ledger: TS-14 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_014)
- ledger: TS-15 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_015)
- ledger: TS-16 is `not_executed:no result recorded for this row's cases` (LOCAL-1_TC_016)
- ledger: TS-18 is `failed:APP_BUG` (LOCAL-1_TC_018)
- ledger: @regression LOCAL-1_TC_006 P-mergetimeout merge failure is not silent, shopper is signed in is `failed:APP_BUG` (tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_006); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_017 P-cartread-error500 failed cart read says so, not the empty-cart text is `failed:APP_BUG` (tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_017 P-cartread-timeout failed cart read says so, not the empty-cart text is `failed:APP_BUG` (tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_017 P-bookread-error500 failed book read shows an error or the lines, not a blank page is `failed:APP_BUG` (tests/e2e/cart/cart_page.spec.ts::LOCAL-1_TC_017); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-deletefail-error500 move with a failed wishlist delete is not reported as moved is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-deletefail-timeout move with a failed wishlist delete is not reported as moved is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-postfail-timeout move with a failed cart add keeps the book on the wishlist and says so is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-removefail-timeout failed remove shows an error, the book stays on the wishlist is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-getfail-error500 failed wishlist read shows an error, not the empty-wishlist text is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- ledger: @regression LOCAL-1_TC_018 P-getfail-timeout failed wishlist read shows an error, not the empty-wishlist text is `failed:APP_BUG` (tests/e2e/cart/wishlist_move.spec.ts::LOCAL-1_TC_018); repair limit exhausted: 2 of 2 rounds about the tests themselves
- coverage red: OB-1 — current sufficient evidence incomplete
- coverage red: OB-6 — current sufficient evidence incomplete
- coverage red: OB-17 — current sufficient evidence incomplete
- coverage red: OB-18 — current sufficient evidence incomplete

**Review gaps**

- review: no critic verdict for LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped, LOCAL-1_TC_005 guest quantity above stock is capped at stock, LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged, LOCAL-1_TC_007 re-adding a book sums into one line, answers 201, LOCAL-1_TC_008 quantity ${name} (${qty}) is refused with VALIDATION_ERROR, LOCAL-1_TC_008 bookId ${name} (${id}) is refused with VALIDATION_ERROR, LOCAL-1_TC_008 edge quantity ${qty} is accepted, LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged, LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged, LOCAL-1_TC_009 total exactly equal to stock is accepted, LOCAL-1_TC_006 ${p.name} merge failure is not silent, shopper is signed in, LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove, LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it, LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist, @regression LOCAL-1_TC_017 P-bookread-timeout failed book read shows an error or the lines, not a blank page, @regression LOCAL-1_TC_017 P-putfail-error500 failed quantity change shows an error, stored quantity stays 1, @regression LOCAL-1_TC_017 P-putfail-timeout failed quantity change shows an error, stored quantity stays 1, @regression LOCAL-1_TC_017 P-deletefail-error500 failed remove shows a message, the line stays, @regression LOCAL-1_TC_017 P-deletefail-timeout failed remove shows a message, the line stays, @regression LOCAL-1_TC_018 P-postfail-error500 move with a failed cart add keeps the book on the wishlist and says so, @regression LOCAL-1_TC_018 P-removefail-error500 failed remove shows an error, the book stays on the wishlist

**Factory defects (not the product's — nothing is wanted from you)**

- 13 behaviour(s) no test proves because of the factory's tools or coverage; they stay unproven
- test instance @api @regression LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-5): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged
- test instance @api @regression LOCAL-1_TC_005 empty guest cart leaves the account cart unchanged requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-5): sensitivity_proof.instance_id does not match the manifest instance
- test instance @api @regression LOCAL-1_TC_007 re-adding a book sums into one line, answers 201 requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-7): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_007 re-adding a book sums into one line, answers 201
- test instance @api @regression LOCAL-1_TC_008 edge quantity 999 is accepted requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-8): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 edge quantity 999 is accepted
- test instance @api @regression LOCAL-1_TC_008 edge quantity 999 is accepted requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-8): sensitivity_proof.instance_id does not match the manifest instance
- test instance @api @regression LOCAL-1_TC_009 total exactly equal to stock is accepted requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-9): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 total exactly equal to stock is accepted
- test instance @api @regression LOCAL-1_TC_009 total exactly equal to stock is accepted requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-9): sensitivity_proof.instance_id does not match the manifest instance
- test instance @api @regression LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 higher quantity wins, guest-only kept, no-stock dropped
- test instance @api @regression LOCAL-1_TC_005 guest quantity above stock is capped at stock requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-5): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_005 guest quantity above stock is capped at stock
- test instance @api @regression LOCAL-1_TC_008 quantity zero (0) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity zero (0) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 quantity negative (-1) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity negative (-1) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 quantity above-max-1000 (1000) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity above-max-1000 (1000) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 quantity fraction (1.5) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 quantity fraction (1.5) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 bookId zero (0) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 bookId zero (0) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 bookId negative (-3) is refused with VALIDATION_ERROR requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 bookId negative (-3) is refused with VALIDATION_ERROR
- test instance @api @regression LOCAL-1_TC_008 edge quantity 1 is accepted requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-8): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_008 edge quantity 1 is accepted
- test instance @api @regression LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged requires current sensitivity proof: its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 out-of-stock book is refused with OUT_OF_STOCK, cart unchanged
- test instance @api @regression LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-9): its receipt is for other bytes (test_content_hash 4e426dc123ef70c4f45a874f368b346cd2cef37f8e8b873e31b1f066efad8051, the test file now hashes aac099d3347a985ce415b5d176bfe295f32556fd354fbf0fe46a376fc028d74f) and other code: probe the current bytes again with probe_by_code.py --instance @api @regression LOCAL-1_TC_009 one over stock with cart contents is INSUFFICIENT_STOCK, cart unchanged
- test instance @regression LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-3): its receipt is for other bytes (test_content_hash 52e579f5278bd3ec84395593d474ad105c3559086f040101fae4efc3f69c6e5d, the test file now hashes f8d7d5297f4e545977a4fd77e80d5afed6d0b4d6f551a9b2b798600d3f9f7e0c) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_003 book not in cart: one line quantity 1, badge 1, off the wishlist; undo path repeats it
- test instance @regression LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-4): its receipt is for other bytes (test_content_hash 52e579f5278bd3ec84395593d474ad105c3559086f040101fae4efc3f69c6e5d, the test file now hashes f8d7d5297f4e545977a4fd77e80d5afed6d0b4d6f551a9b2b798600d3f9f7e0c) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_004 book already in cart with quantity 2: one line, quantity 3, off the wishlist
- test instance @regression LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-13): its receipt is for other bytes (test_content_hash 395f28035d735e92d08510940ffe4dfbe034a1d9914b46cfcde99fb65cc528a6, the test file now hashes c1065221ef6a8f204e21866a6609424633fd29bddcf6b79d36bab778cce6129e) and other code: probe the current bytes again with probe_by_code.py --instance @regression LOCAL-1_TC_013 badge is the sum of quantities, total follows add, update and remove
- test instance @regression LOCAL-1_TC_017 P-bookread-timeout failed book read shows an error or the lines, not a blank page requires current sensitivity proof: no sensitivity receipt
- test instance @regression LOCAL-1_TC_017 P-putfail-error500 failed quantity change shows an error, stored quantity stays 1 requires current sensitivity proof: no sensitivity receipt
- test instance @regression LOCAL-1_TC_017 P-putfail-timeout failed quantity change shows an error, stored quantity stays 1 requires current sensitivity proof: no sensitivity receipt
- test instance @regression LOCAL-1_TC_017 P-deletefail-error500 failed remove shows a message, the line stays requires current sensitivity proof: no sensitivity receipt
- test instance @regression LOCAL-1_TC_017 P-deletefail-timeout failed remove shows a message, the line stays requires current sensitivity proof: no sensitivity receipt
- test instance @regression LOCAL-1_TC_018 P-removefail-error500 failed remove shows an error, the book stays on the wishlist requires current sensitivity proof (looked in tests[].sensitivity_proof and in obligation binding OB-18): sensitivity_proof.instance_id does not match the manifest instance
- ledger: TS-6 is `failed:untriaged` (LOCAL-1_TC_006)
- ledger: TS-17 is `failed:untriaged` (LOCAL-1_TC_017)
- coverage: OB-3 — current sufficient evidence incomplete
- coverage: OB-4 — current sufficient evidence incomplete
- coverage: OB-5 — current sufficient evidence incomplete
- coverage: OB-7 — current sufficient evidence incomplete
- coverage: OB-8 — current sufficient evidence incomplete
- coverage: OB-9 — current sufficient evidence incomplete
- coverage: OB-10 — current sufficient evidence incomplete
- coverage: OB-11 — current sufficient evidence incomplete
- coverage: OB-12 — current sufficient evidence incomplete
- coverage: OB-13 — current sufficient evidence incomplete
- coverage: OB-14 — current sufficient evidence incomplete
- coverage: OB-15 — current sufficient evidence incomplete
- coverage: OB-16 — current sufficient evidence incomplete
