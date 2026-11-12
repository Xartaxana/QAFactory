# Critic findings, window 6 (S5-qa-code-critic-9): LOCAL-1_TC_010, LOCAL-1_TC_012

Read in full: tests/e2e/cart/cart.spec.ts (lines 150-307), case TC_012 at cv_875562d9cfed74770120, manifest rows, author handoff S5-qa-automator-9.
Probes: none run. Person's word: probe gap tooling:typescript, not receipted. Green rows are `unverified` (could not verify, not a rejection); red rows `approved` (red is the product, contradicts_requirement).

## Roll-call

| case | instance | status | verdict |
|---|---|---|---|
| TC_010 | a quantity above stock is refused with the available number shown | green | unverified |
| TC_012 | quantity_class_behaves[p_one], [p_ten], [p_234], [p_contains_zero], [p_multi_digit], [p_stock_boundary], [p_above_stock] | green | unverified |
| TC_012 | quantity_class_behaves[p_zero], [p_negative], [p_non_integer], [p_non_numeric] | red (contradicts_requirement, BookDetailPage.tsx:164) | approved |

## Judgements asked by the conductor

- Expectation change (removed unit-price = P assert, red 0740a4d2923d0ffa7306 -> green 475622e3599d811dd75c): `legitimate_correction`. Then 1 names quantity and subtotal (value x P), not the unit price. The removed assert was stricter than the Then. The quantity assert (line 283) and subtotal assert (line 288) are unchanged, so no value was bent toward the code. The price defect is already red in TC_001/TC_004.
- Shared grep selector_args (`LOCAL-1_TC_012 quantity_class_behaves\[` for all 11 instances): one instance's run executes all 11, red ones included. report_test_id is per instance, so results map correctly. Cost and probe-isolation issue, not a test defect. cause: tooling, non-blocking. Fixing it means a per-id grep; the author may anchor it with the partition id.
- "Then 7 pasted variant not exercised": Then 7 of the case lists "pasted". The test covers whole entry and clear-and-re-enter only. The author declared it. It is a coverage gap of the Then, not a masked one. cause: test_defect, non-blocking remark: add a paste path (fill or clipboard) to the helper in a later round, or hand the pasted part to the person with a `handed_to_person` row.

## Remarks (non-blocking)

- R-1 (test_defect, remark): line 288 `toContainText((value*price).toFixed(2))` is a substring match: "1.50" is found inside "11.50". Use an exact money text from the subtotal locator. Price is 1.5, so the collision is real for e.g. value 1 vs 11 (inside the same row).
- R-2 (mechanical): line 256 reads `price` for invalid classes where it is unused; move it into the valid branch.
- R-3 (note, no cause): p_non_numeric asserts `not.toHaveValue('9')` only: the weakest form the case allows (CC-1), fine as it stands.

## Checked and clean

Order of asserts: independent Thens (API cart, Then 2/6) come before the visible-message assert. Data: each test creates its own book (stock 300 or 4) and a fresh context, cart read per shopper. No sleeps; waits are on conditions (addToCartAndAwait, addToCartAndSettle). No invented expectations: values from R-8..R-11, R-13. TC_010 asserts available number 4 and no cart line. 1a: the locators are page-object ones (availableMessage(n)).

## Not verified
All 7 green TC_012 rows and TC_010: no live receipt (tooling:typescript, person's word). Static review found no defect.

Manifest checks after the patch: 28 test rows, each with case/file/status; 41 then_bindings unchanged; earlier verdicts intact.
