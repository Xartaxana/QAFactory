# Code you will touch - S5-qa-automator-6

Built by code from the plan's tests of this window: the tests you extend, the fixtures they use and one neighbouring test per file. Read it before searching the repository.

## Fields every tests[] row of the manifest owes

- assertion_id: the assertion that fails when the behaviour breaks (a file:line or an id)
- defect_location: the product location the obligation damages (a file:line)
- change_disposition: `new_or_changed` or `unchanged` (one of: new_or_changed, unchanged)
- change_basis_ref: what the disposition is read from (for example `manifest:<case>`)
- obligation_refs: the plan's obligation ids and hashes the test proves; written by the marker, not by hand: the marker `qa(obligations=[...])` on the test, then `manifest_from_tests.py`
- profile_id: the execution profile that runs the test; the file lies under a test root several profiles share

## Not found, not checked

- T-9: no neighbouring test found near tests/api/cart/cart-quote-order.spec.ts (checked: the file and its directory)
