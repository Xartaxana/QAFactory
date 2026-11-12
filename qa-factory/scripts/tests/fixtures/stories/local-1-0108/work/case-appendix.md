## Case appendix

| Case | Plan row | Oracle/basis | Channel | Review status | Version |
|---|---|---|---|---|---|
| LOCAL-1_TC_001 | TS-1 | requirement:R-1 | auto | Draft | cv_0ca72c610937bf16acf5 |
| LOCAL-1_TC_002 | TS-2 | requirement:R-2 | auto | Draft | cv_d0150be267e7a21396f3 |
| LOCAL-1_TC_003 | TS-3 | requirement:R-3 | auto | Draft | cv_430295a645a433dc3e44 |
| LOCAL-1_TC_004 | TS-4 | requirement:R-4 | auto | Draft | cv_7396ea6d54e97abb53b5 |
| LOCAL-1_TC_005 | TS-5 | requirement:R-5 | auto | Draft | cv_1e2fe984a158845705a5 |
| LOCAL-1_TC_006 | TS-6 | requirement:R-6 | auto | Draft | cv_6eb2cabaed7969f5b81e |
| LOCAL-1_TC_007 | TS-8 | requirement:R-8 | auto | Draft | cv_046af312329b03af6938 |
| LOCAL-1_TC_008 | TS-9 | requirement:R-9 | auto | Draft | cv_399811ae764fa23a33a4 |
| LOCAL-1_TC_009 | TS-10 | requirement:R-10 | auto | Draft | cv_a7a0796939a1b5bab25c |
| LOCAL-1_TC_010 | TS-11 | requirement:R-11 | auto | Draft | cv_f2470b6bb042dcf661ab |
| LOCAL-1_TC_011 | TS-12 | requirement:R-12 | auto | Draft | cv_f943fc1ca0d050dd554f |
| LOCAL-1_TC_012 | TS-13 | requirement:R-13 | auto | Draft | cv_875562d9cfed74770120 |
| LOCAL-1_TC_013 | TS-14 | requirement:R-14 | auto | Draft | cv_4efddd5f3c4f2fcbeb17 |
| LOCAL-1_TC_014 | TS-15 | requirement:R-15 | auto | Draft | cv_65325bbd01a66b153365 |
| LOCAL-1_TC_015 | TS-16 | requirement:R-16 | auto | Draft | cv_c5f65d3008111d478843 |
| LOCAL-1_TC_016 | TS-17 | requirement:R-17 | auto | Draft | cv_d41f3bd77f8593fbe8f1 |
| LOCAL-1_TC_017 | TS-18 | requirement:R-18 | auto | Draft | cv_df4ef93d31ae6d041491 |
| LOCAL-1_TC_018 | TS-19 | requirement:R-19 | auto | Draft | cv_2a7711899a86d6d11f3a |
| LOCAL-1_TC_019 | TS-20 | requirement:R-19 | auto | Draft | cv_52d16ccfe2ee80471805 |
| LOCAL-1_TC_020 | TS-21 | requirement:R-19 | auto | Draft | cv_3599058ee1132918ddd6 |
| LOCAL-1_TC_021 | TS-22 | requirement:R-6 | auto | Draft | cv_beee818c5ed0c652255b |
| LOCAL-1_TC_022 | TS-24 | requirement:R-24 | manual-agent | Draft | cv_9f6a72a1fb2befac5683 |
| LOCAL-1_TC_023 | TS-25 | requirement:R-25 | manual-agent | Draft | cv_6370c20e7bf6a3ad8f88 |
| LOCAL-1_TC_024 | TS-26 | requirement:R-26 | manual-agent | Draft | cv_5960d7b9c2b12f9bb956 |

Cases: 24. Generated from pinned case content; do not edit this section by hand.

### LOCAL-1_TC_001 — cv_0ca72c610937bf16acf5

Requirements: R-1
Plan row: TS-1

## Given
- PC-1, PC-2, PC-3. The user's cart is empty. Book B has price P and stock 5 or more.

## When
1. Open the product page of B.
2. Click "Add to Cart" once, with the quantity field untouched.

## Then
1. The cart read through `GET /api/cart` (not the click response) holds exactly one line for B with quantity 1 and unit price P.
2. The cart page shows B once, quantity 1, price P.
3. The cart badge shows 1.

## Notes (self-probe)
- Path carries the discriminating input: B has a price different from other seeded books and P is read from the book record, not typed into the Then.
- Then 1 reads the API, Then 2 the cart page: independent of the click's toast and response. Fixture does not precompute the result.
- No data cleanup assumed: the Thens read only the line of the uniquely marked book B, never a global count.
- Oracle R-1 (AC-1); code is not the oracle.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-1 add puts item with qty 1 and price | R-1 | cart page and GET /api/cart after click | Then 1, 2 | none |
| OB-1 badge count (cosmetic, inside this case) | R-7 | header badge | Then 3 | toast text not asserted (TS-7 skip) |

