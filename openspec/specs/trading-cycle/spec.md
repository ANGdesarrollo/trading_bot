# Spec: trading-cycle

**Capability:** trading-cycle
**Status:** active
**Source:** ws-candle-ingestion change (modified)

---

## Overview

`RunTradingCycleUseCase` is modified to read candles from `CandleStorePort` instead of `BrokerPort`. The freshness-retry loop is removed entirely. A `resolution: str` parameter is added to `__init__` (sourced from `config.timeframe` in wiring). The use case becomes a pure Postgres reader with a single staleness check.

---

## Requirements

**TC-01.** `RunTradingCycleUseCase.__init__` SHALL accept a `candle_store: CandleStorePort` dependency and a `resolution: str` parameter (sourced from `config.timeframe` at composition root). The `BrokerPort` dependency remains for `open_position` and `has_open_position`. The constructor SHALL NOT include `freshness_max_retries` or `freshness_retry_seconds`.

#### Scenario: constructor accepts candle_store and resolution (AC-TC-4)
Given a `RunTradingCycleUseCase` class definition,
when it is instantiated with `candle_store=<CandleStorePort>` and `resolution="MINUTE_15"`,
then the instance is created without error.

#### Scenario: no retry parameters in constructor (AC-TC-4)
Given the `RunTradingCycleUseCase.__init__` signature,
when it is inspected,
then `freshness_max_retries` and `freshness_retry_seconds` are NOT present as parameters.

---

**TC-02.** `RunTradingCycleUseCase.execute` SHALL call `candle_store.recent_candles(symbol, resolution, strategy.required_candles)` to obtain candles, passing both the symbol and the injected resolution.

#### Scenario: execute calls recent_candles with symbol, resolution, and count
Given a mock `CandleStorePort` that records call arguments,
when `execute` is called,
then `recent_candles` is called with positional args `(symbol, resolution, strategy.required_candles)` in that order.

---

**TC-03.** The freshness retry loop (former `trading_cycle.py:53-66`) SHALL be removed entirely. No REST retry, no `freshness_max_retries`, no `freshness_retry_seconds` in the constructor or config.

#### Scenario: no broker.recent_candles call in stale path (AC-TC-2)
Given the store returns 128 candles but the newest candle's timestamp does not equal `expected_decision_ts`,
when `execute` is called,
then the return value is `None`, a warning is logged, and `broker.recent_candles` is NEVER called (the method no longer exists on `BrokerPort`).

---

**TC-04.** `RunTradingCycleUseCase.execute` SHALL perform a single staleness check: if the store's newest candle's `timestamp` does not equal `expected_decision_ts`, it SHALL log a warning and return `None`. No retry, no broker call.

#### Scenario: stale candle logs warning and returns None
Given the store returns `required_candles` candles but the newest candle's `timestamp` differs from `expected_decision_ts`,
when `execute` is called,
then a warning is logged, `None` is returned, and no order is placed.

---

**TC-05.** If `candle_store.recent_candles` returns fewer items than `strategy.required_candles`, `execute` SHALL return `None` without raising. This is the startup-race guard.

#### Scenario: short store returns None (AC-TC-1)
Given `CandleStorePort.recent_candles` returns 5 candles when `required_candles` is 128,
when `execute` is called,
then the return value is `None` and `broker.open_position` is NOT called.

---

**TC-06.** When the store is both fresh (newest candle == expected boundary) and full (count >= required_candles), `execute` SHALL call `strategy.evaluate(candles)` and, if a signal is returned, call `broker.open_position` — the order path is unchanged.

#### Scenario: fresh full store calls strategy then broker (AC-TC-3)
Given the store returns exactly 128 candles with the newest timestamp equal to `expected_decision_ts`,
and `strategy.evaluate` returns a non-None signal,
when `execute` is called,
then `broker.open_position` is called exactly once with the signal.

#### Scenario: open position skips cycle (AC-TC-5)
Given `broker.has_open_position` returns `True`,
when `execute` is called,
then `candle_store.recent_candles` is NOT called and the return value is `None`.

---
