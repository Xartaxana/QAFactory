# LOCAL-1 — test report

**The change.** The story adds books to the shopping cart: from the product page, the catalog card and by moving a wishlist item, for guests and signed-in users, with quantity and stock rules and a price per line. The quick view add path is not implemented in the application, so it could not be verified; you accepted that as a gap. The TypeScript tests were accepted without a deliberate-break probe, so no green test here is "verified by mutation". Eleven red instances are defects of the case text, not of the product: the price check reads the cart API, which carries no price field, while the cart page price is right. Fixing that Then is left to you. Two manual cases (price update during an add, network interruption during an add) were not run because the manual capture tool could not sign in; you accepted that as a stand gap.

<!-- facts:verdict -->
**Verdict: not ready to ship as is.** Because TS-1 (LOCAL-1_TC_001) failed in the run - the triage verdict is CASE_DEFECT. Product bugs: 0 confirmed, 1 unconfirmed. Of 26 requirements: 0 proven by tests, 4 with a product bug, 19 not proven, 1 waiting for a person, 2 deferred by your decision. A person must check 0 cases; 1 case is closed only partly. 0 green tests count as proven. 15 tests could not be verified by the code critic. 30 open reasons in the checks are the factory's own bookkeeping — you are told about it, nothing is asked of you. 13 behaviour(s) no test proves because of the factory's tools or coverage; they stay unproven.

`delivery_ready: no — TS-1 (LOCAL-1_TC_001) failed in the run - the triage verdict is CASE_DEFECT`
<!-- /facts:verdict -->

Notation: R-n — a requirement (the list with its text: understanding.md, "What we verify");
<case id> — a test case, its id in the form the project uses (test-plan.md, "Case appendix");
TS-n — a plan row; BUG-n — a bug file in `qa-factory/bugs/`.

<!-- facts:proven -->
## Proven — 0 green tests

On a build you confirmed, the web tests ran: `Da, na stende pravilnaya versiya, mozhno testirovat (MyBooks a25b080, npm run start)` (2026-11-02). The factory did not read which build the stand runs.

No green test is counted as proven.

Unknown which tests changed after a red run — a gap of the factory's tool, not of the product: a red run has no later pass for LOCAL-1_TC_004 cart unit price and total equal the catalog price, LOCAL-1_TC_013 maximum quantity is added with the right subtotal, cart.spec.@api @regression LOCAL-1_TC_004 cart unit price and total equal the catalog price, cart.spec.@api @regression LOCAL-1_TC_013 maximum quantity is added with the right subtotal, cart.spec.@api @regression LOCAL-1_TC_015 adding the same product twice gives one line with the summed quantity, cart.spec.@api @regression LOCAL-1_TC_016 several products give one line each and a summed total and 11 more, and the test file that would say whether the test still exists cannot be read by this reader.

Formal test execution: 0 tests, 43 executions. Exploratory probes: 0 probes; 0 findings and 1 gap (what the factory could not check) — not tests, not counted as proven.
<!-- /facts:proven -->

<!-- A green test the code critic could not verify is not proven and is not counted in <N>: it
     stands only under "Left with you". When every green test is such a test, the heading reads
     `## Proven — 0 green tests`, never left out.

     The critic's words: "reviewed by the code critic" · "reviewed by the code critic, fixes
     named" · "rejected by the code critic" · "the code critic could not verify it" · "review
     not recorded". The level words say how far the test's own check was shown to work: "the
     check is live" (its assertion fails when made false) · "catches a broken product" (a
     deliberate break of the product made it fail) · "not probed (unchanged test)" · "not
     probed (handed to the person)" (a case this test proves was handed to a person, so no live
     check is asked of it) · "proof level unknown (the test file cannot be found)". "Review not
     recorded" means the critic never gave a verdict (the factory's own round cap): the test is
     green, but nobody has shown that its check fails when it should. -->

