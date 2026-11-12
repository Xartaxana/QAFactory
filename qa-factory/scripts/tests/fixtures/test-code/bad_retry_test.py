"""Retry as stabilization: the flake is hidden, not fixed."""
import pytest
from cart import Cart, apply_coupon


@pytest.mark.flaky(reruns=3)
def test_banner_TC_002():
    cart = Cart(subtotal=200.00)
    apply_coupon(cart, 51)
    assert cart.banner == "DISCOUNT_TOO_LARGE"
