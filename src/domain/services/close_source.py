from __future__ import annotations


def derive_close_source(
    api_source: str,
    close_price: float,
    filled_price: float,
    sl_distance: float,
    tp_distance: float,
    direction: str,
) -> str:
    if api_source in ("USER", "CLOSE_OUT"):
        return api_source
    if api_source != "SYSTEM":
        return "USER"
    d = direction.strip().upper()
    if d == "BUY":
        sl_level, tp_level = filled_price - sl_distance, filled_price + tp_distance
    elif d == "SELL":
        sl_level, tp_level = filled_price + sl_distance, filled_price - tp_distance
    else:
        raise ValueError(f"invalid direction: {direction!r}")
    return "SL" if abs(close_price - sl_level) <= abs(close_price - tp_level) else "TP"
