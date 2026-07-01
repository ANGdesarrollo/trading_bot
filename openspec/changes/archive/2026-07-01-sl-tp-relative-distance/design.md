# Design: sl-tp-relative-distance

## Architecture

Approach A — canonical risk distances on the `Signal` entity. No new abstractions,
no new modules. The domain entity changes shape; three consumers (adapter, broker,
use case) follow the field rename. The layering is untouched: strategy builds the
Signal, broker forwards it. The only architectural shift is WHAT the Signal
carries — relative distances instead of stale absolute levels.

Data flow (unchanged topology, changed payload):

```
FadeStrategy.evaluate
  -> _build_signal(episode, atr_e)          # drops entry_reference param
       -> Signal(direction, sl_distance, tp_distance)
CapitalBrokerAdapter.open_position
  -> POST /positions { stopDistance, profitDistance }   # was stopLevel/profitLevel
RunTradingCycleUseCase.execute
  -> log { filled_price }                    # entry_reference dropped from extra
```

Capital.com anchors `stopDistance`/`profitDistance` to the ACTUAL fill, so the
speculative `entry_reference` anchor is deleted from the domain entirely.

---

## 1. Signal entity (`src/domain/entities/signal.py`)

**Before**

```python
@dataclass(frozen=True, slots=True)
class Signal:
    direction: Direction
    entry_reference: float
    stop_loss: float
    take_profit: float

    def __post_init__(self) -> None:
        if self.direction is Direction.BUY:
            if not (self.stop_loss < self.entry_reference < self.take_profit):
                raise ValueError("BUY requires stop_loss < entry < take_profit")
        elif not (self.take_profit < self.entry_reference < self.stop_loss):
            raise ValueError("SELL requires take_profit < entry < stop_loss")
```

**After**

```python
@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's decision to enter a trade, expressed as risk distances.

    sl_distance and tp_distance are relative price offsets the broker anchors
    to the actual fill, so the engine never re-derives risk from a speculative
    signal-time price.
    """

    direction: Direction
    sl_distance: float
    tp_distance: float

    def __post_init__(self) -> None:
        if self.sl_distance <= 0:
            raise ValueError("sl_distance must be > 0")
        if self.tp_distance <= 0:
            raise ValueError("tp_distance must be > 0")
```

The BUY/SELL ordering invariant is deleted — it was an artifact of absolute levels.
`direction` still drives the broker's `BUY`/`SELL` field; distances are always
positive regardless of direction. `frozen=True, slots=True` unchanged.

---

## 2. `_build_signal` (`src/domain/adapters/fade_strategy.py`)

**Signature change**: drop the third `entry_reference` parameter. The distances
are already computed — surface them directly instead of converting to absolute
levels.

**After**

```python
def _build_signal(episode, atr_e: float) -> Signal:
    fade = -episode.direction
    sl_dist = SL_ATR_MULT * atr_e
    tp_dist = RR * sl_dist
    direction = Direction.BUY if fade == 1 else Direction.SELL
    return Signal(
        direction=direction,
        sl_distance=sl_dist,
        tp_distance=tp_dist,
    )
```

**Call site** (`evaluate`, line 70): `return _build_signal(episode, atr_e)`.

Collapses two near-identical branches into one — direction is the only value that
depended on `fade`, and distances are direction-independent (DRY win). The
comment at lines 51-54 mentioning "we use its close for entry_reference" must be
updated to drop the entry_reference clause; the entry-bar-not-fed-to-detector
rationale stays. `float(c[-1])` is no longer passed but `c` is still used by
`_to_numpy_arrays`, so no import churn.

---

## 3. Broker POST body (`src/infrastructure/capital/broker.py`)

`open_position`, lines 68-69:

**Before**

```python
"stopLevel": signal.stop_loss,
"profitLevel": signal.take_profit,
```

**After**

```python
"stopDistance": signal.sl_distance,
"profitDistance": signal.tp_distance,
```

Nothing else in the method changes. `direction` field, `guaranteedStop`, confirm
flow, and `OrderResult` construction are untouched.

---

## 4. Trading cycle log (`src/application/trading_cycle.py`)

`execute`, lines 42-45 — remove the `entry_reference` key:

**After**

```python
self._logger.info(
    "order placed",
    extra={"filled_price": result.filled_price},
)
```

`filled_price` still logged. No other line touched.

---

## 5. Test migration plan

**Constructor + assertion rewrites (existing):**

- `tests/unit/test_capital_broker.py`
  - Three `Signal(...)` constructors (lines ~114, ~145, and the third): replace
    `entry_reference/stop_loss/take_profit` kwargs with `sl_distance=...,
    tp_distance=...` (positive values, e.g. `sl_distance=0.0020, tp_distance=0.0020`).
  - `test_open_position_posts_correct_body` (lines 140-141): assert
    `body["stopDistance"]` / `body["profitDistance"]` instead of
    `stopLevel`/`profitLevel`.
