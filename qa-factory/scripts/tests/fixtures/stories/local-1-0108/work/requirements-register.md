---
task: LOCAL-1
created: 2026-11-01
ids: [R-1, R-2, R-3, R-4, R-5, R-6, R-7, R-8, R-9, R-10, R-11, R-12, R-13, R-14, R-15, R-16, R-17, R-18, R-19, R-20, R-21, R-22, R-23, R-24, R-25, R-26]
by_source: {story: 16, feature: 2, assumption: 0, discussion: 2, ac: 3, derived: 3}
confidence: high
---

## Register

| R | requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |
|---|---|---|---|---|---|---|---|---|
| R-1 | On the product page of an in-stock item, "Add to Cart" puts the item in the cart with the correct price and quantity = 1 (REF-10, rev 2026-10-13) | ac | — | yes | AC-1 | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:45 | blocked-flow | unchanged |
| R-2 | An out-of-stock product cannot be added and the shopper sees an "Out of stock" message (REF-10 AC-2, 143) | ac | — | yes | AC-2 | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:170 | blocked-flow | unchanged |
| R-3 | Selecting quantity 3 and adding shows quantity 3 and the correct subtotal in the cart (REF-10 AC-3, 142) | ac | — | yes | AC-3 | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:55 | blocked-flow | unchanged |
| R-4 | The price in the cart matches the product page and the backend price (QA note of REF-10, 167, TC-018) | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:103 | money | unchanged |
| R-5 | A guest can add an in-stock book without being sent to login, and the guest cart persists after the browser is closed and reopened (QA note of REF-10, 156, TC-003) | story | — | yes | — | current-code:MyBooks/src/lib/session.ts:34 | degraded | unchanged |
| R-6 | A signed-in user's cart persists across logout and login (REF-21, parent REF-25 TC-004) | feature | — | yes | — | current-code:MyBooks/src/lib/session.ts:34 | degraded | unchanged |
| R-7 | After a successful add a success message is shown and the cart icon/badge shows the item count (REF-25 TC-001, 141) | feature | — | yes | — | current-code:MyBooks/src/components/providers/AppProviders.tsx:35 | cosmetic | unchanged |
| R-8 | A quantity of 0 is rejected with a clear message and nothing is added; the UI must not turn 0 into 1 (REF-2, 146, 89) | story | — | yes | — | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:164 | degraded | changed |
| R-9 | A negative quantity (-1) and a fractional quantity (1.5) are rejected and nothing is added, never rounded or coerced to 1 (REF-4, 152, 140 comment, TC-011/012) | story | — | yes | — | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:164 | degraded | changed |
| R-10 | A non-numeric quantity ("abc") is rejected with an error message and nothing is added (REF-5, TC-013) | story | — | yes | — | current-code:MyBooks/src/components/pages/BookDetailPage.tsx:164 | degraded | changed |
| R-11 | A quantity above stock is rejected with a visible message stating the available number, and nothing is added (REF-11, TC-010) | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:44 | blocked-flow | unchanged |
| R-12 | The stock check counts copies already in the cart: a second add pushing the total above stock (incl. single-copy book) is rejected and the cart is unchanged (REF-18, 147, 89) | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:44 | blocked-flow | unchanged |
| R-13 | Quantity is a whole number from 1 up to stock; every valid value (1, 10, 234, numbers containing zero, multi-digit, equal to stock) is added with exactly that quantity (person's decision s1-conflict-20261101-234118; REF-29) | discussion | — | yes | — | current-code:MyBooks/src/lib/validation/schemas.ts:41 | degraded | unchanged |
| R-14 | The maximum allowed quantity can be added and the cart shows the correct price and subtotal (REF-23, TC-008) | story | — | yes | — | current-code:MyBooks/src/lib/validation/schemas.ts:41 | degraded | unchanged |
| R-15 | An extremely large quantity is handled appropriately (error or maximum limit) and the system stays stable (REF-24, TC-014) | story | — | yes | — | current-code:MyBooks/src/lib/validation/schemas.ts:41 | degraded | unchanged |
| R-16 | Adding the same product twice gives one cart line with the summed quantity and the correct subtotal (REF-12, TC-006) | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:53 | degraded | unchanged |
| R-17 | Adding several different in-stock products gives one line each with correct price, quantity and a subtotal equal to the sum (REF-22, TC-005) | story | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:53 | degraded | unchanged |
| R-18 | Adding a book that does not exist is refused (404 BOOK_NOT_FOUND) and nothing is added (REF-29 comment) | discussion | — | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:33 | degraded | unchanged |
| R-19 | Every path by which a product gets into the cart (product page, catalog card, wishlist move) obeys the same add rules: stock, validation, price, badge, message (LOCAL-1 description) | story | — | yes | — | current-code:MyBooks/src/components/pages/HomePage.tsx:118 | blocked-flow | unchanged |
| R-20 | Catalog card "add to cart" adds exactly quantity 1 (code: handleAddToCart) | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/components/pages/HomePage.tsx:118 | degraded | unchanged |
| R-21 | Wishlist "move to cart" adds quantity 1 then removes the wishlist item; on an add error the item stays in the wishlist (code) | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/components/pages/WishlistPage.tsx:47 | data-loss | unchanged |
| R-22 | Guest cart merge at sign-in: the higher quantity wins, capped at stock, no-stock items dropped (code: mergeGuestCart) | derived | aspect:shopping cart | yes | — | current-code:MyBooks/src/lib/services/cartService.ts:118 | data-loss | unchanged |
| R-23 | A product can be added from the quick view and appears in the cart with the right price and quantity (REF-3, TC-007) | story | — | no | — | none | blocked-flow | new |
| R-24 | Adding a product while its price is being updated causes no errors and the user is charged the price shown when added (REF-6, TC-015) | story | — | no | — | none | money | new |
| R-25 | An interrupted network while adding shows an error and the system recovers or tells the user to retry (REF-7, TC-016) | story | — | no | — | none | degraded | new |
| R-26 | Adding after session expiry extends the session or asks for login, and the product is added after re-authentication (REF-8, TC-017) | story | — | no | — | none | blocked-flow | new |

## Functions

| Function | Requirements |
|---|---|
| Add a book from the product page | R-1, R-2, R-3, R-7 |
| Quantity validation on add | R-8, R-9, R-10, R-13, R-14, R-15 |
| Stock limits on add | R-11, R-12, R-18 |
| Cart composition and price after adds | R-4, R-16, R-17 |
| Cart persistence for guest and signed-in user, merge | R-5, R-6, R-22 |
| Other add paths (catalog card, wishlist, quick view) | R-19, R-20, R-21, R-23 |
| Add under stress (price change, network, session) | R-24, R-25, R-26 |

## Branches

| BN | R | kind | source_ref | text |
|---|---|---|---|---|
| BN-1 | R-2 | variant | REF-15 notes | the application shows a disabled "Out of Stock" button instead of a message after click |
| BN-2 | R-8 | refusal | REF-2 | A quantity of 0 is rejected with a clear message and nothing is added |
| BN-3 | R-9 | partition | REF-4, 152 | negative (-1) and fractional (1.5) quantities |
| BN-4 | R-11 | variant | TC-010 | either no product is added or only the available quantity is added |
| BN-5 | R-13 | partition | person's decision | valid classes: 1, 10, 234, numbers containing zero, multi-digit, equal to stock (stock boundary) |
| BN-6 | R-13 | partition | person's decision | invalid classes: 0, above stock, negative, non-integer, non-numeric |
| BN-7 | R-14 | qualifier | REF-23 | "maximum allowed" is not defined (stock vs the schema cap 999) |
| BN-8 | R-15 | variant | REF-24 | an error or a maximum limit applied |
| BN-9 | R-5 | qualifier | REF-13 | the guest cart before the first add may be empty or the guest sent to login; note which |
| BN-10 | R-25 | variant | REF-7 | the system completes the action or notifies the user to retry |
| BN-11 | R-26 | variant | REF-8 | the session is extended or a new login is asked |

## Source obligations

| unit | home |
|---|---|
| U-b08550b9b491 | R-19 |
| U-43094330aa2e, U-adc00288fc91, U-a4549c25786e, U-dcbcdf3e8f0c | not_obligation: context links and stand description, no verifiable statement |
| U-17772b03a3b7, U-e6952c9bae50, U-9d80b3c4cd88, U-eef019d46fc1, U-2b85df271af5, U-23eba32b94f3, U-f69f202e6358, U-8e0ebd173da7, U-3cb368d58a19 | not_obligation: reproduction setup/meta of the bug |
| U-bfcd07fea8ae, U-265cfa3fc56c, U-2f944c5cc8c9, U-36b53b6b6f05, U-839b0e0841bc, U-14ad8f68ab68, U-6926d6746eaf, U-3b00e00e2e1c, U-6273ff64d9dd, U-82c0b416b86a, U-1dc0f01ccc67, U-c2a0a9b16aaf, U-3193a44fece4, U-cb48abe9e6e0, U-759c2cf082ca, U-84ab795a5787, U-c0049c91ea13 | R-8 |
| U-b8e03d464e2d, U-799db4bca481, U-ec822f899be4, U-7939ad05d52d, U-4961b2f354a7, U-0bd913e550a7, U-5a7468c41574, U-c2c4ae94bac3, U-d1e2d8b4a851, U-724bbceffe46, U-2cf65915d2c1, U-75c9b98e5384 | R-9 |
| U-e17398346dc2, U-41be775743f2, U-15ba92ccc25a, U-23550e4796e7, U-65272e84ea0c, U-da2ed19d270f, U-e1ea26c36214, U-1bd98b371d2f, U-647a4b265b77, U-1ed588542c7e, U-4bae8cd14eb4, U-13b6e8473b24, U-1d29c805c9ed, U-30b66bf7ef1a, U-3a7bc4a978b7, U-6ce68392a4cc, U-be308e44c6a0, U-157eca516243, U-10d2d41a7aa9, U-2336d04eb6af, U-15ea2b373531, U-236e3ec81c50, U-de50ce247948, U-9412816ce519, U-fa14835c7167, U-8a747d3e05b1, U-8f8a41f13b8d, U-c05f4e9eae03, U-0f249828daaf, U-9fab9df89cc0, U-052d3702b471, U-bbdae9b128ab, U-67e308d7ddb5, U-2d0520ed5080, U-ac03e5291580, U-5c3b5bcfdd7e, U-261c309ae29f, U-e4c37a124c0d, U-545d4495908e, U-66f1f3bed42f, U-59f3f57b7cab, U-67bcd36fea36, U-907be9197fd0, U-fb1777ece3f2, U-fcf283186de3, U-673f8f090ae3, U-264a29ce1afc, U-822eed5d2a2c, U-784894b324c5, U-715d920023c9, U-c9ada6128479, U-c740e855e28e, U-156fcef772d1, U-270681ef0f93, U-2e530b619292, U-e4f2e51aba68, U-2ffb7ed050dc, U-f54c6836fddb, U-73670456b9c6, U-4aa1f62ec472, U-f8a3a8a1f680, U-6dfd4d56523e, U-89711f36cb34, U-190fd85920ac, U-7bbac6e2eee7, U-5235faf676f9, U-724a57ad34ba, U-a4f725d5e544, U-d6420ccff9af, U-deafcd21c5cf, U-a18bc7255b84, U-d12b80bc7724, U-6463ad533db6, U-29dd0a1398c6, U-cae7b7fcee0d, U-ef0ac8e7368b, U-1fea3c495062, U-ec93661bda78, U-def8b0f994e7 | not_obligation: test-case setup/boilerplate repeated per case |
| U-1a3296a936f0, U-38b280eda374, U-80aa062455a6, U-b23eabe47c9f, U-e09f6102b675, U-fc7f948495e9, U-1ad3a275716f, U-173659504011, U-a9b573cfe25c, U-0cecea9c138f, U-2086966fac0e, U-620050050a56, U-c1f4158474f3, U-d51f09f29ff3, U-c01baef9fb00, U-1cddb8f6bf09, U-57fdbdd1ee1e, U-db0429da0e1a, U-b990e083f296, U-69503add80e4 | R-1 |
| U-a79e43ad3fdd, U-4e7d2d8d8905, U-1a6176d7a0f1 | R-7 |
| U-80e1c51845f4, U-4e1687581e4c, U-fc6663ba0450, U-3696f0a6ab5e, U-67806ba0083e, U-fa1c3f326d1a, U-e982a80200e8, U-19539f142f33, U-e01d0f8549b4, U-93b5550a842b, U-a802a08c070f, U-921019422b9e, U-98eb8bdfef05, U-312cbb476730, U-570953c0e5de, U-b6dc1405279e, U-c6c207522dd3 | R-3 |
| U-ca4bf4e3f11b, U-97ec88818cd8, U-3d930fc5561b, U-b48e4dc75e15, U-e6607ad48946, U-a6b222bc4ab2, U-95eccc794a44, U-c6a19a2af1ca, U-700a82a90b01, U-cadc81c5c7b6, U-0ecdd8a6414b, U-f1e2341cabf5, U-226ebe532393, U-a02998b0ef0c, U-4b1b90e46833, U-c0019eef0706, U-2b4471f48ffd, U-0f0fe507d1f5, U-b9e109316890, U-bb55afdd8430, U-0446608ab954, U-fb4f0a27d74a | R-2 |
| U-2f7065f82346, U-c475aea64d74, U-48a2d84ae403, U-ca14102e5327, U-0cf5f50854fa, U-2305ed01ba88, U-332a5a8d55a0, U-61333ed56fcb, U-b56c40056d9d, U-7fdd33c84bb1, U-d6e6b9781780, U-bbc6512310c9 | R-11 |
| U-86b1bcedac2f, U-3deccd4e5fe2, U-fd1d3a684a05, U-859f880b19e4, U-dbaf62b34ff4, U-9c11fb9067bc, U-40c85dd471cb, U-249cff1271b7, U-7700753ea2d7, U-c9e4ebb966fe, U-a348c94e82f0, U-f90731b14177, U-6cd2ada1e554, U-bb75b8936dd5, U-f3ff8506e41b, U-dd81fa3a79f8, U-960c867a7902, U-941ee2bf06ce, U-49add28927cd, U-1e02a78eb8db, U-a8c3170ddbca, U-4936e644a7aa, U-1ae2a4180db1 | R-12 |
| U-a929b15ff589, U-126d8bb02629, U-b306bc733eb9, U-a9becee51472, U-443c860e4a21, U-a96b3e0b1a34, U-640f71a6da65, U-fb8e200cdf18, U-789949bf9f23, U-4e59f1300e2c | excluded: raising a cart line quantity is a cart edit, not an add-to-cart path (person's scope decision, s1-conflict-20261101-234118) |
| U-6614619907c5, U-a9270e704dd2, U-c788b8eb3ef8, U-a3433b75e4dd, U-a53aefcc409d, U-db58deaf0185, U-f0de02dc147a, U-d683b97832ea, U-0437a4462cdb, U-4d9367933d80, U-b5ce94cbec88, U-6599dcbdb9dc, U-dd33033e79b0, U-9b49cdd38d25, U-07fcb1f4ae03, U-cb5e9caf28b3 | R-5 |
| U-9cc68a26e526, U-984864320c7a, U-fed08e28969c, U-8caba94e1471, U-49616145514e, U-1fe5778d65e9, U-de90b75f95be | R-6 |
| U-c6e78cd659df, U-27cd9f2650e3, U-6e0a3c934021, U-e75cf856b042 | not_obligation: heading |
| U-ff69e5c0618a | not_obligation: business value, not testable behaviour |
| U-c327cdabec06, U-dabc1a88aee7, U-88f7cb8f0a38, U-2e72fe5c654d, U-44c1328e0af6, U-59b79979a3f0 | R-4 |
| U-d50b53daf332, U-5b3ab64fc3e5, U-14439b451b11, U-a83a561e022d, U-61f7fca3afd0, U-e870de1db4b1, U-1d7528e2f386, U-8ff4b1960d1b, U-4c04c1ba4452, U-a5daf6b54d5f, U-a384eb5eb2bd, U-756e7e6f5f6d, U-a5c932d2c4d7, U-5022f5ff593b, U-12564ff88163, U-ba5c02e51d53, U-dc5d42008b08, U-8bb408b8f2b5, U-c9bfab2d1b0b, U-a6fd06c89e83, U-9a685797912e, U-6fd2bb51396d, U-52f797d71916, U-ec987c01e72e, U-992d95ee41e7, U-75f209485350, U-d15cd1a51275, U-8b39a69fdb0f, U-3956298f0b8a, U-6609b0fb9e94, U-d94e72ea9e9c, U-45d950ef4cc7, U-db9191cafc19, U-13dae8115b54, U-215c38103feb, U-428a02484824, U-2f89b0871a50, U-28bc6e42c98c, U-c2ee8a2bdb75, U-9d20f6c8ecd1, U-84c5b44879dc, U-ef7570a876ed, U-479aec285e6c, U-881bc712a803, U-4dde54a12d52, U-6139068cd0b3, U-389beb7a2c9d | not_obligation: test-document metadata |
| U-cbf263640f49, U-4de2c7a889b5, U-24de14236352, U-c6c246c79c3b, U-27fa2d002bf8 | R-17 |
| U-a61067fcdedb, U-7718915efcf9, U-c9a3a851dc42, U-a41490012fcf | R-16 |
| U-1f16344058e0, U-984fc29434a9, U-116cdfbf6f88, U-3531ae2aae04 | R-23 |
| U-a124d2397a7a, U-a082a41602a5, U-6ee8e86db984, U-86fcc24f6a6a | R-14 |
| U-9ab1cda2e431, U-88ccb7b08d44 | R-10 |
| U-e979affe7228, U-265e88da471e, U-73b763e2d81a, U-958c0539437a | R-15 |
| U-9c29a4ad3505, U-0c7ef58aef56, U-9790b9e01225, U-61ba1a4ba9f7, U-9145f47d6991, U-871f54d5e26e, U-f1e61f02119d | R-24 |
| U-a5f3dd56e576, U-a828cd066fe6, U-baa92676b35f, U-9d451546f735 | R-25 |
| U-b42968af5801, U-130676fdca65, U-0456c5f769db, U-9f6634780ed1, U-540954e1aba3 | R-26 |
| U-2d95e33163a5, U-0f7c68c08916, U-9e5db94d83ed, U-6f405db81fa9, U-9ef46be3feab | not_obligation: defect narrative/data model, already fixed (comment) or outside add-to-cart behaviour |
| U-deadc8fee8e1 | R-13 |
| G-119d6a68ca8c | R-8 |
| G-119d6a68ca8c | R-9 |
| G-119d6a68ca8c | R-10 |
| G-15edbc3f5803 | not_obligation: index of the individual cases of the parent test document |
| G-63d24b73aa42 | not_obligation: index of the individual cases of the parent test document |
| G-eca312b6401b | R-18 |
| G-eca312b6401b | R-12 |
| G-eca312b6401b | R-13 |

## Contradiction matrix

| R | parent story/feature | comments & notes (ticket + parent) | area cases | area open bugs |
|---|---|---|---|---|
| R-1 | ok:REF-10 AC-1 | ok:REF-16 | ok:REF-16 | n/a:no open bug on this behaviour |
| R-2 | contradicts:"Then I should see an \"Out of stock\" message and no item is added" (REF-10 AC-2) vs code "{isOutOfStock ? 'Out of Stock' : ..." disabled button (BookDetailPage.tsx:170) | ok:REF-15 notes "rejection wording is taken from the requirement" | ok:REF-15 | n/a:no open bug |
| R-3 | ok:REF-10 AC-3 | ok:REF-17 | ok:REF-17 | n/a:no open bug |
| R-4 | ok:REF-10 QA notes | silent | ok:REF-14 | n/a:no open bug |
| R-5 | ok:REF-10 QA notes | ok:REF-13 "guest cart behaviour was not documented beforehand, so record what is observed" | ok:REF-13 | n/a:no open bug |
| R-6 | silent | ok:REF-21 | ok:REF-21 | n/a:no open bug |
| R-7 | silent | ok:REF-25 TC-001 | ok:REF-16 | n/a:no open bug |
| R-8 | contradicts:"quantity must be a whole number from 1 up to stock (REF-29)" vs code "setQuantity(Math.max(1, parseInt(e.target.value) \|\| 1))" (BookDetailPage.tsx:164) | contradicts:"A quantity of 0 is rejected with a clear message and nothing is added" (REF-2) vs "Actual: the add succeeds ... the quantity field reverts to 1" (REF-2) | ok:REF-1 | ok:REF-2 |
| R-9 | contradicts:"UI prevents setting negative value or shows error message" (REF-25 TC-012) vs code coercion to 1 (BookDetailPage.tsx:164) | contradicts:"-1 and 1.5 behave the same way" (REF-2 comment 2026-10-12) vs requirement "rejected" (REF-4, 152) | ok:REF-4, REF-20 | ok:REF-2 |
| R-10 | ok:REF-25 TC-013 | contradicts:"Add is rejected with a validation or error message" (REF-5) vs code parseInt(...) \|\| 1 turning non-numeric into 1 (BookDetailPage.tsx:164) | ok:REF-5 | silent |
| R-11 | ok:REF-25 TC-010 | ok:REF-11 | ok:REF-11 | n/a:no open bug |
| R-12 | silent | ok:REF-29 comment "cart plus new quantity fits stock" | ok:REF-18, REF-19 | n/a:no open bug |
| R-13 | ok:REF-29 Expected | ok:person decision s1-conflict-20261101-234118 | silent | n/a:no open bug |
| R-14 | silent | silent | ok:REF-23 | n/a:no open bug |
| R-15 | silent | silent | ok:REF-24 | n/a:no open bug |
| R-16 | ok:REF-25 TC-006 | silent | ok:REF-12 | n/a:no open bug |
| R-17 | ok:REF-25 TC-005 | silent | ok:REF-22 | n/a:no open bug |
| R-18 | silent | ok:REF-29 comment "404 BOOK_NOT_FOUND" | silent | n/a:no open bug |
| R-19 | ok:LOCAL-1 description "every path by which a product can get into the cart" | silent | silent | n/a:no open bug |
| R-20 | silent | silent | silent | n/a:no open bug |
| R-21 | silent | silent | silent | n/a:no open bug |
| R-22 | silent | silent | ok:REF-13, REF-21 | n/a:no open bug |
| R-23 | ok:REF-25 TC-007 | silent | ok:REF-3 | n/a:no open bug |
| R-24 | ok:REF-25 TC-015 | silent | ok:REF-6 | n/a:no open bug |
| R-25 | ok:REF-25 TC-016 | silent | ok:REF-7 | n/a:no open bug |
| R-26 | ok:REF-25 TC-017 | silent | ok:REF-8 | n/a:no open bug |

## Behaviour claims

| R | before | before_ref | now | now_ref | differs | question | origin |
|---|---|---|---|---|---|---|---|
| R-20 | unknown | absent | adds quantity 1 | current-code:MyBooks/src/components/pages/HomePage.tsx:118 | unknown | Q6 | |
| R-21 | unknown | absent | adds quantity 1, then deletes the wishlist item | current-code:MyBooks/src/components/pages/WishlistPage.tsx:47 | unknown | Q6 | |
| R-22 | unknown | absent | higher quantity wins, capped at stock, no-stock dropped | current-code:MyBooks/src/lib/services/cartService.ts:118 | unknown | Q6 | |

## Reading forks

| R | Reading A | Reading B | Behavior difference | Decision |
|---|---|---|---|---|
| R-2 | an "Out of stock" message after the click | a disabled button labelled "Out of Stock" satisfies the AC | the test looks for a message vs a disabled control | question at gate A |
| R-8 | 0 is rejected with a message (requirement; person's recorded decision) | the UI coercion of 0 to 1 is the intended behaviour | 0 rejected vs 1 copy added silently | question at gate A |
| R-9 | -1 and 1.5 rejected with a message | the control may coerce them to a valid value | nothing added vs 1 copy added | question at gate A |
| R-10 | non-numeric input rejected with a message | the control ignores it / falls back to 1 | error vs silent 1 | question at gate A |
| R-11 | reject the whole add | add only the available quantity | nothing vs partial add | question at gate A |
| R-14 | maximum allowed = stock | maximum allowed = the 999 cap of the schema | which value is the boundary | question at gate A |
| R-23 | quick view is in scope as an add path | quick view does not exist, nothing to verify | test vs no test | question at gate A |
| R-24 | behaviour is defined elsewhere | the case is not authored, so the oracle is unresolved | test vs question | question at gate A |

## Attachments

| attachment | ticket | reading | R | question | why |
|---|---|---|---|---|---|
| localhost | REF-2 | not_an_expectation | - | - | HTML capture of the stand root page, not a statement of expected behaviour |
