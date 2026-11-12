# S5 notes (qa-automator-2, CART-1)
- Helpers: core/clients/cartApi.ts (CartApi guest jar, CatalogAdminApi), core/fixtures/cartApi.fixture.ts (fixtures guest and ownBooks; list ownBooks before guest in a test signature so carts clear before books are deleted).
- Admin login for own books: NextAuth credentials via /api/auth/csrf and /api/auth/callback/credentials with EMAIL_USER/EMAIL_PASS from .env (through cfg).
- Tests: tests/api/cart/*.spec.ts; the case id sits in the title after the tags. manifest_from_tests.py cannot read TS files, so the fragment is hand-built (instance spelling title[partition]; the test and parameter keys keep the 9 TC_004 rows apart).
- Run: hand-written request work/requests/s5-2-initial.json (profile web; the runtime probe is a node one-liner printing the provenance JSON). report_test_id is api/cart/file::title; the mapping needed run_suite --reparse-block with an instance_contracts object.