<!-- Checked by hand: what an agent checked in the running product, one line per case planned for it, written
     by code (`report_facts.py`) and never by the scribe. `n` counts the cases with a valid record, `m` the
     cases planned for it; a case with no valid record reads "not checked" and never stands under Proven.
     "Before" is what the requirements say the product did; "not recorded by the requirements" when they say
     nothing. An inconclusive check counts toward nothing. -->
<!-- facts:manual-checks -->
## Checked by hand — 0 of 2

- **LOCAL-1_TC_022** (R-24) — "If Q7 = a (person's answer): the cart line for B is priced 6.00 (the price shown when the add was made, not the updated 8.00) and subtotal equals 6.00 x quantity; otherwise (before) the line is priced 8.00 and the shopper is told of the change. / The add causes no error: the add response is a 2xx, not an unhandled 5xx, and the line price equals one of the two prices (6.00 or 8.00), never a third value or zero. Cart is read from `GET /api/cart` after both actions settled, for B only." — not checked: the stand could not be verified — login by code: this project's sign-in is not an HTTP request the factory knows (environment.access.kind harness_command); nothing was sent; record manual_capture.login.http in config.json (path and token_field), or null if this kind of capture needs no login; a screen case signs in with fill-account steps
- **LOCAL-1_TC_023** (R-25) — "The shopper sees an error or retry message after the interruption, not a success message and not a silent nothing; the page stays usable (no blank screen). / If Q8 = a (person's answer): after the network returns the add is completed with the quantity the user chose, so `GET /api/cart` holds exactly one line for B with quantity 3 (not 1); if the add still fails after the network returns, the user sees a message asking to try again. Otherwise (before): the page told the user to retry and `GET /api/cart` holds no line for B until the retry is made. / No duplicate: after the interruption and any retry `GET /api/cart` holds at most one line for B and its quantity is 3, the quantity of the one chosen add, never 6." — not checked: no record was written
<!-- /facts:manual-checks -->

<!-- facts:bugs -->
## Product bugs — 0 confirmed · 1 unconfirmed

1. **minor · R-8, R-9, R-10 · LOCAL-1_TC_007, LOCAL-1_TC_008, LOCAL-1_TC_009, LOCAL-1_TC_012** — Invalid quantities (0, -1, 1.5, abc) are rewritten to a valid number and added to the cart instead of being rejected (BUG-1) (unconfirmed — nobody has reproduced it; it counts toward nothing) — file: bugs/BUG-1.md · tracker: not sent — the project keeps bugs in markdown

BUG-1 lies in the story's own folder, not in the project's bug folder; it is counted anyway. This is the factory's own bookkeeping — nothing is asked of you.
<!-- /facts:bugs -->

<!-- Review gaps: the tests the code critic rejected whose window closed anyway because its repair limit was spent, written by
     code (`report_facts.py`) and never by the scribe. One line per window, then one line per test with what the critic said,
     what it expected and what to fix; a test with no recorded remark says so. Runs of S7 left failing stand under their own
     heading. With nothing to list the block says so in one line. -->

<!-- facts:exploratory -->
## Exploratory findings and unresolved questions

### Observations

- ~~nothing observed: the capture tool could not sign in; no request was sent~~ — corrected later: the investigation ended before this target

### Unresolved questions

none

### Coverage gaps

- LOCAL-1_TC_022 — nothing observed: the capture tool could not sign in; no request was sent — not checked again — missing: not investigated - the investigation ended before this target — why it is not a bug: manual_capture.login.http not recorded; the person accepted this as a stand gap (state/words/s6-manual-login-gap.txt)
<!-- /facts:exploratory -->

<!-- facts:review-gaps -->
## Review gaps — 0 tests the code critic rejected

None: the code critic left no test rejected.

### Windows over the cap — 1

Window 5 over the cap: 3 cases, cap 2.
<!-- /facts:review-gaps -->

## Left with you

