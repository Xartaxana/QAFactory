# Gate A — LOCAL-1

**Approve: `understanding.md`, `test-plan.md`.** This brief is a summary of them, not a document to approve.

**Plan** — 26 rows. Levels: api 8, e2e-ui 17, integration 1. Dispositions: automate 21, skip 1, unverifiable 4.
Pyramid: api/automate 8, e2e-ui/automate 13, e2e-ui/skip 1, e2e-ui/unverifiable 3, integration/unverifiable 1.
**Cases** — 24 pinned: [LOCAL-1_TC_001](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_001/cv_0ca72c610937bf16acf5.md), [LOCAL-1_TC_002](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_002/cv_d0150be267e7a21396f3.md), [LOCAL-1_TC_003](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_003/cv_430295a645a433dc3e44.md), [LOCAL-1_TC_004](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_004/cv_7396ea6d54e97abb53b5.md), [LOCAL-1_TC_005](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_005/cv_1e2fe984a158845705a5.md), [LOCAL-1_TC_006](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_006/cv_6eb2cabaed7969f5b81e.md), [LOCAL-1_TC_007](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_007/cv_046af312329b03af6938.md), [LOCAL-1_TC_008](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_008/cv_399811ae764fa23a33a4.md), [LOCAL-1_TC_009](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_009/cv_a7a0796939a1b5bab25c.md), [LOCAL-1_TC_010](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_010/cv_f2470b6bb042dcf661ab.md), [LOCAL-1_TC_011](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_011/cv_f943fc1ca0d050dd554f.md), [LOCAL-1_TC_012](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_012/cv_875562d9cfed74770120.md), [LOCAL-1_TC_013](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_013/cv_4efddd5f3c4f2fcbeb17.md), [LOCAL-1_TC_014](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_014/cv_65325bbd01a66b153365.md), [LOCAL-1_TC_015](qa-factory/artifacts/LOCAL-1/state/case-versions/LOCAL-1_TC_015/cv_c5f65d3008111d478843.md)....
**Critic** — verdict `approve_with_concerns`, roll-call 11 rows, every row reviewed.
Concerns carried to automation: LOCAL-1_TC_009, LOCAL-1_TC_019, LOCAL-1_TC_020, LOCAL-1_TC_021, LOCAL-1_TC_022, LOCAL-1_TC_023, LOCAL-1_TC_024
**Critic, per plan row (as gate A reads it)** — all 14 accepted; 1 with no case critic review.
**Size** — size **L** (6 functions: Add a book from the product page, Quantity validation on add, Stock limits on add, Cart composition and price after adds, Cart persistence for guest and signed-in user, merge, Other add paths (catalog card, wishlist, quick view)), the requirements weigh 50 (each weighted by its priority and area); the test ceiling is 28, **over it by 22**, 4 requirement(s) nothing here can verify. Arithmetic: work/sizing.json.

## After your approval
- [your call] the test repository has 6 uncommitted change(s) on branch `main` (HEAD 5cd21eb10194), and S5 writes test code into it: qa-factory/artifacts/, qa-factory/local-tickets/, qa-factory/records/journal.json…
- [your call] TS-7 carries a declared gap the next stage cannot close (S-1): toast text not asserted by an automated check
- [your call] TS-23 carries a declared gap the next stage cannot close (S-1): no implementation or observable
- [your call] TS-24 carries a declared gap the next stage cannot close (S-1): oracle and observable
- [your call] TS-25 carries a declared gap the next stage cannot close (S-1): oracle and observable
- (+17 more and … marks a line cut here — the whole list is under "Rehearsal of gate A" below)
- needs your word before your approval counts (22 open): [vcs-1], [case_environment-1], [case_environment-2], [case_environment-3], [case_environment-4], [case_environment-5], [case_preconditions-1], [case_preconditions-2], [case_preconditions-3], [case_preconditions-4], [case_preconditions-5], [case_preconditions-6], [case_preconditions-7], [case_preconditions-8], [case_preconditions-9], [case_preconditions-10], [case_preconditions-11], [case_preconditions-12], [case_preconditions-13], [case_preconditions-14], [case_preconditions-15], [case_preconditions-16] (each is under "Rehearsal of gate A" below) — or answer `approve as is` to approve over all of them, each recorded with your words

