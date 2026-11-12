"""A test that says what it checks and proves it through an independent channel."""
from cart import Cart, apply_coupon, CouponError


def test_cap_rejected_TC_001():
    """TC-001 coverage: a coupon above the cap is refused, the total is untouched."""
    cart = Cart(subtotal=200.00)
    try:
        apply_coupon(cart, 51)
        raised = None
    except CouponError as e:
        raised = str(e)
    assert raised == "DISCOUNT_TOO_LARGE"
    assert cart.total == 200.00
