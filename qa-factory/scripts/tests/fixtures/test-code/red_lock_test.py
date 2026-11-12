"""An expected-red test: the requirement is not implemented yet, and says so out loud.

red_lock: R-4 has no implementation in this MR; the test is honestly red and carries the
bug reference, which is the sanctioned path for a known gap.
"""
import pytest


@pytest.mark.xfail(reason="red_lock: BUG-7 - requirement R-4 is not implemented", strict=True)
def test_total_restored_TC_004():
    from cart import Cart, remove_coupon
    cart = Cart(subtotal=200.00, discount_percent=10)
    remove_coupon(cart)
    assert cart.total == 200.00
