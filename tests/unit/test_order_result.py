import pytest

from domain.entities.order import OrderResult


def test_construction_roundtrip():
    result = OrderResult(order_id="abc", filled_price=1.0852, status="OPEN")
    assert result.order_id == "abc"
    assert result.filled_price == 1.0852
    assert result.status == "OPEN"


def test_frozen_field_assignment_raises():
    result = OrderResult(order_id="abc", filled_price=1.0852, status="OPEN")
    with pytest.raises(AttributeError):
        result.order_id = "changed"
