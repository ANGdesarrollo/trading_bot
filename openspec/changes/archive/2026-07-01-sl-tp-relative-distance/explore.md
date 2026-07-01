# Explore: sl-tp-relative-distance

## Executive Summary

Switch `CapitalBrokerAdapter.open_position` from sending absolute `stopLevel`/`profitLevel` to relative `stopDistance`/`profitDistance`. The cleanest implementation replaces Signal's `stop_loss`/`take_profit`/`entry_reference` fields with `sl_distance`/`tp_distance`, letting the adapter forward the values directly without re-deriving anything. Blast radius: 4 source files, 3 unit tests rewritten, 1 integration test one-line update.

---

## 1. Current Signal Entity Shape

`src/domain/entities/signal.py`

```python
@dataclass(frozen=True, slots=True)
class Signal:
    direction: Direction
    entry_reference: float   # c[-1] — signal-bar close; misaligned from actual fill
    stop_loss: float         # absolute price: entry_reference ± sl_dist
    take_profit: float       # absolute price: entry_reference ± tp_dist

    def __post_init__(self):
        # enforces ordering: BUY: sl < entry < tp; SELL: tp < entry < sl
```

The docstring explicitly states: _"The strategy emits stop_loss and take_profit as absolute prices so the engine never re-derives risk from broker-specific units."_ This design decision is now invalidated by the verified Capital.com behavior.

---

## 2. Field Consumer Map

| Field | Consumer | Location | Notes |
|---|---|---|---|
| `signal.entry_reference` | `_build_signal()` | `fade_strategy.py:83–99` | Used as anchor for absolute SL/TP computation |
| `signal.entry_reference` | `RunTradingCycleUseCase.execute()` | `trading_cycle.py:43` | Logged for fill-variance monitoring |
| `signal.stop_loss` | `_build_signal()` | `fade_strategy.py:92,98` | Set to `entry_reference ± sl_dist` |
| `signal.stop_loss` | `CapitalBrokerAdapter.open_position()` | `broker.py:68` | Sent as `stopLevel` |
| `signal.take_profit` | `_build_signal()` | `fade_strategy.py:93,99` | Set to `entry_reference ± tp_dist` |
| `signal.take_profit` | `CapitalBrokerAdapter.open_position()` | `broker.py:69` | Sent as `profitLevel` |
| `signal.stop_loss`, `signal.entry_reference` | `test_aggressive_bar_produces_valid_signal` | `test_fade_strategy.py:167–177` | Asserts entry_reference == candles[-1].close, ordering invariant |
| `signal.stop_loss`, `signal.take_profit`, `signal.entry_reference` | `test_open_position_posts_correct_body` | `test_capital_broker.py:113–141` | Constructs Signal with absolute values, asserts stopLevel/profitLevel |
| `signal.stop_loss`, `signal.entry_reference` | `test_anti_drift_signal_matches_backtest` | `test_fade_strategy_anti_drift.py:176–177` | `abs(signal.stop_loss - signal.entry_reference)` and `abs(signal.take_profit - signal.entry_reference)` |

---

## 3. The Bug in Detail

`_build_signal` at `fade_strategy.py:70` is called with `float(c[-1])` — the close of the last closed bar (the signal bar). This becomes `entry_reference`. SL and TP are then set as absolute prices anchored to that close.

The broker sends these absolute prices as `stopLevel`/`profitLevel`. Capital.com interprets these as exact price levels for the SL/TP triggers. But the actual fill happens at the open of the next bar (what the backtest calls `o[entry_i]`). The gap between `c[run_end+1-1]` (the close) and `o[run_end+1]` (the next open) is the anchor misalignment — typically 0–3 pips but structurally wrong at all times.

With `stopDistance`/`profitDistance`, Capital.com anchors to the actual fill price regardless of when/where it executes. Verified demo order: BUY, stopDistance=profitDistance=0.0020 → fill=1.14074, stopLevel=1.13874 (fill − 0.00200), profitLevel=1.14274 (fill + 0.00200).

The distances the adapter already computes internally (`sl_dist = SL_ATR_MULT * atr_e`, `tp_dist = RR * sl_dist`) ARE the correct values — they just get buried in the absolute level conversion instead of being surfaced.

---

## 4. Approach Comparison