### LOCAL-1_TC_002 — cv_d0150be267e7a21396f3

Requirements: R-2
Plan row: TS-2

## Given
- PC-1, PC-2, PC-3. The user's cart is empty. Book O has stock 0.

## When
1. Open the product page of O.
2. UI attempt: click the add control if it is enabled (a disabled control is itself the Q5 reading b outcome; no click then). Read the page and `GET /api/cart`.
3. API attempt (separate scenario): send `POST /api/cart` for O with quantity 1 as the same user, wait for the response, then `GET /api/cart`.

## Then
1. After the UI attempt (step 2): `GET /api/cart` holds no line for O and the badge is unchanged.
2. The wording check: a message or label naming the out-of-stock state is visible on the page (either reading of Q5 satisfies it). The Then asserts only the presence of the text "out of stock" (case-insensitive) on the page (open question Q5, BN-1).
3. After the API attempt (step 3): the request is not a 2xx and `GET /api/cart` holds no line for O. The exact 4xx code is informative only; R-2 states only "cannot be added".

## Notes (self-probe)
- Discriminating input is stock 0 on a book owned by the case; the cart is read through the API, independent of the UI.
- Negative proof is bounded: the cart is read after the API attempt completes (response received), not just after the click.
- Wording oracle is source_conflict (BN-1): the Then is deliberately reading-neutral. Owner answer to Q5 may tighten it.
- Cart read covers O only; no global count.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-2 nothing added (UI) | R-2 | GET /api/cart after UI attempt | Then 1 | none |
| OB-2 "Out of stock" visible | R-2 | product page text | Then 2 | message vs disabled button open (Q5) |
| OB-2 nothing added (API) | R-2 | response + GET /api/cart | Then 3 | status code not specified |

### LOCAL-1_TC_003 — cv_430295a645a433dc3e44

Requirements: R-3
Plan row: TS-3

## Given
- PC-1, PC-2, PC-3. The user's cart is empty.

## When
1. Open the product page of B.
2. Enter 3 into the quantity field (the whole value typed at once), click "Add to Cart".

## Then
1. `GET /api/cart` holds one line for B with quantity 3 and unit price P.
2. The cart page shows quantity 3 and a line subtotal of 3 x P (P read from the book record, the product is multiplied in the test).
3. The cart badge shows 3.
4. Before the click the quantity field holds "3" whole and is still the focused element.

## Notes (self-probe)
- Path: a multi-digit-free value but whole-entry; Then 4 checks the field keeps the whole value and focus (not keyed per character).
- Subtotal expected 3 x P is computed from the book record P, not read from the cart response.
- Reads only the line of marked book B.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-3 quantity 3 and subtotal | R-3 | GET /api/cart and cart page | Then 1, 2 | none |
| OB-3 badge | R-7 | header badge | Then 3 | none |
| OB-3 field behaviour | R-13 | quantity input | Then 4 | none |

### LOCAL-1_TC_004 — cv_7396ea6d54e97abb53b5

Requirements: R-4
Plan row: TS-4

## Given
- PC-1, PC-2. Empty cart. Book B has price 19.99 (set by the case).

## When
1. `POST /api/cart` with B and quantity 2.
2. `GET /api/cart` and `GET /api/cart/total`.

## Then
1. The cart line of B shows unit price equal to the book's price read from `GET /api/books/<id>` (the catalog record), not from the add response.
2. `GET /api/cart/total` equals 2 x the catalog price (39.98), computed in the test from the catalog price.

## Notes (self-probe)
- A non-round price makes price/rounding mix-ups visible; expected total is computed by the test from the catalog record, not from the cart.
- Two reads through different endpoints (books, cart, total) are independent of the add response.
- Only the marked book's line and the user's own total (fresh cart) are read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-4 cart price = book price | R-4 | GET /api/cart vs GET /api/books | Then 1 | UI display of the price not read here (TS-1 covers the cart page) |
| OB-4 total | R-4 | GET /api/cart/total | Then 2 | none |

### LOCAL-1_TC_005 — cv_1e2fe984a158845705a5

Requirements: R-5
Plan row: TS-5

## Given
- PC-1, PC-2. An anonymous request context, never signed in.

## When
1. `POST /api/cart` for B quantity 1 as the guest; keep the session cookie from the response.
2. Close the context and open a new one that carries only the stored cookie.
3. `GET /api/cart`.

