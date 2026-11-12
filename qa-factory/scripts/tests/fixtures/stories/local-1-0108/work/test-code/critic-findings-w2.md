# Critic findings, window 2 (TC_014..017), S5-qa-code-critic-4
Roll-call: TC_014, TC_015, TC_016, TC_017 -> tests/api/cart/cart.spec.ts, one instance each.
- TC_014 unverified (no TS probe; static review clean). Note: the 4xx/5xx assertions are partly redundant (mechanical-grade, no finding).
- TC_015 approved, red on product (cart lines carry no price): Then 1 asserted first, Then 2 reads price; proves the requirement.
- TC_016 approved, red on product: Then 2 (total delta) before the price part of Then 1; independent Thens not hidden.
- TC_017 unverified (no TS probe); asserts 404 + BOOK_NOT_FOUND code and unchanged cart.
Probe: not run, person's word "probe gap: tooling:typescript" (cause: tooling).
