# Proposal: sl-tp-relative-distance

## Intent

**Problem.** The live fade adapter anchors SL/TP to the wrong price. `fade_strategy.py` computes stop-loss and take-profit as ABSOLUTE price levels anchored to `c[-1]` (the signal bar's close), and `broker.py` forwards them to Capital.com as absolute `stopLevel`/`profitLevel`. But the real fill is the OPEN of the next bar. That gap between the signal-bar close and the actual fill (typically 0–3 pips, but structurally wrong at all times) means the live SL/TP distances silently diverge from the backtest risk model on every trade.

**Why now.** A real Capital.com demo order today confirmed the fix: POST `/positions` accepts RELATIVE `stopDistance`/`profitDistance` in PRICE units and anchors them to the ACTUAL fill (verified: BUY, stopDistance=profitDistance=0.0020 → fill=1.14074, stopLevel=1.13874, profitLevel=1.14274). This removes the anchor entirely rather than trying to predict the next-bar open. The correct distances (`sl_dist = SL_ATR_MULT * atr_e`, `tp_dist = RR * sl_dist`) are already computed internally — they are just buried in the absolute-level conversion instead of being surfaced.

**Success.** Live orders carry the exact risk distances the backtest uses, anchored to the real fill. `stopDistance`/`profitDistance` are sent instead of `stopLevel`/`profitLevel`. The anti-drift guarantee holds unchanged (distances are mathematically identical to today's values). No frozen research-lib changes.

## In Scope

- Replace Signal's `entry_reference` / `stop_loss` / `take_profit` fields with `sl_distance` / `tp_distance` (Approach A).
- Adapter (`fade_strategy.py`) emits distances directly: `sl_dist = SL_ATR_MULT * atr_e`, `tp_dist = RR * sl_dist`.
- Broker (`broker.py`) sends `stopDistance` / `profitDistance` instead of `stopLevel` / `profitLevel`.
- Drop the now-unavailable `entry_reference` log line in `trading_cycle.py` (fill is still logged via `result.filled_price`).
- Update affected unit + integration tests; add two new tests asserting the relative-distance contract.

## Out of Scope (conscious debt, not this change)

- Swap / rollover cost modeling.
- Slippage projection.
- Broker-specific size min/step validation.
- Post-fill fill-variance analytics layer (replacement for the dropped `entry_reference` monitoring).
- `sys.path` shim cleanup.

## Approach (A — relative distances on Signal)

Signal carries the canonical risk distances, not absolute levels anchored to a stale price. This keeps the original design intent ("the broker never re-derives risk") honest: the broker forwards distances the adapter already computed, rather than reconstructing them from a speculative anchor.

- `signal.py`: fields become `sl_distance: float`, `tp_distance: float`. `__post_init__` asserts both `> 0`. Docstring updated to state distances are broker-anchored to the fill.
- `fade_strategy.py`: `_build_signal` drops the `entry_reference` parameter and absolute-level math; constructs `Signal(direction=..., sl_distance=sl_dist, tp_distance=tp_dist)`.
- `broker.py`: `open_position` sends `"stopDistance": signal.sl_distance`, `"profitDistance": signal.tp_distance`.
- `trading_cycle.py`: remove `entry_reference` from the log `extra` dict.

Rejected alternatives: B (broker re-derives distances from domain fields) reintroduces the exact coupling the design forbids; C (parallel absolute + relative fields) leaves redundant, misleading state.

## Impact

**Source (4 files, ~30 lines):** `src/domain/entities/signal.py`, `src/domain/adapters/fade_strategy.py`, `src/infrastructure/capital/broker.py`, `src/application/trading_cycle.py`.

**Tests:** rewrite Signal constructors and assertions in `tests/unit/test_fade_strategy.py`, `tests/unit/test_capital_broker.py`, `tests/unit/test_trading_cycle.py`, and `tests/integration/test_fade_strategy_anti_drift.py` (2-line rename to `signal.sl_distance` / `signal.tp_distance`). Add `test_open_position_sends_stop_distance_not_level` and `test_build_signal_returns_relative_distances`.

**Guarantees preserved:** no frozen research-lib changes; anti-drift test intact (distances mathematically identical to current values); live distances match the backtest risk model exactly.

Single-PR small change.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Capital.com interprets distances in pips vs price units per instrument | Medium | Confirmed price units via demo order (EURUSD). Verify per additional symbol before going live. |
| Dropping `entry_reference` removes fill-variance monitoring input | Low | `result.filled_price` still logged; dedicated analytics layer is explicit out-of-scope debt. |
| Signal ordering invariant (`sl < entry < tp`) is lost | None | Replaced by strictly correct invariant `sl_distance > 0`, `tp_distance > 0`. |
