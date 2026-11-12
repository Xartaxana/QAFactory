"""A negative check that accepts any client error proves nothing."""
from client import post


def test_expired_coupon_TC_003():
    response = post("/v1/cart/coupon", {"code": "EXPIRED"})
    assert response.status_code in (400, 403, 422)
