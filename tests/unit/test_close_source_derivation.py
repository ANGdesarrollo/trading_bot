from __future__ import annotations

import pytest

from domain.services.close_source import derive_close_source

_FP = 1.1000
_SL_DIST = 0.0020
_TP_DIST = 0.0040


@pytest.mark.parametrize("api_source,direction,close_price,expected", [
    ("SYSTEM", "BUY",  1.1040, "TP"),   # BUY at tp_level
    ("SYSTEM", "BUY",  1.0980, "SL"),   # BUY at sl_level
    ("SYSTEM", "SELL", 1.0960, "TP"),   # SELL at tp_level (fp - tp_dist)
    ("SYSTEM", "SELL", 1.1020, "SL"),   # SELL at sl_level (fp + sl_dist)
    ("SYSTEM", "BUY",  1.1010, "SL"),   # equidistant → SL tie-break
    ("USER",   "BUY",  9999.0, "USER"),
    ("CLOSE_OUT", "BUY", 9999.0, "CLOSE_OUT"),
    ("SYSTEM", "buy",  1.1040, "TP"),   # mixed-case accepted
    ("TP", "BUY", 9999.0, "TP"),        # Capital demo gives explicit TP
    ("SL", "BUY", 9999.0, "SL"),        # Capital demo gives explicit SL
    ("TP", "SELL", 9999.0, "TP"),       # explicit source ignores price/direction
])
def test_derive_close_source_parametrized(api_source, direction, close_price, expected):
    result = derive_close_source(api_source, close_price, _FP, _SL_DIST, _TP_DIST, direction)
    assert result == expected


def test_invalid_direction_raises():
    with pytest.raises(ValueError):
        derive_close_source("SYSTEM", 1.1000, _FP, _SL_DIST, _TP_DIST, "LONG")


def test_empty_direction_raises():
    with pytest.raises(ValueError):
        derive_close_source("SYSTEM", 1.1000, _FP, _SL_DIST, _TP_DIST, "")