## Open questions (12)
- **Q1** [major, owner po_ba] Should the product-page quantity control reject 0, -1, 1.5 and non-numeric input, or may it turn them into 1?
  - the source says: "A quantity of 0 is rejected with a clear message and nothing is added." — REF-2 description
  - the source says: "setQuantity(Math.max(1, parseInt(e.target.value) || 1))" — MyBooks/src/components/pages/BookDetailPage.tsx:164
  - the source says: "Testirovat po trebovaniyu: proverit testom, chto 0 otklonyaetsya" — person's decision s1-conflict-20261101-234118
  - a) Requirement stands: invalid quantities are rejected with a message and nothing is added (from description)
    if chosen: tests expect rejection; the current UI behaviour is reported as a bug candidate at gate B
  - b) The UI coercion to 1 is intended (from code)
    if chosen: tests expect one copy added for invalid input and the tickets are changed
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q1: a`, `Q1: b` or `Q1: not needed`
  <!-- card Q1 2500ee9d524b708d70184bfb8829a1f8412d330f343ad90b7aed6f9ead2e41ae -->
- **Q2** [minor, owner po_ba] Quantity above stock: is the whole add rejected, or is only the available quantity added?
  - the source says: "Either no product is added or only available quantity is added" — REF-25 TC-010
  - the source says: "A visible error states that only S0 are in stock; Cart is empty" — REF-11
  - a) Reject the whole add with a message, cart unchanged (from description)
    if chosen: tests assert an empty cart and an error naming the stock
    what changes if you choose a:
    - nothing in the plan or the cases changes.
  - b) Add only the available quantity (from precedent)
    if chosen: tests assert the cart holds the stock quantity
    what changes if you choose b:
    - nothing in the plan or the cases changes.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q2: a`, `Q2: b` or `Q2: not needed`
  <!-- card Q2 86f5e03b70300081f3d7a21695decc09ffb32dee4eece303e5253fec205b912a -->
- **Q3** [major, owner po_ba] What is the maximum allowed quantity and what must a huge quantity (e.g. 999999) do?
  - the source says: "Set quantity to maximum allowed value" — REF-25 TC-008 / REF-23
  - the source says: "integer 1..999" — MyBooks/src/lib/validation/schemas.ts:41
  - a) Maximum equals stock (from description)
    if chosen: boundary tests at stock and stock+1; above is rejected
    what changes if you choose a:
    - nothing in the plan or the cases changes.
  - b) Maximum is the schema cap 999 (from code)
    if chosen: boundary tests at 999 and 1000, with stock large enough
    what changes if you choose b:
    - nothing in the plan or the cases changes.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q3: a`, `Q3: b` or `Q3: not needed`
  <!-- card Q3 ab655631599c6552a3f891ddeb6520b0b171e718bb18ea4af6c65a2909c275ee -->
- **Q4** [major, owner po_ba] What is expected for quick view add, add during a price update, network interruption and session expiry?
  - the source says: "Steps & Expected results: To be authored." — REF-3, 164, 165, 166
  - the source says: "no quick-view component in src (grep empty)" — context bundle fact REF-3
  - a) Scenarios are in scope and the owner supplies expected results (from person)
    if chosen: rows become testable with those results
    what changes if you choose a:
    - TS-23: waits for your answer becomes not checked - no case of it could be read here.
  - b) Scenarios stay unverifiable (quick view has no implementation) (from description)
    if chosen: rows stay unverifiable and are named in the report
    what changes if you choose b:
    - TS-23: waits for your answer becomes not checked - no case of it could be read here.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q4: a`, `Q4: b` or `Q4: not needed`
  <!-- card Q4 22103e9320aa6f720d97e8fa7ca4d4d2295af6234f9a041796453b9a1fe306f6 -->