1. **An unconfirmed expectation: what happens after the session expires (R-26, no case).** To check: answer Q9: after session expiry, must the system extend the session, or ask for login and then add the product? There is no test: the plan marks it as not observable in code. Needed: your answer to which of the two readings is right; accept the risk or defer with a reminder.
2. **A guest's add is kept by the cookie (R-5, LOCAL-1_TC_005).** To check: the guest add is accepted with no redirect to login, the same cookie sees the line for book B with quantity 1, an anonymous context sees none, and the cookie is persistent. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
3. **An out-of-stock book cannot be added (R-2, LOCAL-1_TC_002).** To check: after the UI attempt the cart has no line for the book and the badge is unchanged, a message names the out-of-stock state, and the API attempt is not a 2xx. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
4. **A signed-in cart survives logout and login (R-6, LOCAL-1_TC_006).** To check: after login the cart page shows book B with quantity 2 and the cart API holds one line for it. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
5. **Quantity above stock is refused with a message (R-11, LOCAL-1_TC_010).** To check: a visible message states the available number (4) and the cart holds no line for the book. There is a test in the cart UI suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
6. **Stock check counts copies already in the cart (R-12, LOCAL-1_TC_011).** To check: both second requests are refused with a 4xx, the line quantities stay 3 and 1, and a third add up to exactly the stock is accepted. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
7. **Quantity classes: valid values stored exactly, invalid ones rejected (R-13, LOCAL-1_TC_012).** To check: valid quantities are stored exactly as entered; zero, negative, fractional, non-numeric and above-stock values are rejected with a message and no line. There is a test with a variant per quantity class; the invalid ones are red because the product turns them into 1 (see Product bugs), and the code critic did not verify it. How: run it yourself after the product fix. Answer wanted: accept the risk.
8. **An extremely large quantity does not break the app (R-15, LOCAL-1_TC_014).** To check: each request gets a 4xx or is capped at most at the stock (10), never a 5xx, and the application still answers a normal add afterwards. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
9. **An unknown book id is refused (R-18, LOCAL-1_TC_017).** To check: the answer is 404 with the error code BOOK_NOT_FOUND and the cart gains no line. There is a test in the cart API suite; it is green, but the code critic did not verify it. How: run it yourself where you can. Answer wanted: accept the risk.
10. **A guest cart is merged at sign-in (R-22, LOCAL-1_TC_021).** To check: the guest item stays at the quantity the guest added, the higher quantity wins when both carts hold the book, and an item with no stock is dropped. There is a test; it is green, but the code critic could only read it, not run a deliberate-break check. How: run it yourself where you can. Answer wanted: accept the risk.

<!-- Every check the ledger leaves with the person has an item above - one per case, naming its R-n and its case
     id (`report_facts.py --check` names an item that is missing). The two code-owned blocks below stand LAST in the
     section and are never typed: what the person's gate B answers left with them (it exists only after the gate, and only
     when an answer did), and the plan's regression list, verbatim - it is always here and never changes the verdict.
     Nothing of yours goes after them. -->

<!-- facts:left-branches -->
### Branches left with you

- **BN-2** (R-8) — To check: A quantity of 0 is rejected with a clear message and nothing is added. Needed: LOCAL-1_TC_007 carries it, but no test or recorded check proves it
- **BN-3** (R-9) — To check: negative (-1) and fractional (1.5) quantities. Needed: LOCAL-1_TC_008 carries it, but no test or recorded check proves it
- **BN-7** (R-14) — To check: "maximum allowed" is not defined (stock vs the schema cap 999). Needed: LOCAL-1_TC_013 carries it, but no test or recorded check proves it
- **BN-10** (R-25) — To check: the system completes the action or notifies the user to retry. Needed: LOCAL-1_TC_023 carries it, but no test or recorded check proves it
- **BN-11** (R-26) — To check: the session is extended or a new login is asked. Needed: the role left it out, you have not said so: plan row TS-26 is `unverifiable`: No code observable (REF-8); two readings (BN-11); owner decides at gate A.
- **U-a929b15ff589** — To check: *Objective:* Verify that raising a cart line's quantity above available stock is rejected and the stored quantity stays unchanged. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-126d8bb02629** — To check: Book "Ariel" is in stock; read its real stock S0. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-b306bc733eb9** — To check: Initial quantity: 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-a9becee51472** — To check: Attempted cart quantity: S0 + 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-443c860e4a21** — To check: *Expected:* One line "Ariel" with quantity 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-a96b3e0b1a34** — To check: Change the line's quantity to S0 + 1 and commit it (Enter or blur). Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-640f71a6da65** — To check: *Expected:* A visible error states there is not enough stock. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-fb8e200cdf18** — To check: Reload the cart page. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-789949bf9f23** — To check: *Expected:* Line "Ariel" still shows quantity 1; cart badge shows 1. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
- **U-4e59f1300e2c** — To check: Cart line quantity is unchanged. Needed: the role left it out, you have not said so: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118)
<!-- /facts:left-branches -->

