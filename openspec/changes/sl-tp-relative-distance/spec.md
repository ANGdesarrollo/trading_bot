# Spec: sl-tp-relative-distance

## Delta Description

Replace Signal's absolute SL/TP price levels and entry anchor with relative risk distances. The broker forwards those distances to Capital.com as `stopDistance`/`profitDistance` so the exchange anchors SL/TP to the actual fill, eliminating the structural entry-anchor misalignment.

---

## REQ-1 Signal entity carries relative distances, not absolute levels

**What must be true after the change:**

- `Signal` has exactly two risk fields: `sl_distance: float` and `tp_distance: float`.
- `Signal` does NOT have `stop_loss`, `take_profit`, or `entry_reference` fields.
- `Signal.__post_init__` enforces `sl_distance > 0` AND `tp_distance > 0`; violating either raises `ValueError`.
- `sl_distance` and `tp_distance` are broker-unit price distances, not pips.

### Scenario 1.1 — Valid distances are accepted

```
Given sl_distance = 0.0020 and tp_distance = 0.0040
When Signal(direction=BUY, sl_distance=0.0020, tp_distance=0.0040) is constructed
Then the signal is created without error
And signal.sl_distance == 0.0020
And signal.tp_distance == 0.0040
```

### Scenario 1.2 — Zero sl_distance is rejected

```
Given sl_distance = 0.0
When Signal(direction=BUY, sl_distance=0.0, tp_distance=0.0040) is constructed
Then ValueError is raised
```

### Scenario 1.3 — Negative tp_distance is rejected

```
Given tp_distance = -0.0010
When Signal(direction=BUY, sl_distance=0.0020, tp_distance=-0.0010) is constructed
Then ValueError is raised
```

---

## REQ-2 Fade adapter emits distances derived from episode ATR

**What must be true after the change:**

- `FadeStrategyAdapter._build_signal` constructs `Signal` with:
  - `sl_distance = SL_ATR_MULT * atr_e`
  - `tp_distance = RR * sl_distance`
  where `atr_e` is the ATR of the aggressive-exhaustion episode, `SL_ATR_MULT` and `RR` are the frozen backtest constants.
- The adapter does NOT compute or store any absolute price level.
- The adapter does NOT pass `entry_reference` to `Signal`.
- The direction in the emitted signal is the fade direction (opposite to the exhaustion direction).

### Scenario 2.1 — BUY fade signal distances

```
Given a bearish aggressive-exhaustion episode with atr_e = 0.0010
And SL_ATR_MULT = 1.5 and RR = 2.0
When FadeStrategyAdapter detects the episode and builds a signal
Then signal.direction == BUY
And signal.sl_distance == 0.0015          (1.5 * 0.0010)
And signal.tp_distance == 0.0030          (2.0 * 0.0015)
```

### Scenario 2.2 — SELL fade signal distances

```
Given a bullish aggressive-exhaustion episode with atr_e = 0.0008
And SL_ATR_MULT = 1.5 and RR = 2.0
When FadeStrategyAdapter detects the episode and builds a signal
Then signal.direction == SELL
And signal.sl_distance == 0.0012          (1.5 * 0.0008)
And signal.tp_distance == 0.0024          (2.0 * 0.0012)
```

---

## REQ-3 Broker sends relative distance keys to Capital.com

**What must be true after the change:**

- `CapitalBrokerAdapter.open_position` includes `"stopDistance"` and `"profitDistance"` in the POST body.
- The POST body does NOT contain `"stopLevel"` or `"profitLevel"`.
- `body["stopDistance"] == signal.sl_distance`
- `body["profitDistance"] == signal.tp_distance`

### Scenario 3.1 — POST body contains stopDistance and profitDistance

```
Given a Signal with sl_distance=0.0020 and tp_distance=0.0040
When CapitalBrokerAdapter.open_position(signal) is called
Then the HTTP POST body contains key "stopDistance" with value 0.0020
And the HTTP POST body contains key "profitDistance" with value 0.0040
And the HTTP POST body does NOT contain key "stopLevel"
And the HTTP POST body does NOT contain key "profitLevel"
```

### Scenario 3.2 — Distance values are forwarded verbatim

```
Given a Signal with sl_distance=0.0015 and tp_distance=0.0030
When CapitalBrokerAdapter.open_position(signal) is called
Then body["stopDistance"] == signal.sl_distance
And body["profitDistance"] == signal.tp_distance
```

---

## REQ-4 Anti-drift guarantee: live distances match frozen backtest within tolerance

**What must be true after the change:**

- For any candle window that the frozen research lib processes, the `sl_distance` and `tp_distance` emitted by `FadeStrategyAdapter` agree with the expected values (`SL_ATR_MULT * atr_at_endpoint` and `RR * sl_dist`) within an absolute tolerance of 1e-6.
- The frozen research lib (`_aggressive_episodes`, `compute_atr`) is NOT modified.
- The anti-drift integration test assertion changes only in field names (`signal.sl_distance` / `signal.tp_distance`), not in computation or tolerance.

### Scenario 4.1 — Live adapter matches backtest distances

```
Given a fixed candle window processed by the frozen research lib
And expected_sl_dist = SL_ATR_MULT * atr_at_endpoint
And expected_tp_dist = RR * expected_sl_dist
When FadeStrategyAdapter processes the same candle window
Then abs(signal.sl_distance - expected_sl_dist) < 1e-6
And abs(signal.tp_distance - expected_tp_dist) < 1e-6
```

---

## Non-Goals (explicit exclusions from this spec)

- Swap / rollover cost modeling.
- Slippage projection.
- Broker-specific size min/step validation.
- Post-fill fill-variance analytics (dropped `entry_reference` log line is acceptable debt).
- Per-instrument distance unit verification beyond EURUSD demo confirmation.