## Then
1. The add is accepted for the guest: a 2xx, no redirect to login and no 401.
2. In the new context with the same cookie `GET /api/cart` holds the line for B quantity 1.
3. An anonymous context with no cookie sees no line for B (the cart is owned by the cookie). What the guest sees before the first add (empty vs login prompt, BN-9, Q4) is not asserted.
4. The `Set-Cookie` of the guest add (step 1) is persistent: it carries `Max-Age` or `Expires` in the future, not a session-only cookie that is lost when the browser closes (the persistence clause of R-5).

## Notes (self-probe)
- Discriminating input: the cookie. Without it the cart must differ, so a shared-global-cart defect is red.
- Cookie lifetime is now read from the Set-Cookie header (Then 4), so a session-only cookie is red; a real browser restart is still not performed (residual gap).
- Reads only the marked book's line.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-5 guest add without login | R-5 | HTTP status of the add | Then 1 | none |
| OB-5 persistence | R-5 | GET /api/cart with the cookie | Then 2, 3, 4 (cookie lifetime via Set-Cookie) | real browser restart not performed; first-add wording (Q4) |

### LOCAL-1_TC_006 — cv_6eb2cabaed7969f5b81e

Requirements: R-6
Plan row: TS-6

## Given
- PC-1, PC-2, PC-3. The user is signed in; the case first removes any line of its own book.

## When
1. Add B with quantity 2 from the product page.
2. Log out through the UI, then log in again as the same user.
3. Open the cart page.

## Then
1. After login the cart page shows B with quantity 2.
2. `GET /api/cart` (signed in again) holds the line of B with quantity 2 and no second line for B.

## Notes (self-probe)
- Logout in between means a session-bound cart (owner = guest cookie) would lose the line: red when cart ownership is wrong.
- The user's other cart lines are ignored (shared seed user): only the marked B line is read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-6 cart persists across logout/login | R-6 | cart page and GET /api/cart | Then 1, 2 | none |

### LOCAL-1_TC_007 — cv_046af312329b03af6938

Requirements: R-8
Plan row: TS-8

red_lock: expected red until the product page stops turning 0 into 1 (REF-2, owner-confirmed expected behaviour: 0 is rejected). Proof of the gap, not a broken case.

## Given
- PC-1, PC-2, PC-3. Empty cart (fresh user or the marked book absent).

## When
1. Open the product page of B.
2. Enter 0 into the quantity field as a whole value, click "Add to Cart".

## Then
1. P-zero: a visible message states that the quantity is invalid / must be at least 1.
2. `GET /api/cart` holds no line for B (nothing added), read after the click completes (message shown or request answered).
3. The quantity field still shows "0" whole (the UI did not turn it into 1).

## Notes (self-probe)
- The discriminating input is 0; the observed code coerces it to 1 and adds a copy, so Then 2 fails there (seeded defect = current behaviour).
- Negative proof reads the API after completion, independent of the UI message.
- Oracle is the requirement, not the code; no title on the defective behaviour.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-8 message | R-8 | page text | Then 1 | exact wording not specified ("clear message") |
| OB-8 nothing added | R-8 | GET /api/cart | Then 2 | none |
| OB-8 no coercion | R-8 | input value | Then 3 | none |

### LOCAL-1_TC_008 — cv_399811ae764fa23a33a4

Requirements: R-9
Plan row: TS-9

red_lock: expected red until the product page stops coercing -1 and 1.5 to 1 (REF-4, 152, 140; owner-confirmed expected behaviour: rejected).

## Given
- PC-1, PC-2, PC-3. Each value runs on a fresh empty cart (parameterized: P-negative = -1, P-non-integer = 1.5).

## When
1. Open the product page of B.
2. Enter the value as a whole (-1, then in a second run 1.5), click "Add to Cart".

## Then
1. For each value a visible message states the quantity is invalid.
2. `GET /api/cart` holds no line for B after the click completes: not rounded, not coerced to 1.
3. The field still shows the entered value whole ("-1", "1.5").

## Notes (self-probe)
- Value 1.5 and -1 distinguish rounding (to 2 or 1) from rejection; the count of lines for B is the discriminator.
- Negative proof via API after completion; fixture does not precompute anything.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-9 -1 rejected | R-9 | page + GET /api/cart | Then 1, 2, 3 (P-negative) | wording not specified |
| OB-9 1.5 rejected | R-9 | page + GET /api/cart | Then 1, 2, 3 (P-non-integer) | wording not specified |

### LOCAL-1_TC_009 — cv_a7a0796939a1b5bab25c

Requirements: R-10
Plan row: TS-10

red_lock: expected red until the product page stops turning non-numeric input into 1 (REF-5; owner-confirmed expected behaviour: error).

