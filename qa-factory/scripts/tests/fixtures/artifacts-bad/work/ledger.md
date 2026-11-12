# QA-1 — checks ledger

| Ref | Kind | State | Detail |
|---|---|---|---|
| TS-1 | plan_row | `passed_green` | TC-001 |
| TS-2 | plan_row | `failed:FLAKY` | TC-002 |
| TS-3 | plan_row | `impossible` | TC-003 |
| TC-001 | test | `passed_green` | tests/test_coupon.py::TC-001 |
| TC-002 | test | `not_verified_flaky` | tests/test_cart_banner.py::TC-002 — mechanism unnamed |
| QA-1-2 | plan_row | `subtask_in_progress` | status in progress at S1 — not closed by this story |

`delivery_ready: no`
- manifest: TC-003 is impossible and carries no gate decision
- traceability: R-3 has no terminal outcome (TC-003: unresolved (impossible) with no decision attached)
- traceability: R-4 has no terminal outcome (no row of test-plan.md names this requirement)
- triage: tests/test_cart_banner.py::test_banner is FLAKY and was not fixed (fix_result: none) — it is not verified; quarantine is a human decision at gate B, with a debt and a trigger
- review: no critic verdict for at least one test
- subtask QA-1-2 is still in progress — the story's own scope is not closed
- ledger: TS-2 is `failed:FLAKY` (TC-002)
- ledger: TS-3 is `impossible` (TC-003)
- ledger: TC-002 is `not_verified_flaky` (tests/test_cart_banner.py::TC-002 — mechanism unnamed)
