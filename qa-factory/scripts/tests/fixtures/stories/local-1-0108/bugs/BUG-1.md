---
id: BUG-1
title: Invalid quantities (0, -1, 1.5, abc) are rewritten to a valid number and added to the cart instead of being rejected
severity: minor
status: Open
area: cart
found_by: LOCAL-1_TC_007
violates: requirement:R-8
created: 2026-11-02
impact: degraded
source_draft: work/bug-drafts/qty-invalid-input-coerced.json
gate_b_decision_id: gateB-LOCAL-1
confirmation: unconfirmed
cases: ["LOCAL-1_TC_007","LOCAL-1_TC_008","LOCAL-1_TC_009","LOCAL-1_TC_012"]
requirements: ["R-8","R-9","R-10"]
no_case_reason: 
---

## Initial state

A signed-in user is on the product page of an in-stock book; the cart does not contain that book; the quantity field is editable.

## Reproduction steps

1. Sign in and open the product page of an in-stock book.
2. Type 0 into the quantity field and click Add to Cart; then open the cart page and watch the message area and the quantity field.
3. Repeat with -1.
4. Repeat with 1.5.
5. Repeat with abc (the field may only accept it as a number input; use paste or keyboard entry).

## Expected result

Per requirement:R-8 (0), R-9 (-1, 1.5) and R-10 (abc), confirmed by the person at gate A (Q1 a: invalid quantities are rejected with a message and nothing is added): each value is rejected with a clear message, nothing is added to the cart, the field keeps the typed value.

## Actual result

One root cause, MyBooks/src/components/pages/BookDetailPage.tsx:164 `setQuantity(Math.max(1, parseInt(v) || 1))`: the invalid input is rewritten and the add proceeds with no message. Observed per input: 0 -> field shows 1, cart line quantity 1; -1 -> field shows 11, cart line quantity 1; 1.5 -> field shows 1, cart line quantity 1; abc -> field shows 1, cart line quantity 1.

## User impact

A shopper who mistypes a quantity gets a different quantity silently added to the cart, with no message, and can place an order for an amount they did not choose. Impact class: degraded.

## Evidence

- Failing tests: LOCAL-1_TC_007 [tc007_zero], LOCAL-1_TC_008 [tc008_negative], [tc008_non_integer], LOCAL-1_TC_009 [tc009_non_numeric] (qa-factory/artifacts/LOCAL-1/work/triage.json, run-report.json); LOCAL-1_TC_012 also covers the class.
- Draft: qa-factory/artifacts/LOCAL-1/work/bug-drafts/qty-invalid-input-coerced.json (merged by the person's decision, one bug for all inputs).
- Defect location: MyBooks/src/components/pages/BookDetailPage.tsx:164.
- Dedup search: grep of bugs/ for "quantity", "BookDetailPage", "coerc" - no match (bugs/ did not exist).
- Authorization: gate B decision gateB-LOCAL-1 (pipeline.json gates.B; words in state/words/gateB-20261102-approved.txt and gateB-20261102-merge-bugs.txt).