## Given
- PC-1, PC-2, PC-3. Empty cart for the marked book.

## When
1. Open the product page of B.
2. Enter "abc" by keyboard typing into the quantity field (P-non-numeric; the field is `type="number"`, so a programmatic fill of "abc" throws and is not used), then click "Add to Cart". If the browser drops the typed letters, record that: the dropped text and the resulting empty/1 value are not a pass, Then 1 and 2 still apply.

## Then
1. A visible validation or error message is shown.
2. `GET /api/cart` holds no line for B after the click completes.
3. The field is not silently replaced by a number; its content "abc" is kept whole (a number input may hold an empty value; then the message of Then 1 still appears).

## Notes (self-probe)
- Input of type number may refuse letters at the browser level: the case enters the text through the field and, if the browser drops it, records that fact; the add must still not produce a line for B.
- Discriminator is the absent line (a coercion to 1 would add a copy).

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-10 error shown | R-10 | page text | Then 1 | wording unspecified |
| OB-10 nothing added | R-10 | GET /api/cart | Then 2, 3 | none |

### LOCAL-1_TC_010 — cv_f2470b6bb042dcf661ab

Requirements: R-11
Plan row: TS-11

## Given
- PC-1, PC-2, PC-3. Empty cart for B (stock 4).

## When
1. Open the product page of B.
2. Enter 5 (stock + 1) whole, click "Add to Cart".

## Then
1. A visible message states the available number (4).
2. `GET /api/cart` holds no line for B after the request completed. (Whether only the available quantity could be added instead is open question Q2; this Then asserts the requirement text "nothing is added".)

## Notes (self-probe)
- Stock 4 and request 5: one over the boundary separates >= from > defects.
- The cart is read through the API after completion; the message through the UI.
- BN-4 reading b (partial add) would make Then 2 red; reading deferred to Q2.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-11 message with available number | R-11 | page text | Then 1 | none |
| OB-11 nothing added | R-11 | GET /api/cart | Then 2 | whole vs partial add (Q2, BN-4) |

### LOCAL-1_TC_011 — cv_f943fc1ca0d050dd554f

Requirements: R-12
Plan row: TS-12

## Given
- PC-1, PC-2. Book A stock 5, book S stock 1. Empty cart lines for A and S.

## When
1. `POST /api/cart` A quantity 3 (accepted). `POST /api/cart` A quantity 3 again.
2. `POST /api/cart` S quantity 1 (accepted). `POST /api/cart` S quantity 1 again.
3. `GET /api/cart`.

## Then
1. Both second requests are refused (4xx, INSUFFICIENT_STOCK-class error), not a 2xx and not a 5xx.
2. The line of A still has quantity 3 (not 6, not 5); the line of S still has quantity 1.
3. Boundary: a third `POST` A quantity 2 (3 + 2 = stock 5) is accepted and the line of A reads 5.

## Notes (self-probe)
- Single-copy book S covers the "incl. single-copy book" part of R-12; the 3+3>5 and 3+2=5 pair brackets the boundary.
- Cart read through GET after each refusal; a 5xx counts as a failed outcome for triage, not as a refusal.
- Only the lines of marked books are read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-12 refusal | R-12 | HTTP status | Then 1 | error code name is not required by the register |
| OB-12 cart unchanged | R-12 | GET /api/cart | Then 2 | none |
| OB-12 exact boundary accepted | R-12 | GET /api/cart | Then 3 | none |

### LOCAL-1_TC_012 — cv_875562d9cfed74770120

Requirements: R-13
Plan row: TS-13

red_lock: partitions P-zero, P-negative, P-non-integer, P-non-numeric are expected red until the product page stops coercing them to 1 (REF-2; owner-confirmed expected behaviour).

## Given
- PC-1, PC-2, PC-3. One parameterized test; for each partition a fresh empty cart for the marked book B (stock 300).

## When
For each partition enter the value whole into the quantity field of B's product page and click "Add to Cart":
P-one = 1, P-ten = 10, P-234 = 234, P-contains-zero = 100 (and 20, 101), P-multi-digit = 57, P-stock-boundary = 300, P-zero = 0, P-above-stock = 301, P-negative = -1, P-non-integer = 1.5, P-non-numeric = abc.

