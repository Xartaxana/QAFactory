"""A negative check whose exact code is an open question keeps the 4xx range, the allowed call by the same credentials, and the door."""
from client import get, post

TOKEN = "readonly-token"


def test_expired_coupon_TC_003():
    assert get("/v1/cart", token=TOKEN).status_code == 200
    response = post("/v1/cart/coupon", {"code": "EXPIRED"}, token=TOKEN)
    assert 400 <= response.status_code < 500  # oracle_unknown: Q4
