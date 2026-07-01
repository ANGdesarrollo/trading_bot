# Delta for capital-session

## ADDED Requirements

### Requirement: CS-05 — Capital Producers Accept Injected Provider

`CapitalWsIngester`, `CapitalCandleHistory`, and `PairBuffer` SHALL each accept a `provider: str` constructor parameter defaulting to `"capital"`. Every `CandleRow` they emit SHALL have `row.provider` set to the injected value. Provider SHALL NOT be parsed from WebSocket payloads or HTTP responses.

#### Scenario: CapitalWsIngester stamps provider on emitted CandleRow

- GIVEN `CapitalWsIngester` constructed with `provider="capital"`
- WHEN a candle is completed and a `CandleRow` is emitted
- THEN `row.provider` equals `"capital"`

#### Scenario: CapitalCandleHistory stamps provider on each fetched CandleRow

- GIVEN `CapitalCandleHistory` constructed with `provider="capital"`
- WHEN `fetch_history` returns a list of `CandleRow` objects
- THEN every `row.provider` in the list equals `"capital"`

#### Scenario: PairBuffer stamps provider on completed candle

- GIVEN `PairBuffer` constructed with `provider="capital"`
- WHEN a candle close is triggered and a `CandleRow` is produced
- THEN `row.provider` equals `"capital"`

#### Scenario: provider is not sourced from WS payload

- GIVEN `CapitalWsIngester` constructed with `provider="capital"`
- AND a WS payload that contains no provider field
- WHEN the payload is processed
- THEN `row.provider` still equals `"capital"` (injected value is used, not payload-derived)

---

### Requirement: CS-06 — Composition Roots Wire Provider from Config

The composition roots (`__main__.py`, `ingestion.py`, `reconciler.py`) SHALL read `config.provider` and pass it to every Capital producer and to `RunTradingCycleUseCase` at construction time. No hardcoded `"capital"` string SHALL appear in composition roots.

#### Scenario: ingestion composition root passes config.provider to producers

- GIVEN `config.provider` equals `"capital"` (from env or default)
- WHEN the ingestion process starts and constructs `CapitalWsIngester` and `CapitalCandleHistory`
- THEN both are constructed with `provider="capital"` derived from `config.provider`

#### Scenario: changing PROVIDER env var changes what producers stamp

- GIVEN the `PROVIDER` environment variable is set to `"ic_markets"` before process start
- WHEN a producer emits a `CandleRow`
- THEN `row.provider` equals `"ic_markets"`

---