- `tests/unit/test_fade_strategy.py`
  - `test_aggressive_bar_produces_valid_signal` (lines 167-177): delete the
    `entry_reference == candles[-1].close` assertion and the BUY/SELL ordering
    block. Replace `sl_dist = abs(signal.stop_loss - signal.entry_reference)`
    with `sl_dist = signal.sl_distance`, `tp_dist = signal.tp_distance`. Keep the
    `tp_dist == RR * sl_dist` check.
- `tests/unit/test_trading_cycle.py`
  - `_make_signal` (lines 45-51): swap to `sl_distance=0.0020, tp_distance=0.0020`.
    No `entry_reference` assertions exist elsewhere in this file, so no other edits.

**Anti-drift rename (integration):** covered in Section 6.

**Two new tests:**

- `test_open_position_sends_stop_distance_not_level` (`test_capital_broker.py`):
  build a Signal with known distances, call `open_position`, assert
  `"stopDistance" in body and "profitDistance" in body` AND
  `"stopLevel" not in body and "profitLevel" not in body`. This locks the
  contract against regression to absolute levels.
- `test_build_signal_returns_relative_distances` (`test_fade_strategy.py`):
  drive `_build_signal(episode, atr_e)` (or `evaluate` on the aggressive window)
  and assert `signal.sl_distance == pytest.approx(SL_ATR_MULT * atr_e)` and
  `signal.tp_distance == pytest.approx(RR * signal.sl_distance)`.

---

## 6. Anti-drift preservation

`tests/integration/test_fade_strategy_anti_drift.py`, lines 176-177 only:

```python
actual_sl_dist = signal.sl_distance      # was: abs(signal.stop_loss - signal.entry_reference)
actual_tp_dist = signal.tp_distance      # was: abs(signal.take_profit - signal.entry_reference)
```

`expected_sl_dist = SL_ATR_MULT * atr_at_endpoint` and the `1e-6` tolerance are
unchanged. The adapter still calls `_aggressive_episodes` and `compute_atr` from
the frozen research lib, and the emitted distances are the SAME float values as
today (`SL_ATR_MULT * atr_e`, `RR * sl_dist`) — previously buried in the absolute
subtraction, now surfaced directly. The rename reads the value directly instead
of reconstructing it, so the guarantee is preserved and the comparison is
strictly cleaner. No frozen-lib code is modified.

---

## 7. Strict TDD ordering

RED tests first, in this sequence:

1. **`test_build_signal_returns_relative_distances`** (fade_strategy) — RED first.
   It fails at collection/attribute time because `Signal` has no `sl_distance`.
   Drives the entity change (Section 1) AND `_build_signal` (Section 2). This is
   the root of the change: the entity shape and the producer must land together
   for any Signal to be constructible.
2. **`test_open_position_sends_stop_distance_not_level`** (broker) — RED second.
   Once Signal carries distances, this drives the POST body change (Section 3).
3. Migrate the existing constructor/assertion tests (Section 5) — they go RED the
   moment the entity changes; update them to GREEN alongside steps 1-2.
4. Update the anti-drift rename (Section 6) last — it is a pure read-site rename,
   goes RED on the field removal, GREEN on the two-line edit, and serves as the
   final regression gate confirming distances are mathematically identical.

Rationale for #1 first: the entity is the keystone. Every other test depends on
`Signal` being constructible with the new fields, so the entity + producer RED→GREEN
must precede the broker and use-case work.

---

## ADR — decisions

- **Decision:** Replace `entry_reference/stop_loss/take_profit` with
  `sl_distance/tp_distance` on Signal.
  **Rationale:** Capital.com anchors relative distances to the real fill; the
  signal-time anchor is speculative and structurally wrong. Distances are already
  computed internally.
  **Rejected — B (broker re-derives distances):** reintroduces the broker
  re-deriving risk from domain fields, the exact coupling the original docstring
  forbids.
  **Rejected — C (parallel absolute + relative fields):** redundant, misleading
  state; `__post_init__` would have to validate two representations of one truth.

- **Decision:** Drop the BUY/SELL ordering invariant, replace with
  `sl_distance > 0`, `tp_distance > 0`.
  **Rationale:** ordering was an artifact of absolute levels; positivity is the
  strictly correct invariant for distances.

- **Decision:** Delete the `entry_reference` log line rather than replace it.
  **Rationale:** the adapter cannot know the fill at signal time. Fill-variance
  monitoring, if needed, belongs in a post-fill analytics layer (explicit
  out-of-scope debt). `result.filled_price` is still logged.