- **Q5** [minor, owner po_ba] For an out-of-stock product, does a disabled 'Out of Stock' button satisfy the AC 'I should see an Out of stock message'?
  - the source says: "Then I should see an "Out of stock" message and no item is added" — REF-10 AC-2
  - the source says: "The application shows a disabled "Out of Stock" button rather than a message" — REF-15 notes
  - a) A disabled button labelled Out of Stock is enough (from comment:REF-15 notes)
    if chosen: tests assert the disabled button with that label and an empty cart
    what changes if you choose a:
    - nothing in the plan or the cases changes.
  - b) A message is required (from acceptance_criteria:AC-2)
    if chosen: tests assert a message; the missing message is a bug candidate
    what changes if you choose b:
    - nothing in the plan or the cases changes.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q5: a`, `Q5: b` or `Q5: not needed`
  <!-- card Q5 b6b29294a9af4b898d5d5eca1cdc1660e30e7024346adf23c0782325a7c99017 -->
- **Q6** [minor, owner po_ba] Code-only add behaviours with no requirement: catalog card add (qty 1), wishlist move-to-cart, guest cart merge at sign-in. Are they intended?
  - the source says: "every path by which a product can get into the cart" — LOCAL-1 description
  - before the change: unknown (no base revision read) — no diff, current code only
  - now: card adds qty 1; wishlist move adds qty 1 then deletes the item; merge keeps the higher quantity capped at stock — HomePage.tsx:118, WishlistPage.tsx:47, cartService.ts:118
  - a) The behaviour now is intended (from claim)
    if chosen: tests assert the current behaviour
    what changes if you choose a:
    - Then 2 of LOCAL-1_TC_019 (The catalog card adds the book to the cart with the right line) would read: "the card adds a line with quantity exactly 1 and the badge rose by 1"
    - Then 2 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist) would read: "the item is removed from the wishlist after a successful move"
    - Then 3 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist) would read: "when the add fails the item stays in the wishlist"
    - Then 1 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "the guest item survives sign-in at quantity 1"
    - Then 2 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "for a book in both carts the higher quantity wins"
    - Then 3 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "the merged quantity is capped at stock and a no-stock item is dropped"
  - b) The behaviour before is expected (a regression) (from claim)
    if chosen: tests wait for the owner's before value
    what changes if you choose b:
    - Then 2 of LOCAL-1_TC_019 (The catalog card adds the book to the cart with the right line) would read: "the card adds the quantity the owner names for the earlier behaviour"
    - Then 2 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist) would read: "the item stays in the wishlist as the owner names"
    - Then 3 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist) would read: "when the add fails the item is removed as the owner names"
    - Then 1 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "the guest cart is discarded or replaced at sign-in as the owner names"
    - Then 2 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "the quantities are summed or another rule the owner names"
    - Then 3 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items) would read: "another cap rule the owner names"
  - if you write `Q6: not needed`, what changes:
    - Then 2 of LOCAL-1_TC_019 (The catalog card adds the book to the cart with the right line): nothing is asserted here for this answer.
    - Then 2 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist): nothing is asserted here for this answer.
    - Then 3 of LOCAL-1_TC_020 (Moving a wishlist item to the cart adds it and removes it from the wishlist): nothing is asserted here for this answer.
    - Then 1 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items): nothing is asserted here for this answer.
    - Then 2 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items): nothing is asserted here for this answer.
    - Then 3 of LOCAL-1_TC_021 (A guest cart is merged at sign-in without losing items): nothing is asserted here for this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q6: a`, `Q6: b` or `Q6: not needed`
  <!-- card Q6 8c25b42632f7f3c54613f72dd031c9b3d23331b17d085bafd1a05ec985b3dfc1 -->
