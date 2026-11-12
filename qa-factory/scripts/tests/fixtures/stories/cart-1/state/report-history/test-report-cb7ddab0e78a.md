# CART-1 — test report


**The change.** CART-1 covers Add to Cart in MyBooks, checked against the current code: adding a book from the catalog or the detail page, stock limits, quantity and id validation, guest and account carts, merging the guest cart at sign-in, changing and removing cart items, the checkout quote and order reading the cart, and move-from-wishlist. No formal requirements exist; you ruled at gate A that the documented contract is the expected behaviour.

<!-- facts:verdict -->
**Verdict: <ready to ship | ready once you finish the checks left with you | not ready to ship as
is>.** <on "not ready": "Because" and the first product-owned reason, in the task's words>.
<N> product bugs (<severities>). Of <N> requirements, <n> are proven by tests,
<n> are not proven, <n> wait for a person, <n> deferred by your decision. <A test the code critic
could not verify is left with you and says so in one clause: "<n> tests could not be verified by
the code critic"; it makes the verdict "ready once you finish the checks left with you", never
"not ready".> <MR state in one clause, when known>

`delivery_ready: yes` | `delivery_ready: after_checks — <n> items are left with you` |
`delivery_ready: no — <the first reason, in words>`
<!-- /facts:verdict -->

Notation: R-n — a requirement (the list with its text: understanding.md, "What we verify");
<case id> — a test case, its id in the form the project uses (test-plan.md, "Case appendix");
TS-n — a plan row; BUG-n — a bug file in `qa-factory/bugs/`.

<!-- facts:proven -->
## Proven — <N> green tests

<Area> — `<test files>`:
- R-n <the requirement in words> (<case id>) — <the critic's words> · <the level words>
<!-- /facts:proven -->


<!-- facts:manual-checks -->
## Checked by hand — <n> of <m>

- **<case id>** (R-n) — "<the Then, quoted>" — before: <value · where it comes from | not recorded by the requirements> — now: <what the runner saw · link> — result: <passed | failed | inconclusive> — before the action: <link>; after the action: <link>
- **<case id>** (R-n) — "<the Then, quoted>" — not checked: <why, in words>
<or: Nothing to show: no case was planned for a manual check.>
<!-- /facts:manual-checks -->

<!-- facts:bugs -->
## Product bugs — <N confirmed · N unconfirmed>

1. **<Severity> · R-n · <case id>** — <one line of what is broken> — `<file:lines>`
<or: none found>
<!-- /facts:bugs -->

<!-- facts:review-gaps -->
## Review gaps — <n> tests the code critic rejected

Repair limit exhausted: <n> of <cap> rounds about the tests themselves (<cases>); you chose: <your answer>.
- `<function>` (<case id>) — the critic: "<problem>" — expected: "<expected>" — to fix: "<fix>"
- `<function>` (<case id>) — the critic's remarks were not recorded
<or: None: the code critic left no test rejected.>
<!-- /facts:review-gaps -->

## Left with you