| Approach | Description | Pros | Cons | Effort |
|---|---|---|---|---|
| **A — Relative distances on Signal** (recommended) | Replace `stop_loss`/`take_profit`/`entry_reference` with `sl_distance`/`tp_distance` on Signal. Broker sends `stopDistance`/`profitDistance`. | Domain contract matches what the broker actually uses. No anchor leaks into domain. `__post_init__` becomes simpler (both distances > 0). Anti-drift test is trivially updated. | Signal shape changes — all Signal constructors in tests must be updated. | 4 source files, ~30 lines |
| **B — Distances computed in broker** | Keep Signal shape unchanged. Broker derives `sl_distance = abs(signal.stop_loss - signal.entry_reference)` and sends `stopDistance`. | Zero domain changes. Existing Signal unit tests pass unchanged. | Broker re-derives risk from domain fields — the exact coupling the docstring says to avoid. If entry_reference semantics drift again, broker silently gets wrong distances. | 2 source files, ~5 lines |
| **C — New parallel fields** | Add `sl_distance`/`tp_distance` alongside existing fields. Broker uses new fields. | No breaking change to Signal consumers. | Redundant state in Signal — two ways to express the same risk. `__post_init__` must validate consistency between absolute and relative fields. Leaves dead fields that will mislead future readers. | 4 source files, higher complexity |

**Recommendation: Approach A.**

Rationale:
- The original design rationale ("broker never re-derives risk") still holds — it just means Signal should carry the canonical risk distances, not absolute levels anchored to a stale price.
- `entry_reference` is now architecturally wrong: the adapter cannot know the fill price at signal time, so any anchor is speculative. Removing it makes the contract honest.
- The anti-drift test checks `abs(signal.stop_loss - signal.entry_reference)` — a direct rename to `signal.sl_distance` makes it cleaner, not harder.
- `trading_cycle.py` logs `entry_reference` for fill-variance monitoring. With Approach A, this log line is dropped (the adapter no longer knows the entry price). The fill is still logged via `result.filled_price`. This is acceptable — if fill-variance monitoring matters, it belongs in a post-fill analytics layer, not in the signal.

---

## 5. Exact Files to Change

### Source files

| File | Change |
|---|---|
| `src/domain/entities/signal.py` | Replace `entry_reference: float`, `stop_loss: float`, `take_profit: float` with `sl_distance: float`, `tp_distance: float`. Update `__post_init__` to assert both > 0. Update docstring. |
| `src/domain/adapters/fade_strategy.py` | `_build_signal`: remove `entry_reference` parameter and absolute level computation. Construct `Signal(direction=..., sl_distance=sl_dist, tp_distance=tp_dist)`. |
| `src/infrastructure/capital/broker.py` | `open_position`: replace `"stopLevel": signal.stop_loss, "profitLevel": signal.take_profit` with `"stopDistance": signal.sl_distance, "profitDistance": signal.tp_distance`. |
| `src/application/trading_cycle.py` | Remove `"entry_reference": signal.entry_reference` from the log `extra` dict (field no longer exists). |

### Test files

| File | Change |
|---|---|
| `tests/unit/test_fade_strategy.py` | Remove `entry_reference` assertion. Replace `abs(signal.stop_loss - signal.entry_reference)` with `signal.sl_distance`. |
| `tests/unit/test_capital_broker.py` | Three `Signal(...)` constructors: replace kwargs with `sl_distance`/`tp_distance`. Update assertions: `body["stopDistance"]`/`body["profitDistance"]`. |
| `tests/integration/test_fade_strategy_anti_drift.py` | Replace `abs(signal.stop_loss - signal.entry_reference)` → `signal.sl_distance`; `abs(signal.take_profit - signal.entry_reference)` → `signal.tp_distance`. |
| `tests/unit/test_trading_cycle.py` | Signal constructor: replace with `sl_distance`/`tp_distance`. Remove `entry_reference` assertions. |

### New tests to add

| Test | File | What it verifies |
|---|---|---|
| `test_open_position_sends_stop_distance_not_level` | `test_capital_broker.py` | POST body contains `stopDistance`/`profitDistance` and NOT `stopLevel`/`profitLevel`. |
| `test_build_signal_returns_relative_distances` | `test_fade_strategy.py` | `_build_signal` returns Signal with `sl_distance == SL_ATR_MULT * atr_e` and `tp_distance == RR * sl_distance`. |

---

## 6. Anti-Drift Guarantee: Impact Assessment

The anti-drift test check becomes:

```python
actual_sl_dist = signal.sl_distance
actual_tp_dist = signal.tp_distance
```

The comparison logic (`expected_sl_dist = SL_ATR_MULT * atr_at_endpoint`, tolerance 1e-6) is unchanged. The frozen-lib anti-drift guarantee is fully preserved — the adapter still calls `_aggressive_episodes` and `compute_atr` from the frozen research lib.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Capital.com treats distances in pips vs price units per instrument | Medium | Confirmed via demo order (EURUSD, price units). Verify per additional symbol before going live. |
| `entry_reference` removal breaks fill-variance monitoring | Low | `result.filled_price` is still logged. |
| Signal `__post_init__` loses ordering invariant | None | New invariant (`sl_distance > 0`, `tp_distance > 0`) is strictly correct. |

---

## 8. Summary

- **Blast radius**: 4 source files (~30 lines), 3 unit test files, 1 integration test (2-line update)
- **Anti-drift test**: safe
- **Recommended approach**: A (relative distances on Signal)
- **No frozen-lib changes required**