- **Q7** [major, owner po_ba] Q4 (TS-24): which price is charged when a book price is updated while the shopper is adding it: the price shown at add time, or the updated price?
  - the source says: "Adding a product while its price is being updated causes no errors and the user is charged the price shown when added" — R-24, REF-6 TC-015
  - before the change: unknown — no readable base for this behaviour
  - now: unknown — no code observable, cart price is read from the database at total time
  - a) Intended: the behaviour now is the expected one (unknown). (from claim)
    if chosen: The expected value of the Then is the behaviour now (unknown); the Then is checked against it.
    what changes if you choose a:
    - Then 1 of LOCAL-1_TC_022 (Adding a book while its price is updated charges the owner-defined price) would read: "the cart line and subtotal use the price shown on the page when the add was made (Q4 = a)"
    - Adding a book while its price is updated charges the owner-defined price: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_022).
  - b) A regression: the behaviour before the change is the expected one - unknown; say what it was. (from claim)
    if chosen: The expected value of the Then is what you say the behaviour was before the change; the behaviour now is reported as a defect.
    what changes if you choose b:
    - Then 1 of LOCAL-1_TC_022 (Adding a book while its price is updated charges the owner-defined price) would read: "the cart line and subtotal use the updated price and the shopper is told of the change (Q4 = b)"
    - Adding a book while its price is updated charges the owner-defined price: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_022).
  - if you write `Q7: not needed`, what changes:
    - Then 1 of LOCAL-1_TC_022 (Adding a book while its price is updated charges the owner-defined price): nothing is asserted here for this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q7: a`, `Q7: b` or `Q7: not needed`
  <!-- card Q7 ddc7d2f0961dac6412a459b0e000ece7cdd0ecd3527f912b250a665bc71dd588 -->
- **Q8** [major, owner po_ba] Q4 (TS-25): on an interrupted network during add, must the system complete the action, or tell the user to retry?
  - the source says: "An interrupted network while adding shows an error and the system recovers or tells the user to retry" — R-25, REF-7 TC-016
  - before the change: unknown — no readable base for this behaviour
  - now: unknown — no code observable for the interrupted add
  - a) Intended: the behaviour now is the expected one (unknown). (from claim)
    if chosen: The expected value of the Then is the behaviour now (unknown); the Then is checked against it.
    what changes if you choose a:
    - Then 2 of LOCAL-1_TC_023 (An interrupted network during add ends in the owner-defined outcome) would read: "the system completes the action: after the connection returns the book is in the cart once (Q4 = a)"
    - An interrupted network during add ends in the owner-defined outcome: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_023).
  - b) A regression: the behaviour before the change is the expected one - unknown; say what it was. (from claim)
    if chosen: The expected value of the Then is what you say the behaviour was before the change; the behaviour now is reported as a defect.
    what changes if you choose b:
    - Then 2 of LOCAL-1_TC_023 (An interrupted network during add ends in the owner-defined outcome) would read: "the system tells the user to retry and the book is not in the cart until the user retries (Q4 = b)"
    - An interrupted network during add ends in the owner-defined outcome: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_023).
  - if you write `Q8: not needed`, what changes:
    - Then 2 of LOCAL-1_TC_023 (An interrupted network during add ends in the owner-defined outcome): nothing is asserted here for this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q8: a`, `Q8: b` or `Q8: not needed`
  <!-- card Q8 f03b7e192eaa46cb0df5c1ffbcc0747bc021503116d610b4b40761d5ee95dc7b -->