<!-- facts:regression -->
### Regression to run (from the plan approved at gate A)

No regression: the tests repository has no cart test (coverage_search tests: none) and the implementation source is current-code with no diff, so no existing test defends this blast radius; developers keep the application's own unit tests `src/lib/cartRules.test.ts` and `src/lib/validation/schemas.test.ts`.

Tests of this story (not regression): tests/api/cart/cart.spec.ts, tests/e2e/cart/cart.spec.ts
<!-- /facts:regression -->

<!-- facts:open-questions -->
## Open questions — 1 · 10 asked under "Left with you"

```
po_ba · Q4 (TS-26): after session expiry, must the system extend the session, or ask for login and then add the product?
```
<!-- /facts:open-questions -->

<!-- The null outcomes are split in two by the ledger's own facts, never by wording: what the PLAN decided not to check and
     the person approved at gate A (a plan row `skip` with its reason, a gate A waiver with their words) stands first,
     each with that reason verbatim; "Not proven" then holds the checks that COULD NOT execute (a manual check that did not
     answer, the stand, a deferral nobody worded), each with what stopped it. A red test under a waiver is neither: it
     is a bug. -->
<!-- facts:skipped-by-plan -->
## Skipped by the plan (approved at gate A)

- **R-7** — cosmetic, badge sum asserted inside TS-1 and TS-3; toast text goes to the Developers line (plan row TS-7, skipped by the plan) : risk: how it looks or reads is off; the behaviour holds; the plan's defect hypothesis: smoke
- **R-23** — the owner's answer leaves no implemented quick-view add path to verify inside add-to-cart scope (plan row TS-23, skipped by the plan) : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: smoke
<!-- /facts:skipped-by-plan -->

<!-- facts:not-proven -->
## Not proven, and what it costs

- **R-1** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: state @ product page add-to-cart
- **R-2** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: contract @ out-of-stock add rejection
- **R-3** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: boundary @ quantity selector to cart line
- **R-4** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: money can be charged, paid or counted wrongly in production; the plan's defect hypothesis: contract @ cart price vs book price
- **R-5** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: state @ guest cart session cookie
- **R-6** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: state @ signed-in cart across logout and login
- **R-11** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: boundary @ quantity above stock
- **R-12** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: state @ stock check with copies already in cart
- **R-14** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: boundary @ maximum allowed quantity
- **R-15** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: boundary @ extremely large quantity
- **R-16** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: state @ same product added twice
- **R-17** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: state @ several different products in cart
- **R-18** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: error-path @ unknown book id
- **R-19** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: seam @ add paths: product page, catalog card, wishlist
- **R-20** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: contract @ catalog card quantity
- **R-21** — red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... : risk: data can be lost or corrupted in production; the plan's defect hypothesis: data-loss @ wishlist move-to-cart
- **R-22** — its test ran green but is not counted as proven: the code critic has not approved it, or a live check of it is still owed; the code critic could not verify it : risk: data can be lost or corrupted in production; the plan's defect hypothesis: data-loss @ guest cart merge at sign-in
- **R-24** — the owner settled the expected price : risk: money can be charged, paid or counted wrongly in production; the plan's defect hypothesis: concurrency @ add during price update
- **R-25** — the owner settled which outcome is expected : risk: a flow keeps working, but worse than intended; the plan's defect hypothesis: error-path @ network interruption during add
- **R-26** — expectation unconfirmed, check not executed — Q9: before unknown, now unknown : risk: people can be stopped from finishing a flow they rely on; the plan's defect hypothesis: state @ add after session expiry
<!-- /facts:not-proven -->

