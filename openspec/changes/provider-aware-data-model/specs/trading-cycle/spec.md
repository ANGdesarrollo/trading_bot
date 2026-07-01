# Delta for trading-cycle

## MODIFIED Requirements

### Requirement: TC-02 — execute Reads Candles with Provider

`RunTradingCycleUseCase.execute` SHALL call `candle_store.recent_candles(provider, symbol, resolution, strategy.required_candles)` to obtain candles, passing the injected provider, the symbol, and the injected resolution. `provider` is injected at construction time from `Config.provider`.

(Previously: `recent_candles` was called with `(symbol, resolution, strategy.required_candles)` — no provider argument.)

#### Scenario: execute calls recent_candles with provider, symbol, resolution, and count

- GIVEN a mock `CandleStorePort` that records call arguments
- AND `RunTradingCycleUseCase` constructed with `provider="capital"`
- WHEN `execute` is called
- THEN `recent_candles` is called with positional args `("capital", symbol, resolution, strategy.required_candles)` in that order

---

## ADDED Requirements

### Requirement: TC-07 — JournalEntry Provider Stamping

`JournalEntry` SHALL carry a `provider: str` field defaulting to `"capital"`. `RunTradingCycleUseCase._build_entry` SHALL stamp each `JournalEntry` with the provider injected at construction time.

#### Scenario: _build_entry stamps provider from injected value

- GIVEN `RunTradingCycleUseCase` constructed with `provider="capital"`
- WHEN `_build_entry` is called to produce a `JournalEntry`
- THEN `entry.provider` equals `"capital"`

#### Scenario: JournalEntry is immutable with provider field

- GIVEN a `JournalEntry` constructed with `provider="capital"`
- WHEN an attempt is made to set `provider` after construction
- THEN an `AttributeError` (or equivalent frozen-dataclass error) is raised

#### Scenario: JournalEntry defaults provider to "capital"

- GIVEN a `JournalEntry` constructed without an explicit `provider` argument
- WHEN `entry.provider` is accessed
- THEN it equals `"capital"`

---

### Requirement: TC-08 — TradingCycle Provider Injection

`RunTradingCycleUseCase.__init__` SHALL accept a `provider: str` parameter defaulting to `"capital"`. The provider SHALL be forwarded to both `recent_candles` calls and `_build_entry`.

#### Scenario: constructor accepts provider parameter

- GIVEN a `RunTradingCycleUseCase` class definition
- WHEN it is instantiated with `provider="capital"` alongside existing required parameters
- THEN the instance is created without error

#### Scenario: omitting provider defaults to "capital"

- GIVEN a `RunTradingCycleUseCase` instantiated without a `provider` argument
- WHEN `execute` is called and a trade entry is built
- THEN `entry.provider` equals `"capital"` and `recent_candles` receives `"capital"` as its first argument

---
