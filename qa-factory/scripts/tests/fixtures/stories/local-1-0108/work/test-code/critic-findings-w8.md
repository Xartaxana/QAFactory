# Critic findings - window 8 (S5-qa-code-critic-13): LOCAL-1_TC_020, LOCAL-1_TC_021

Roll-call (case -> instance, tests/e2e/cart/cart.spec.ts):
- LOCAL-1_TC_020 -> "@regression LOCAL-1_TC_020 moving a wishlist item to the cart ..." (red, contradicts_requirement on Then 1 unit price) - approved
- LOCAL-1_TC_021 -> "@regression LOCAL-1_TC_021 a guest cart is merged at sign-in ..." (green) - unverified (static review: separates max/sum/replace and coercion, but no live probe; probe record incomplete, person accepted the gap)

Static review: no blocking finding. Read cart.spec.ts 426-519, BasePage, WishlistPage, LoginPage, cart.fixture, bookstoreApi.

- TC_020: the plan's CC-3 point is met: the step-4 POST /api/cart reply is awaited and asserted 4xx. Then 2/3 read after a reload from the API (wishlistBookIds, cart), Then 1 unit price asserted last, so the known defect (cart line has no price) does not hide Thens 2 and 3. Red is the product's: contradicts_requirement (R-19), no probe, no fix asked.
- TC_021 sensitivity (static): H guest 2 vs user 4 separates max (4) from sum (6) and replace (2); G=3 by `toEqual([3])` catches loss and coercion to 1; Z=0 stock asserted absent plus a stock ceiling loop. The guest cookie does carry: the context is built from guest.ctx.storageState(), and G appears in the user's cart at 3, which only the guest cart can supply. Merge is awaited by leaving /login, not by sleep.
- BasePage.clickAndAwaitCartReply now returns the Response: the only other caller (spec line 388) awaits it and ignores the value; no change in earlier tests' behaviour.
- Note (no cause): Then 3 stock ceiling for Z (0) is implied by "Z absent"; harmless.

Findings: none blocking.
- F-1 cause: tooling - probe not run: TypeScript has no assertion probe ("person's word: probe gap tooling:typescript"; "not receipted"). Both instances: TC_021 critic_verdict unverified (static review only), TC_020 approved, sensitivity unproven by a live receipt.

Manifest check after put: 34 tests rows with case/file/status, 93 then_bindings, 34 critic_verdicts, no stray rows.