## Then
1. Valid partitions (P-one, P-ten, P-234, P-contains-zero, P-multi-digit, P-stock-boundary): `GET /api/cart` holds one line for B whose quantity equals the entered value exactly (not truncated, not clamped, 234 is not 23 or 2, 100 is not 1) and subtotal is value x P (P from the catalog record).
2. P-zero: a visible rejection message; no line for B.
3. P-negative and P-non-integer: a visible rejection message; no line for B (never rounded or coerced to 1).
4. P-non-numeric: a visible error message; no line for B.
5. P-above-stock (301): a visible message stating the available number 300; no line for B.
6. Every invalid partition (P-zero, P-above-stock, P-negative, P-non-integer, P-non-numeric): the cart read via the API after the click completes holds no line for B.
7. For every partition the typed value stays whole in the field and the field keeps focus until the click (multi-character value entered whole, cleared and re-entered, pasted).

## Notes (self-probe)
- The partitions are the person's equivalence classes; multi-digit and zero-containing values catch per-keystroke handling (typing 234 keystroke by keystroke would clamp 2 -> 23?). Then 7 pins that.
- Stock 300 lets 234 and the boundary 300 be valid and 301 invalid; stock below the 999 cap so boundary is stock (Q3 is for the API row TS-14).
- Each class has its own fresh cart so lines do not accumulate (a second add would sum); expected values are independent of cart reads.
- Negative proof reads the API after completion.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-13 valid classes exact quantity | R-13 | GET /api/cart | Then 1 (BN-5) | none |
| OB-13 zero | R-8 | page + API | Then 2, 6 | message wording |
| OB-13 negative, fractional | R-9 | page + API | Then 3, 6 | message wording |
| OB-13 non-numeric | R-10 | page + API | Then 4, 6 | browser may block letters in number input |
| OB-13 above stock | R-11 | page + API | Then 5, 6 | whole vs partial (Q2) |
| OB-13 field behaviour | R-13 | input | Then 7 | none |

### LOCAL-1_TC_013 — cv_4efddd5f3c4f2fcbeb17

Requirements: R-14
Plan row: TS-14

## Given
- PC-1, PC-2. Empty cart for B (stock 50).

## When
1. `POST /api/cart` for B with quantity 50 (the stock level).
2. `GET /api/cart` and `GET /api/cart/total`.

## Then
1. The add is accepted and the line of B has quantity 50 (the stock boundary reading of "maximum allowed"; the 999 schema-cap reading is open question Q3 and is not asserted).
2. The unit price equals the catalog price P and the total equals 50 x P, computed in the test.

## Notes (self-probe)
- Stock 50 is below the 999 cap so stock and cap readings differ; this case asserts the stock boundary only.
- Quantity 999 with stock >= 999 is left for the owner's answer to Q3.
- Reads only the marked book's line and the fresh cart total.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-14 maximum accepted | R-14 | GET /api/cart | Then 1 | stock vs 999 cap (Q3, BN-7) |
| OB-14 price and subtotal | R-14 | cart + total | Then 2 | none |

### LOCAL-1_TC_014 — cv_65325bbd01a66b153365

Requirements: R-15
Plan row: TS-15

## Given
- PC-1, PC-2. Empty cart for B.

## When
`POST /api/cart` for B with quantity 999999999 (partition P-huge), then with 99999999999999999999 (P-beyond-safe-integer).

## Then
1. Each request is answered with a 4xx error or the add is capped to a limit that is at most the stock (10): never a 5xx and never a line above stock.
2. After each request `GET /api/cart` holds either no line for B or one with quantity at most 10.
3. The application stays up: `GET /api/health` answers 200 and a normal add of quantity 1 for B afterwards is accepted.

## Notes (self-probe)
- Two sizes: one within JSON integer range, one beyond safe-integer precision, so a type overflow is visible.
- Stability proof is the follow-up request, not the absence of a crash message.
- A 5xx is a failed outcome for triage.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-15 error or limit | R-15 | HTTP status + cart | Then 1, 2 | which of error vs limit is not specified (BN-8) |
| OB-15 system stays stable | R-15 | health + follow-up add | Then 3 | none |

### LOCAL-1_TC_015 — cv_c5f65d3008111d478843

Requirements: R-16
Plan row: TS-16

## Given
- PC-1, PC-2. Empty cart for B.

## When
1. `POST /api/cart` B quantity 2. 2. `POST /api/cart` B quantity 3. 3. `GET /api/cart`.

## Then
1. Exactly one cart line exists for B (not two) with quantity 5.
2. The line subtotal equals 5 x P (P from the catalog record).

## Notes (self-probe)
- 2 and 3 are different so summing differs from replacing (3) and from doubling (4).
- One-line check counts lines of the marked book B only.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-16 one line summed | R-16 | GET /api/cart | Then 1, 2 | UI path not repeated |

### LOCAL-1_TC_016 — cv_d41f3bd77f8593fbe8f1

Requirements: R-17
Plan row: TS-17

## Given
- PC-1, PC-2. Books B1 (price p1), B2 (p2), B3 (p3), all different, stock 10.

