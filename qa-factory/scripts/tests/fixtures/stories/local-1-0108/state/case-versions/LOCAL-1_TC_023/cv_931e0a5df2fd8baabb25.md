---
id: LOCAL-1_TC_023
title: An interrupted network during add ends in the owner-defined outcome
area: cart
priority: P2
status: Draft
channel: manual-agent
reuse_decision: new
updated: 2026-11-02
task: LOCAL-1
covers: [R-25]
defect_class: error-path
basis: "requirement:R-25"
then_oracles: [{"then": 1, "source": "requirement", "ref": "R-25"}, {"then": 2, "source": "unknown", "ref": "raise"}, {"then": 3, "source": "requirement", "ref": "R-25"}]
raise_questions: [{"then": 2, "question": "Q4 (TS-25): on an interrupted network during add, must the system complete the action, or tell the user to retry?", "source_says": [{"quote": "An interrupted network while adding shows an error and the system recovers or tells the user to retry", "where": "R-25, REF-7 TC-016"}], "severity": "major", "owner_role": "po_ba", "before": {"value": "unknown", "where": "no readable base for this behaviour"}, "now": {"value": "unknown", "where": "no code observable for the interrupted add"}}]
question_thens: [{"question": "raise", "then": 2, "readings": {"now": "the system completes the action: after the connection returns the book is in the cart once (Q4 = a)", "before": "the system tells the user to retry and the book is not in the cart until the user retries (Q4 = b)"}, "not_needed": ""}]
plan_row: TS-25
reuse_reason: grep cart in tests/, core/, test-cases/ finds no network-interruption case; new
preconditions: [{"id": "PC-1", "kind": "account", "what": "a signed-in seed user", "check": {"stand_account": "user"}}, {"id": "PC-2", "kind": "service", "what": "the stand UI address", "check": {"stand_frontend": "the product page is driven in the browser"}}, {"id": "PC-3", "kind": "data", "what": "an in-stock book, created by the case", "check": {"case_seeds": "one uniquely marked in-stock book"}}]
branches: [{"id": "BN-10", "then": 2}]
---
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