<!-- facts:gate-a -->
## Decided at gate A

```
approve
R-8: a
R-9: a
R-10: a
Q1: a
Q2: a
Q3: a
Q4: b
Q5: a
Q6: a
Q7: a
Q8: a
Q9: b
vcs-1: accept go on on this branch as the person said
case_environment-1: accept gap accepted by the person
case_environment-2: accept gap accepted by the person, quick view is not implemented and goes in the test report as a gap
case_environment-3: accept gap accepted by the person
case_environment-4: accept gap accepted by the person
case_environment-5: accept gap accepted by the person
```
- S0 · the login this project records was refused: "Idti dalshe po moemu slovu (login verified manually: the login test passes in ~80s, the probe limit is 60s)"
<!-- /facts:gate-a -->

<!-- Decided at gate B: present only after the gate, and only with gate B's own words. Before the
     gate the heading is absent - never another gate's content under it. -->

<!-- facts:gate-b -->
## Decided at gate B

```
MR ne nado
Approved
```
- Bugs: BUG-1 (unconfirmed) in an unfiled draft and the story's own bugs folder.
- What went outward: not recorded
<!-- /facts:gate-b -->

## Factory defects — nothing is wanted from you

The factory's count and what happened differ in places. Fifteen green tests carry no code-critic verdict, because the review windows were accepted by you without a recorded review, and one review window had more cases than its cap allows; this is why green tests appear under Left with you instead of Proven. The branch accounting was waived by you as well.

The factory's open bookkeeping reasons in the checks (30) and the 13 behaviours no test proves come from its own tools and coverage, not from the product; the ledger counts the eleven case-text defects as failures, while here they are named as case defects. Nothing here is yours to repair.

<!-- facts:size -->
## Size

Forecast: **L** (6 functions: Add a book from the product page, Quantity validation on add, Stock limits on add, Cart composition and price after adds, Cart persistence for guest and signed-in user, merge, Other add paths (catalog card, wishlist, quick view)) — the requirements weigh 50 (each weighted by its priority and area); the test ceiling is 28, over it by 22.
Fact: **L** — 22 testable requirements, 26 plan rows, 24 cases, 34 tests.
Difference: none.
Attachments were not turned into requirements: 1 (localhost). They were offered to you at the plan gate.
19 linked tickets were left out and not reconciled: RUN-2026 (not_relevant), TC-001 (not_relevant), TC-002 (not_relevant), TC-003 (not_relevant), TC-004 (not_relevant), TC-005 (not_relevant), TC-006 (not_relevant), TC-007 (not_relevant), TC-008 (not_relevant), TC-009 (not_relevant), and 9 more.
184 parts of the ticket were read as no obligation: context links and stand description, no verifiable statement, reproduction setup/meta of the bug, test-case setup/boilerplate repeated per case, heading, business value, not testable behaviour, test-document metadata, defect narrative/data model, already fixed (comment) or outside add-to-cart behaviour, index of the individual cases of the parent test document.
What the change touches: no implementation diff was read for this story (current-code). The implementation of this story is read from the current code, not from a recorded diff, so there are no hunks to label and no grounding rows.
<!-- /facts:size -->

<!-- facts:where-to-look -->
## Where to look

- understanding.md — sections: Why this change; Size; What we verify; What we do not verify, and why; What else the change may touch; Questions without which testing is pointless
- test-plan.md — sections: Plan; Owner questions for gate A (register questions Q1 to Q6); Recommended regression; Case appendix; Given; When; Then; Notes (self-probe); Obligation coverage
- retro.md — sections: What went wrong, and what to do about it; Time; Cost (copied from retro-numbers.md, INCOMPLETE); Marathons and what they spent turns on; Rejects, rework, runs; Gate-A disposition overrides; Estimate vs actual; What recurred (routed, see below); The human's answer to the retro question
- the appendix below — every requirement, case and test with its result
- the factory's own signals during this run: 2 signals, kept in the factory's own log
<!-- /facts:where-to-look -->