- **Q9** [major, owner po_ba] Q4 (TS-26): after session expiry, must the system extend the session, or ask for login and then add the product?
  - the source says: "Adding after session expiry extends the session or asks for login, and the product is added after re-authentication" — R-26, REF-8 TC-017
  - before the change: unknown — no readable base for this behaviour
  - now: unknown — no code observable for expiry handling
  - a) Intended: the behaviour now is the expected one (unknown). (from claim)
    if chosen: The expected value of the Then is the behaviour now (unknown); the Then is checked against it.
    what changes if you choose a:
    - Then 1 of LOCAL-1_TC_024 (Adding after the session expired follows the owner-defined outcome) would read: "the session is extended and the add succeeds without a login prompt (Q4 = a)"
    - Adding after the session expired follows the owner-defined outcome: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_024).
  - b) A regression: the behaviour before the change is the expected one - unknown; say what it was. (from claim)
    if chosen: The expected value of the Then is what you say the behaviour was before the change; the behaviour now is reported as a defect.
    what changes if you choose b:
    - Then 1 of LOCAL-1_TC_024 (Adding after the session expired follows the owner-defined outcome) would read: "the user is asked to log in again and, after re-authentication, the book is added (Q4 = b)"
    - Adding after the session expired follows the owner-defined outcome: waits for your answer becomes a check by an agent, by hand (cases: LOCAL-1_TC_024).
  - if you write `Q9: not needed`, what changes:
    - Then 1 of LOCAL-1_TC_024 (Adding after the session expired follows the owner-defined outcome): nothing is asserted here for this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `Q9: a`, `Q9: b` or `Q9: not needed`
  <!-- card Q9 db01cef167dae8fa60b6227e1fca22241b1f878fe64af1b48df1734838f5fc2d -->
- **R-8** [blocker, owner po_ba] TS-8 (R-8) rests on a contradiction between two sources. Which reading do we test?
  - the source says: "A quantity of 0 is rejected with a clear message and nothing is added; the UI must not turn 0 into 1 (REF-2, 146, 89)" — requirements-register.md, R-8
  - the source says: ""quantity must be a whole number from 1 up to stock (REF-29)" vs code "setQuantity(Math.max(1, parseInt(e.target.value) || 1))" (BookDetailPage.tsx:164)" — requirements-register.md contradiction matrix, parent story/feature
  - a) A quantity of 0 is rejected with a clear message and nothing is added; the UI must not turn 0 into 1 (REF-2, 146, 89) (from description)
    if chosen: TS-8 keeps its disposition and its Then asserts the requirement as the register wrote it
  - b) "quantity must be a whole number from 1 up to stock (REF-29)" vs code "setQuantity(Math.max(1, parseInt(e.target.value) || 1))" (BookDetailPage.tsx:164) (from parent_ticket)
    if chosen: the Then of TS-8 is rewritten to what parent story/feature says; until you answer, that assertion stays `oracle_unknown` and the row is not automated on it
  - no row or case changes with this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `R-8: a`, `R-8: b` or `R-8: not needed`
- **R-9** [blocker, owner po_ba] TS-9 (R-9) rests on a contradiction between two sources. Which reading do we test?
  - the source says: "A negative quantity (-1) and a fractional quantity (1.5) are rejected and nothing is added, never rounded or coerced to 1 (REF-4, 152, 140 comment, TC-011/012)" — requirements-register.md, R-9
  - the source says: ""UI prevents setting negative value or shows error message" (REF-25 TC-012) vs code coercion to 1 (BookDetailPage.tsx:164)" — requirements-register.md contradiction matrix, parent story/feature
  - a) A negative quantity (-1) and a fractional quantity (1.5) are rejected and nothing is added, never rounded or coerced to 1 (REF-4, 152, 140 comment, TC-011/012) (from description)
    if chosen: TS-9 keeps its disposition and its Then asserts the requirement as the register wrote it
  - b) "UI prevents setting negative value or shows error message" (REF-25 TC-012) vs code coercion to 1 (BookDetailPage.tsx:164) (from parent_ticket)
    if chosen: the Then of TS-9 is rewritten to what parent story/feature says; until you answer, that assertion stays `oracle_unknown` and the row is not automated on it
  - no row or case changes with this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `R-9: a`, `R-9: b` or `R-9: not needed`
