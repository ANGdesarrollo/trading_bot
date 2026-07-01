import pytest

from domain.entities.direction import Direction
from domain.entities.signal import Signal


def test_zero_sl_distance_raises_value_error():
    with pytest.raises(ValueError):
        Signal(direction=Direction.BUY, sl_distance=0.0, tp_distance=0.004)


def test_negative_tp_distance_raises_value_error():
    with pytest.raises(ValueError):
        Signal(direction=Direction.BUY, sl_distance=0.002, tp_distance=-0.001)
