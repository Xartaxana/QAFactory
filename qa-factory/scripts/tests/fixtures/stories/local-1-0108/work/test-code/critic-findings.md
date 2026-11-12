# Critic findings - S5-qa-code-critic-2 (LOCAL-1, window 1)

Roll-call: LOCAL-1_TC_004 -> cart.spec.ts:7 (Then 1 line 20, Then 2 line 19); TC_005 -> :24 (Then 1-4 at 29-30, 41-42, 44, 54); TC_011 -> :58 (Then 1 at 77-78, Then 2 at 73-74, Then 3 at 81-84); TC_013 -> :88 (Then 1 at 93/98, Then 2 at 100-101).

Probes: all four `incomplete` (the probe mutated the planned assertion, the run failed on an assertion, but the Playwright report gave no frame site the tool can read). cause: tooling. Instances are unverified, not rejected.

Static review: no sleep, own data (shop.book / guest / clearCart), Thens ordered independent-first, counts asserted before index. No test_defect found.

Notes:
- F-1 (TC_011 Then 1, lines 76-79) cause: test_defect, non-blocking remark: refusal is `>=400 && <500`; plan words "INSUFFICIENT_STOCK-class error". Cart-unchanged and boundary asserts partly discriminate the cause; naming the product's error code/body would discriminate fully. Not a blocker.
- Plan-name deviations reported by s5_precheck (plan ids tc004... vs titled tests) are code-checked, not re-reported; the author should declare them in `deviations`/`plan_remarks`.

## Window S5-qa-code-critic-3 (LOCAL-1_TC_004, 005, 011, 013) - static review

Read in full: tests/api/cart/cart.spec.ts, core/clients/bookstoreApi.ts, core/fixtures/cart.fixture.ts.
Roll-call: TC_004 -> cart.spec.ts:7 (Then 1,2); TC_005 -> :24 (Then 1-4); TC_011 -> :58 (Then 1-3); TC_013 -> :88 (Then 1,2). Each covered by an instance that names it.
Static: own data per test (marked books, fresh shopper), teardown in the fixture, no sleeps, no asserts in the client/fixture, Then 2 of TC_004 placed before the price-dependent Then. No stricter_assert or invented_expectation found. TC_011 uses a broad 4xx for the refusal but also asserts unchanged cart state and the 3+2 boundary (note, not a finding).
- TC_004, TC_013: red on the product (contradicts_requirement; cart line has no price field). Verdict approved; probe not applicable: red.
- TC_005: probe_by_code returned incomplete (cause: tooling): the TypeScript failure wording does not match the assertion_probes row. Record work/probes/cart.spec.@api-@regression-LOCAL-1_TC_005-*.json. Verdict unverified.
- TC_011: probe_by_code returned not_executed (cause: tooling): request tmp file path too long on Windows. Verdict unverified.
- tooling: window_record.py reports stale_review / no critic_verdict for rows whose manifest trace_binding.test_content_sha (350d5e56...) differs from the current file sha (f073861c...); the author's trace_binding is stale, not the review.

## Window S5-qa-code-critic-6 (LOCAL-1_TC_003, LOCAL-1_TC_006) - static review

Read in full: tests/e2e/cart/cart.spec.ts, core/pages/BookDetailPage.ts, CartPage.ts, core/fixtures/cart.fixture.ts.
Roll-call: TC_003 -> cart.spec.ts:79 (Then 4 at 92-93, Then 3 at 98, Then 2 at 104-106, Then 1 at 110-113); TC_006 -> :120 (Then 1 at 144-145, Then 2 at 152-153).
Static: own data per test, teardown in fixture, no sleeps, locators in page objects, independent Thens use expect.soft, the price Then last. No invented_expectation, no stricter_assert.
- TC_003 is RED by requirement (GET /api/cart line has no price, line 113): it asserts the Then and fails on the product; accepted red with its contradicts_requirement row, no probe.
- F-1 TC_003 (cart.spec.ts:90, BookDetailPage.ts:19) cause: test_defect, blocking. Then 4 asks that the quantity field keeps "3" whole and keeps focus; the field value goes to the page state and redraws. `fill('3')` writes the whole value in one step, so it covers a level less than the case asks: a lost character or lost focus on keystroke cannot be seen. Expected: enter the quantity by keystrokes (`pressSequentially`, in the page object's enterQuantity or a separate method) with the field value and focus asserted after the keystrokes, with a multi-digit control if the case data has one.
- TC_006: green; Thens read through the UI and through a fresh API session; quantity 2 and a single line asserted, no price needed. Its quantity entry uses fill too (line 131), but the Then does not concern typing, so no finding. Probe: not run, person's word (probe gap tooling:typescript, not receipted); cause: tooling. Verdict unverified.
