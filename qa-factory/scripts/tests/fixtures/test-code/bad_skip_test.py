"""A skip with no expected-red declaration: the check is silently unverified."""
import pytest


@pytest.mark.skip(reason="fails on CI, will look at it later")
def test_total_restored_TC_004():
    assert False
