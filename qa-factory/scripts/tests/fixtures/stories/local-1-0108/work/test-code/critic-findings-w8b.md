# Critic findings - window 8 re-look (S5-qa-code-critic-14): LOCAL-1_TC_020, LOCAL-1_TC_021

Retry of S5-qa-code-critic-13. The author added obligation_hash to the obligation_refs of both rows (OB-21, OB-22); no test code changed. I re-read cart.spec.ts 426-519 and stand behind the earlier verdicts.

Roll-call (case -> instance, tests/e2e/cart/cart.spec.ts):
- LOCAL-1_TC_020 -> "@regression LOCAL-1_TC_020 moving a wishlist item to the cart ..." (red, contradicts_requirement R-19, Then 1) - approved
- LOCAL-1_TC_021 -> "@regression LOCAL-1_TC_021 a guest cart is merged at sign-in ..." (green) - unverified

Static review:
- TC_020: the refused step-4 add is asserted 4xx on the awaited reply. Thens 2 and 3 are read after a reload through the API and are soft-asserted before Then 1, so the missing price field (the product defect) does not hide them.
- TC_021: H guest 2 vs user 4 separates max (4) from sum (6) and from replace (2). G is asserted with toEqual([3]), which catches loss and coercion. Z is absent and the stock ceiling is checked. The guest cookie travels in storageState, and G reaching the user's cart is only possible through it.
- No sleeps; the merge is awaited by the logout button becoming visible.
- Note (no cause): the Then 3 stock ceiling for Z is implied by "Z absent"; harmless.

Manifest check: 34 tests rows (each with case/file/status), 93 then_bindings. TC_020 approved and TC_021 unverified are on the rows. No stray rows, nothing to put.

Findings:
- F-1 cause: tooling, not blocking. TypeScript has no assertion probe (person's words: "probe gap tooling:typescript", "not receipted"). TC_021 stays unverified (static review only, no defect found). TC_020 is approved on a red run that fails for the product's reason, so it needs no probe.