## Appendix — traceability

Sorted by requirement, then by case. Result vocabulary: **pass** · **BUG-n** · **wait** (the case is handed to a person) · **blocked** (the stand) · **not run** · **unreachable** (the scenario cannot occur in the product) · **deferred** (a recorded decision) · **not planned**. Level: unit · component · api · integration · e2e-ui · manual-agent · manual-human. Shape: new · extend · reuse · parameterize · consolidate.

Product bugs — 1 unconfirmed. An `unconfirmed` bug is a draft nobody has reproduced yet — neither a person at gate B nor a second run on another stand — and it counts toward nothing.

Test files: **S** = `tests/e2e/cart/cart.spec.ts`, **C** = `tests/api/cart/cart.spec.ts`.

| R | What we verify | TC · Then | Test | Level · shape | Result | Basis |
|:--|:--|:--|:--|:--|:--|:--|
| R-1 | An in-stock book is added once with the right price from the product page | LOCAL-1_TC_001<br>Then 1–3 | S `..ight price from the product page` | e2e-ui<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-2 | An out-of-stock book cannot be added to the cart | LOCAL-1_TC_002<br>Then 1–3 | S `..book cannot be added to the cart` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-3 | Quantity 3 is added and the cart shows 3 with the right subtotal | LOCAL-1_TC_003<br>Then 1–4 | S `.. shows 3 with the right subtotal` | e2e-ui<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-4 | The cart price and total equal the book price | LOCAL-1_TC_004<br>Then 1–2 | C `..nd total equal the catalog price` | api<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-5 | A guest adds a book without logging in and the cart persists with the same ... | LOCAL-1_TC_005<br>Then 1–4 | C `.. and the cart follows the cookie` | api<br>new | **pass** | the code critic could not verify it |
| R-6 | A signed-in cart survives logout and login | LOCAL-1_TC_006<br>Then 1–2 | S `..n cart survives logout and login` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-7 | After a successful add a success message is shown and the cart icon/badge shows ... | TS-7 | — | — | **deferred** | cosmetic, badge sum asserted inside TS-1 and TS-3; toast text goes to the Developers line |
| R-8 | Quantity 0 is rejected with a message and nothing is added | LOCAL-1_TC_007<br>Then 1–3 | S `..007 invalid_`<br>`quantity_rejected` [tc007_zero] | e2e-ui<br>parameterize | **BUG-1**<br>unconfirmed | @regression LOCAL-1_TC_007 invalid_quantity_rejected[tc007_zero] ... |
| R-9 | Negative and fractional quantities are rejected and never rounded | LOCAL-1_TC_008<br>Then 1–3 | S `..008 invalid_`<br>`quantity_rejected` [tc008_negative, tc008_non_integer] | e2e-ui<br>parameterize | **BUG-1**<br>unconfirmed | @regression LOCAL-1_TC_008 invalid_quantity_rejected[tc008_negative] ... |
| R-10 | A non-numeric quantity is rejected with an error and nothing is added | LOCAL-1_TC_009<br>Then 1–3 | S `..009 invalid_`<br>`quantity_rejected` [tc009_non_numeric] | e2e-ui<br>parameterize | **BUG-1**<br>unconfirmed | @regression LOCAL-1_TC_009 invalid_quantity_rejected[tc009_non_numeric] ... |
| R-11 | A quantity above stock is refused with the available number shown | LOCAL-1_TC_010<br>Then 1–2 | S `.. with the available number shown` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-12 | A second add that would exceed stock is refused and the cart is unchanged | LOCAL-1_TC_011<br>Then 1–3 | C `..efused and the cart is unchanged` | api<br>new | **pass** | the code critic could not verify it |
| R-13 | Every quantity class, valid and invalid, behaves as required on the product page | LOCAL-1_TC_012<br>Then 1 | S `..TC_012 quantity_`<br>`class_behaves` [6 variants] | e2e-ui<br>parameterize | **pass** | the code critic could not verify it |
| R-13 | Every quantity class, valid and invalid, behaves as required on the product page | LOCAL-1_TC_012<br>Then 2–4 | S `..TC_012 quantity_`<br>`class_behaves` [4 variants] | e2e-ui<br>parameterize | **BUG-1**<br>unconfirmed | @regression LOCAL-1_TC_012 quantity_class_behaves[p_zero]: cart.spec.ts:258:3 ... |
| R-13 | Every quantity class, valid and invalid, behaves as required on the product page | LOCAL-1_TC_012<br>Then 5 | S `..TC_012 quantity_`<br>`class_behaves` [p_above_stock] | e2e-ui<br>parameterize | **pass** | the code critic could not verify it |
| R-13 | Every quantity class, valid and invalid, behaves as required on the product page | LOCAL-1_TC_012<br>Then 6–7 | S `..TC_012 quantity_`<br>`class_behaves` [11 variants] | e2e-ui<br>parameterize | **BUG-1**<br>unconfirmed | @regression LOCAL-1_TC_012 quantity_class_behaves[p_zero]: cart.spec.ts:258:3 ... |
| R-14 | The maximum allowed quantity is added with the right subtotal | LOCAL-1_TC_013<br>Then 1–2 | C `..is added with the right subtotal` | api<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-15 | An extremely large quantity gives an error or a limit and the app stays up | LOCAL-1_TC_014<br>Then 1–3 | C `.. or a limit and the app stays up` | api<br>new | **pass** | the code critic could not verify it |
| R-16 | Adding the same product twice gives one line with the summed quantity | LOCAL-1_TC_015<br>Then 1–2 | C `..ne line with the summed quantity` | api<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-17 | Several products give one line each and a summed total | LOCAL-1_TC_016<br>Then 1–2 | C `..one line each and a summed total` | api<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-18 | A nonexistent book is refused with 404 BOOK_NOT_FOUND | LOCAL-1_TC_017<br>Then 1–2 | C `..NOT_FOUND` | api<br>new | **pass** | the code critic could not verify it |
| R-19 | Catalog card and wishlist paths obey the same add rules as the product page | LOCAL-1_TC_018<br>Then 1–4 | S `..path_obeys_the_add_`<br>`rules` [3 variants] | e2e-ui<br>parameterize | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-20 | The catalog card adds the book to the cart with the right line | LOCAL-1_TC_019<br>Then 1–2 | S `.. to the cart with the right line` | e2e-ui<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-21 | Moving a wishlist item to the cart adds it and removes it from the wishlist | LOCAL-1_TC_020<br>Then 1–3 | S `..and removes it from the wishlist` | e2e-ui<br>new | **blocked** | red run, triaged CASE_DEFECT: The case pins the unit price to a field of GET /api/cart, but the API CartItem ... |
| R-22 | A guest cart is merged at sign-in without losing items | LOCAL-1_TC_021<br>Then 1–3 | S `.. at sign-in without losing items` | e2e-ui<br>new | **pass** | the code critic could not verify it |
| R-23 | A product can be added from the quick view and appears in the cart with the ... | TS-23 | — | — | **deferred** | the owner's answer leaves no implemented quick-view add path to verify inside add-to-cart scope |
| R-24 | Adding a book while its price is updated keeps the price shown at add time | LOCAL-1_TC_022 | — | manual-agent | **not run** | the owner settled the expected price |
| R-25 | An interrupted network during add ends with the chosen quantity added or a ... | LOCAL-1_TC_023 | — | manual-agent | **not run** | the owner settled which outcome is expected |
| R-26 | Adding after session expiry extends the session or asks for login, and the ... | TS-26 | — | — | **wait** | expectation unconfirmed, check not executed — Q9: before unknown, now unknown |