## When
`POST /api/cart` B1 x1, B2 x2, B3 x3; then `GET /api/cart` and `GET /api/cart/total`.

## Then
1. The cart holds one line per book (three lines for the marked books) with each book's catalog price and the quantities 1, 2, 3.
2. The total equals p1 + 2 x p2 + 3 x p3, computed in the test from the catalog records.

## Notes (self-probe)
- Distinct prices and quantities make a swapped or merged line visible.
- Because the shared seed user may hold other lines, the Then reads only the three marked lines; the total is asserted as a delta against the total read before the adds.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-17 one line each | R-17 | GET /api/cart | Then 1 | none |
| OB-17 summed total | R-17 | GET /api/cart/total | Then 2 | none |

### LOCAL-1_TC_017 — cv_df4ef93d31ae6d041491

Requirements: R-18
Plan row: TS-18

## Given
- PC-1. A book id that does not exist: the case reads the catalog and takes max id + 1000000.

## When
`POST /api/cart` with that bookId, quantity 1; then `GET /api/cart`.

## Then
1. The answer is 404 with the error code BOOK_NOT_FOUND.
2. The cart has no line for that bookId and the user's line count is the same as before the request.

## Notes (self-probe)
- The id is derived from the catalog, not hard-coded, so it cannot become a real book.
- The cart is read after the response; the count is compared with the count read before (delta, not global).

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-18 404 BOOK_NOT_FOUND | R-18 | HTTP status and code | Then 1 | none |
| OB-18 nothing added | R-18 | GET /api/cart | Then 2 | orphan rows in storage not observable by API |

### LOCAL-1_TC_018 — cv_2a7711899a86d6d11f3a

Requirements: R-19
Plan row: TS-19

## Given
- PC-1, PC-2, PC-3. Empty cart lines for both books; both books on the wishlist.

## When
Decision table, one run per path (product page, catalog card, wishlist move) and per book (in stock, out of stock): perform the add by that path.

## Then
1. In-stock book, each of the three paths: `GET /api/cart` holds a line for the book at the catalog price P (the same price whichever path added it).
2. In-stock book, each path: the badge increases by the added quantity and a success message is shown.
3. Out-of-stock book, each path: no line is created (read through the API); the path shows the out-of-stock refusal or does not offer the add.
4. A second add of the in-stock book by a different path sums into the same single line (quantity 2), never above stock 5.

## Notes (self-probe)
- Seam: the paths are separate code (HomePage, WishlistPage, BookDetailPage); equal outcomes across them is the discriminating check.
- Stock-limit parity beyond 1 per add is covered by TS-12 (api); here the stock path is the out-of-stock book.
- Quantity-1 and wishlist removal are the subject of LOCAL-1_TC_019/020, not asserted here.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-19 price parity | R-19 | GET /api/cart | Then 1 | none |
| OB-19 badge, message | R-19 | UI | Then 2 | message wording |
| OB-19 stock rule parity | R-19 | GET /api/cart | Then 3, 4 | quick view has no implementation (TS-23) |

### LOCAL-1_TC_019 — cv_52d16ccfe2ee80471805

Requirements: R-20
Plan row: TS-20

## Given
- PC-1, PC-2, PC-3. Empty cart line for B.

## When
Click the add-to-cart button of B's catalog card once.

## Then
1. `GET /api/cart` holds a line for B at the catalog price (the add by the card obeys the add rules of the product page).
2. If Q6 confirms the present behaviour (now): the line quantity is exactly 1 and the badge rose by 1; if the owner names the earlier behaviour (before), the value follows that answer. No literal is asserted before Q6 is answered.

## Notes (self-probe)
- The quantity-1 claim comes from code (R-20 is implementation-derived), so Then 2 is `unknown`; a second click is not used because summing is TS-16.
- Then 1 is independent of the quantity question.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-20 line created at catalog price | R-19 | GET /api/cart | Then 1 | none |
| OB-20 quantity | Q6 | GET /api/cart, badge | Then 2 | oracle unknown until Q6 |

### LOCAL-1_TC_020 — cv_3599058ee1132918ddd6

Requirements: R-21
Plan row: TS-21

## Given
- PC-1, PC-2, PC-3, PC-4. Two marked books W and X, both in stock (stock 5), are on the user's wishlist. The move button of an out-of-stock wishlist item is disabled in the UI, so the refused add is staged by taking X out of stock after the page has rendered, not by seeding X at stock 0.

## When
1. Open the wishlist page; both W and X show an enabled move button.
2. Click "move to cart" for W.
3. As admin (PC-4) set the stock of X to 0 while the page is still open.
4. Click "move to cart" for X (the add is now refused by the stock rule).
5. Reload the wishlist page.