- **R-10** [blocker, owner po_ba] TS-10 (R-10) rests on a contradiction between two sources. Which reading do we test?
  - the source says: "A non-numeric quantity ("abc") is rejected with an error message and nothing is added (REF-5, TC-013)" — requirements-register.md, R-10
  - the source says: ""Add is rejected with a validation or error message" (REF-5) vs code parseInt(...) || 1 turning non-numeric into 1 (BookDetailPage.tsx:164)" — requirements-register.md contradiction matrix, comments & notes (ticket + parent)
  - a) A non-numeric quantity ("abc") is rejected with an error message and nothing is added (REF-5, TC-013) (from description)
    if chosen: TS-10 keeps its disposition and its Then asserts the requirement as the register wrote it
  - b) "Add is rejected with a validation or error message" (REF-5) vs code parseInt(...) || 1 turning non-numeric into 1 (BookDetailPage.tsx:164) (from comment)
    if chosen: the Then of TS-10 is rewritten to what comments & notes (ticket + parent) says; until you answer, that assertion stays `oracle_unknown` and the row is not automated on it
  - no row or case changes with this answer.
  - or your own wording — the readings are what the sources say, not a closed list of answers.
  - Answer: `R-10: a`, `R-10: b` or `R-10: not needed`

## How to answer
Write each answer on its own line, in one of these forms:
- `<question id>: <letter>` - the reading you choose, for example `Q1: a`
- `<question id>: not needed`
- `<full case id>: manual` - keep that case checked by hand
- `<full case id>: automate` - have that case checked by an automated test
- `<item id>: accept <your reason>` - pass one open item of the list above anyway, with your reason
- `approve as is` - alone on the first line: approves over every open item, each recorded with your words
- To accept a case as blocked on this stand, write `<full case id>: accept as blocked` on a line of its own, for example `LOCAL-1_TC_001: accept as blocked`; S5 then reports exactly those as not executed.
A full case id is the whole id, as written in this packet, for example `LOCAL-1_TC_001`.
Anything else, in your own words, goes to the assistant running this story, who turns it into one of these or asks you back; only the forms above are read by code.

## Attachments: not turned into requirements (1)
The factory turned the text of this ticket and of the tickets kept for it into requirements, sentence by sentence. It did not do that with their attachments, so a requirement that stands only in an attachment is in this plan only if you add it.
- REF-2: localhost (opened)
Do you want to add a requirement because of any of these?
(a) `approve` - nothing to add; this also approves the plan and the cases as they stand.
the factory: a record only; no agent works.
you: nothing more.
the story: what stands only in these attachments is not checked; the delivery verdict stays as the report has it.
(b) say which requirement, in your own words, instead of `approve`.
the factory: a helper reads your words and offers you the choices; then the requirements stage (S2) and the stages after it run again up to this gate.
you: this answer, one more answer to choose, and one more look at this gate.
the story: delivery waits until the gate is shown again.
Anything else, in your own words, goes to the assistant running this story, who turns it into one of these or asks you back; only the forms above are read by code. That holds unless your answer starts with the word that approves this gate: then only the lines in the form above are read, so do not start the answer with that word if you want your own words read.

## Tickets you kept: no requirement taken from their text (10)
- REF-22: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-12: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-3: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-23: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-5: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-24: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-6: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-7: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-8: read; no requirement taken from it: test-case setup/boilerplate repeated per case
- REF-14: read; no requirement taken from it: test-case setup/boilerplate repeated per case
If one of them holds a requirement, say which, in your own words, instead of `approve`.
Anything else, in your own words, goes to the assistant running this story, who turns it into one of these or asks you back; only the forms above are read by code. That holds unless your answer starts with the word that approves this gate: then only the lines in the form above are read, so do not start the answer with that word if you want your own words read.

## Already decided by you — repeated, not re-asked
- Start and preflight (S0) · the login this project records was refused · your word: "Idti dalshe po moemu slovu (login verified manually: the login test passes in ~80s, the probe limit is 60s)" · 2026-11-01

## e2e rows without a highest-risk field (10), for your information
- TS-1, TS-2, TS-3, TS-6, TS-11, TS-13, TS-19, TS-20, TS-21, TS-22: `automate` at e2e-ui, as written or after an answer to a question, while `impact`, `likelihood` and `verification_depth` do not say highest risk. The strategist judged them so; this is no question to you, and a critic of the plan reads the level. Say so in your answer if you want them changed.

_(brief truncated at 256 lines; the documents above carry the rest)_