1. **Unknown or sold-out book is rejected (R-3, CART-1_TC_001).** To check: the Then: "HTTP 404 BOOK_NOT_FOUND for an unknown book, 400 OUT_OF_STOCK for stock 0", and no cart row is created. There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
2. **Add beyond stock is rejected (R-4, CART-1_TC_002).** To check: the Then: "a third add past the stock of 5 answers 400 INSUFFICIENT_STOCK" and the row stays at 5. There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
3. **Repeat add accumulates (R-5, CART-1_TC_003).** To check: the Then: "exactly one row for the book, quantity 3 (1 + 2)". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
4. **Invalid quantity or id gets a stable error (R-6, CART-1_TC_004).** To check: the Then: "quantity 1 and 999 accepted; 0, fraction, string, over-limit and bad ids give 4xx with error and code, never 5xx". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
5. **Guest cart is separate from the account cart (R-7, CART-1_TC_005).** To check: the Then: "the account and another guest never see the first guest cart rows". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
6. **Guest cart merges on sign-in (R-8, CART-1_TC_006).** To check: the Then: "the higher quantity wins, capped at stock, sold-out dropped, no session gives 401". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
7. **Update and delete a cart item (R-11, CART-1_TC_007).** To check: the Then: "PUT sets the quantity within stock, over stock gives 400, DELETE removes the row". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
8. **A foreign cart item cannot be changed (R-12, CART-1_TC_008).** To check: the Then: "PUT and DELETE on another owner item give 404 CART_ITEM_NOT_FOUND and that cart is unchanged". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
9. **Add from the catalog shows badge and cart page (R-1, R-2, R-10, CART-1_TC_010).** To check: the Then: "the badge equals the sum of quantities (1) and the cart page lists the book with quantity 1". There is a test and it is green, but the code critic did not verify it: the factory probe tool cannot read Playwright TypeScript. How: run it yourself in the suite. Answer wanted: accept the risk (you already accepted the probe gap).
10. **Quote and order from the cart (R-15, CART-1_TC_009).** To check: Then 2, "the quote lists B1 x2 and B2 x1". There is a test and it is red on that one assert (the other four pass). The quote prices the cart (200) and rejects an empty cart (400) but has no items array; R-15 and the documented Quote schema do not ask for one, and the same happens without this story's change. Needed: your decision. Answer wanted: remove that check from the test, or add the items array to the requirement.
11. **Requirements with no case (R-9, R-13, R-16; no case id).** To check: guest cart after register then login (R-9, gate A question 2), NaN in the cart quantity box and unchecked fetches (R-13, question 3), concurrent add of the same book (R-16, question 4). There is no test: you answered "a" (in scope, a failure is a bug) at gate A, but the plan did not give them a case. Needed: plan cases for them, or a decision to defer.

<!-- facts:left-gate-b -->
### Added after gate B (from your answers)

- **<case id>** (R-n) — you said: "<their words>" — <how>
<!-- /facts:left-gate-b -->

<!-- facts:regression -->
### Regression to run (from the plan approved at gate A)

<the lines of test-plan.md's "Recommended regression", verbatim | no regression scope was recorded at S3 — a factory gap>
<!-- /facts:regression -->

<!-- facts:open-questions -->
## Open questions — <N>

```
<owner role> · <the question, in words>
```
<or: none>
<!-- /facts:open-questions -->

<!-- facts:skipped-by-plan -->
## Skipped by the plan (approved at gate A)

- **R-n** — <the plan's reason, or their gate A words, verbatim> : <the risk this leaves in production>
<!-- /facts:skipped-by-plan -->

<!-- facts:not-proven -->
## Not proven, and what it costs

- **R-n, R-m** — <what stopped the check, in words> : <the risk this leaves in production>
<!-- /facts:not-proven -->

<!-- facts:gate-a -->
## Decided at gate A

```
<gates.A.authorization_source, verbatim>
```
<the S0-S4 stage overrides, each with the person's words; an environment finding accepted at gate
A that binds no requirement or case, quoted, with "no case of this story was stopped by it">
<!-- /facts:gate-a -->

<!-- facts:gate-b -->
## Decided at gate B (<date>)

<the person's words verbatim and the S8/S9 overrides; where the bugs went; what went outward, or
"not recorded">
<!-- /facts:gate-b -->

## Factory defects — nothing is wanted from you

The factory's probe tool, which checks that a test's assertion fails when it should, cannot read this project's Playwright TypeScript tests, so none of the nine green automated tests could be verified by the code critic. That is why they stand under Left with you and not under Proven; it is the factory's gap, not a product finding.

The coverage check also lists obligations as unverified because it counts those same unverified tests and the three requirements the plan left without a case; those lines repeat the items above. Data left on the stand by the manual checks: books 110 to 113, a wishlist entry and a cart row.

<!-- facts:size -->
## Size

Forecast: **<size_initial>** — the requirements weigh <n> (each weighted by its priority and area); the <size> cap is <n>.
Fact: **<size_final>** — <n> testable requirements, <n> plan rows, <n> cases, <n> tests.
Difference: <forecast -> fact | none>.
<or: Forecast: unknown — no size was recorded, <why>>
<!-- /facts:size -->

<!-- facts:where-to-look -->
## Where to look

- understanding.md — what we verify and why (R-1…R-n), what we do not verify and why
- test-plan.md — the plan rows, priorities, why automated, the gate A questions, the
  regression commands, the case texts
- retro.md — time per stage, what went wrong and what to change | not written: <the person's
  skip words | the retro has not run>
- the appendix below — every requirement, case and test with its result
<!-- /facts:where-to-look -->

## Appendix — traceability

@@APP@@