## Then
1. After step 2 `GET /api/cart` holds a line for W at its catalog price.
2. If Q6 confirms the present behaviour (now): W is gone from the wishlist (read after the reload of step 5, not from the page state before it); otherwise the owner's rule (before).
3. If Q6 confirms the present behaviour (now): after the refused move X is still on the wishlist (read after reload) and `GET /api/cart` holds no line for X: no item is lost; otherwise the owner's rule (before).

## Notes (self-probe)
- Reachability: the disabled-button path is avoided (X is in stock when rendered, then stock is set to 0 before the click), so the add-refused branch really runs. A check that the click of step 4 was answered with a refusal (4xx from the add request) is taken as the completion boundary before reading the wishlist.
- Data-loss risk: the refused add must not delete the wishlist item; the refusal comes from the real stock rule, not a mocked failure.
- Wishlist state is read after a reload (independent of the click response). Only the case's own user and marked books.
- Thens 2 and 3 carry no literal until Q6 is answered.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-21 add on move | R-19 | GET /api/cart | Then 1 | none |
| OB-21 wishlist removal | Q6 | wishlist after reload | Then 2 | oracle unknown |
| OB-21 error keeps item | Q6 | wishlist + cart after refused add | Then 3 | oracle unknown |

### LOCAL-1_TC_021 — cv_beee818c5ed0c652255b

Requirements: R-22
Plan row: TS-22

