# S5 notes (what the next window must not rediscover)

- Page objects: core/pages/HomePage.ts (catalog card: openCatalogFor(title) via /?query=, bookCard/cardAddButton/addFromCard/outOfStockMark, cartBadge, addedToast), core/pages/WishlistPage.ts (open, moveButton, moveToCart, movedToast, outOfStockBadge), core/pages/BookDetailPage.ts (outOfStockMark added).
- API client: core/clients/bookstoreApi.ts saveToWishlist(bookId); wishlist rows go with the throwaway shopper.
- Fixture: core/fixtures/cart.fixture.ts `shop` (shopper, book(price, stock)); cart line has no price field (known defect), so unit-price asserts go last.
- Run mapping: one `--grep` per case; a parameterized case uses the prefix `<case> <title>\[` in selector_args for every instance (the launcher takes only the last --grep).
- Generators: work/gen-w10.py and gen-w10b.py write the fragments; loop-generated titles are not parsed by manifest_from_tests.py, so rows are sent with manifest_put.py (do not re-run manifest_from_tests on cart.spec.ts: it adds stray rows).
- Branch check: commit a25b0801669b is of the MyBooks repo, not the test repo; the content is proven by the code present (WishlistPage.tsx, BookCard.tsx).