## Given
- PC-1, PC-2, PC-3, PC-4. Order: (1) signed in as the user, seed the user's cart with H x4 (stock of H is 10); (2) log out; (3) as a guest add G x1, H x2, Z x1; (4) as admin set Z's stock to 0 (Z's guest line stays); the guest cookie is kept.

## When
Sign in as the user through the UI login page (the guest cookie still present), then open the cart.

## Then
1. If Q6 confirms the present behaviour (now): G is in the user's cart at quantity 1 (the guest item is not lost); `GET /api/cart` as the signed-in user shows it. Otherwise it follows the owner's answer (before).
2. If Q6 confirms the present behaviour (now): H has quantity 4 (higher of 2 and 4 wins, not 6); otherwise the owner's rule (before).
3. If Q6 confirms the present behaviour (now): Z is absent (no stock, dropped) and no line has a quantity above its stock; otherwise the owner's rule (before).

## Notes (self-probe)
- 2 and 4 are chosen so max (4), sum (6) and replace-by-guest (2) differ.
- Then 1 is the data-loss floor; R-6 says only that the signed-in cart persists, not that a guest cart is merged, so Then 1 is oracle_unknown on Q6 like Thens 2 and 3 (all are code claims awaiting Q6).
- Only the three marked books are read.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-22 guest item kept | Q6 | GET /api/cart after login | Then 1 | oracle unknown until Q6 (R-6 does not cover guest merge) |
| OB-22 winner rule | Q6 | GET /api/cart | Then 2 | oracle unknown |
| OB-22 cap and drop | Q6 | GET /api/cart | Then 3 | oracle unknown |

### LOCAL-1_TC_022 — cv_9f6a72a1fb2befac5683

Requirements: R-24
Plan row: TS-24

Manual evidence policy (copied from the plan row, OB-24): `evidence_policy: api`; required phases before and after; completion condition: both actions settled (the add answered and the price update answered). Disposition applies once Q4 is answered (reading a or b settles the expected price); until then the row stays `unverifiable`.

## Given
- PC-1, PC-2, PC-3, PC-4. The marked book B costs 10.00; the user's cart holds no line for B.

## When
1. Before phase: record `GET /api/books/<B>` price and `GET /api/cart` (no line for B).
2. As the user open the product page of B (page shows 10.00).
3. As admin update the price of B to 12.00 through the API; wait for the answer.
4. As the user click "Add to Cart" on the still-open page.
5. After phase: record the add response, `GET /api/cart` and `GET /api/books/<B>`.
Actual steps and each request/response (secret-free) are captured as evidence.

## Then
1. If Q4 = a: the cart line for B is priced 10.00 (the price shown) and subtotal equals 10.00 x quantity; if Q4 = b: the line is priced 12.00 and the shopper is told of the change. No literal is asserted before Q4 is answered.
2. The add causes no error: the add response is a 2xx or a visible message, not an unhandled 5xx, and the line price equals one of the two prices (10.00 or 12.00), never a third value or zero. Cart is read from `GET /api/cart` after both actions settled, for B only.

## Notes (self-probe)
- The two prices differ (10.00 vs 12.00) so stale-price and fresh-price outcomes are distinguishable; the cart is read through the API, independent of the page.
- The update is sequenced before the click (a deterministic ordering of the race, not a true parallel race); a true simultaneous race is not claimed (residual gap).
- Evidence incomplete (missing before or after) is `inconclusive`, not pass.
- Cleanup: restore B's price, remove the line; only the marked book is touched.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-24 price charged | Q4 | cart and total after both actions | Then 1 | oracle unknown until Q4 |
| OB-24 no error | R-24 | add response, cart | Then 2 | true parallel race not staged |

### LOCAL-1_TC_023 — cv_6370c20e7bf6a3ad8f88

Requirements: R-25
Plan row: TS-25

Manual evidence policy (copied from the plan row, OB-25): `evidence_policy: ui`; required phases before and after plus the actual steps; screenshots of the page after the interruption and after recovery; completion condition: request settled or timed out. Missing evidence is `inconclusive`. Request abort uses route interception on the browser only, with teardown and network evidence; it never mutates infrastructure. Applies once Q4 is answered; until then the row stays `unverifiable`.

## Given
- PC-1, PC-2, PC-3. The user's cart holds no line for the marked book B. A route rule on the browser aborts the next `POST /api/cart` request.

## When
1. Before phase: screenshot of the product page of B and `GET /api/cart` (no line for B).
2. Activate the abort rule and click "Add to Cart" once; wait until the request has failed or timed out.
3. After-interruption phase: screenshot the page; record the network log showing the aborted request.
4. Remove the abort rule; if the page offers a retry or the system recovers on its own, follow it; wait until settled.
5. After phase: screenshot and `GET /api/cart`.

## Then
1. The shopper sees an error or retry message after the interruption, not a success message and not a silent nothing; the page stays usable (no blank screen).
2. If Q4 = a: after recovery `GET /api/cart` holds exactly one line for B quantity 1; if Q4 = b: the page told the user to retry and `GET /api/cart` holds no line for B until the retry is made. No literal asserted before Q4 is answered.
3. No duplicate: after the interruption and any retry `GET /api/cart` holds at most one line for B and its quantity equals the number of completed adds (one).

## Notes (self-probe)
- Discriminator: the abort rule is in place for exactly the add request; cart is read through the API after the settle boundary, independent of the page message.
- Then 1 holds under both readings of BN-10; Then 2 is the open part.
- Route interception evidence (network log, teardown of the rule) is required.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-25 error shown | R-25 | page message | Then 1 | wording not specified |
| OB-25 outcome | Q4 | page + GET /api/cart | Then 2 | complete vs retry open (BN-10) |
| OB-25 no duplicate | R-25 | GET /api/cart | Then 3 | none |

### LOCAL-1_TC_024 — cv_5960d7b9c2b12f9bb956

Requirements: R-26
Plan row: TS-26

Manual evidence policy (copied from the plan row, OB-26): `evidence_policy: ui`; required phases before and after plus actual steps; screenshots of the page when the add is attempted and after settling; completion condition: add settled and re-authentication done if asked. Missing evidence is `inconclusive`. The expiry is made by removing or invalidating the session cookie in the browser context only; no infrastructure change. Applies once Q4 is answered; until then the row stays `unverifiable`.

## Given
- PC-1, PC-2, PC-3. The user is signed in on the product page of the marked book B; the cart holds no line for B.

## When
1. Before phase: screenshot of the page showing the signed-in state and `GET /api/cart` (no line for B).
2. Expire the session: clear the session cookie of this browser context (record the cookie names, never the values).
3. Click "Add to Cart" on the still-open page; screenshot what the page shows.
4. If a login is asked, sign in as the same user and complete the add (or follow the page's continuation); wait until settled.
5. After phase: screenshot and `GET /api/cart` as the user.

## Then
1. If Q4 = a: the page does not ask for login and the add succeeds with the session extended; if Q4 = b: the page asks for login, and after re-authentication the cart holds the line for B. No literal asserted before Q4 is answered.
2. The add never fails silently and never loses the product: after the flow settles either the cart holds one line for B quantity 1, or the page shows a visible message; the user is never left on a blank page, and no duplicate line for B exists.

## Notes (self-probe)
- Discriminator: the expired state is real (cookie cleared before the click) so the add cannot ride the old session; the cart is read via the API with a fresh sign-in, independent of the page.
- Then 2 holds under both readings (BN-11); Then 1 is the open part.
- Cleanup: remove the line for B.

## Obligation coverage
| obligation/part | oracle | boundary | Then/evidence | residual gap |
|---|---|---|---|---|
| OB-26 extend vs login | Q4 | page state | Then 1 | open (BN-11) |
| OB-26 product not lost | R-26 | page + GET /api/cart | Then 2 | none |

