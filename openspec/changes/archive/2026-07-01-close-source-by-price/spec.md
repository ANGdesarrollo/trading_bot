# close-source-by-price Specification

## Purpose

Define the behavioral contract for deriving a trade's `close_source` label from
price levels when the broker API cannot distinguish SL from TP exits. Covers the
deriver function, the reconciler wiring, and the adapter passthrough change.

---

## Requirements

### Requirement: Price-Based SYSTEM Close Derivation

For broker-triggered closes (`api_source == "SYSTEM"`), the system MUST derive
`close_source` deterministically from the relative distance between `close_price`
and the computed SL / TP price levels. The system MUST NOT hard-code a fixed
label for SYSTEM closes.

Level computation:
- BUY: `sl_level = filled_price - sl_distance`, `tp_level = filled_price + tp_distance`
- SELL: `sl_level = filled_price + sl_distance`, `tp_level = filled_price - tp_distance`

Classification: `"SL"` when `|close_price - sl_level| <= |close_price - tp_level|`,
otherwise `"TP"`.

#### Scenario: BUY closed at TP level

- GIVEN a BUY trade with `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0040`, `api_source="SYSTEM"`
- WHEN `close_price=1.1040` (equals `tp_level`)
- THEN `derive_close_source` returns `"TP"`

#### Scenario: BUY closed at SL level

- GIVEN a BUY trade with `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0040`, `api_source="SYSTEM"`
- WHEN `close_price=1.0980` (equals `sl_level`)
- THEN `derive_close_source` returns `"SL"`

#### Scenario: SELL closed at TP level

- GIVEN a SELL trade with `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0040`, `api_source="SYSTEM"`
- WHEN `close_price=1.0960` (equals `tp_level`)
- THEN `derive_close_source` returns `"TP"`

#### Scenario: SELL closed at SL level

- GIVEN a SELL trade with `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0040`, `api_source="SYSTEM"`
- WHEN `close_price=1.1020` (equals `sl_level`)
- THEN `derive_close_source` returns `"SL"`

#### Scenario: Equidistant close resolves to SL (conservative tie-break)

- GIVEN a BUY trade with `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0020`, `api_source="SYSTEM"`
- WHEN `close_price=1.1010` (equidistant from `sl_level=1.0980` and `tp_level=1.1020`)
- THEN `derive_close_source` returns `"SL"`

---

### Requirement: API-Unambiguous Source Passthrough

When `api_source` is unambiguously classifiable (`"USER"` or `"CLOSE_OUT"`), the
system MUST return that value unchanged. Price levels MUST NOT be consulted.

#### Scenario: USER source passes through

- GIVEN any trade with `api_source="USER"`
- WHEN `derive_close_source` is called
- THEN it returns `"USER"` regardless of `close_price`, `sl_distance`, or `tp_distance`

#### Scenario: CLOSE_OUT source passes through

- GIVEN any trade with `api_source="CLOSE_OUT"`
- WHEN `derive_close_source` is called
- THEN it returns `"CLOSE_OUT"` regardless of `close_price`, `sl_distance`, or `tp_distance`

---

### Requirement: Invalid Direction Raises ValueError

The system MUST raise `ValueError` when `direction` is not `"BUY"` or `"SELL"`
(after case normalization and whitespace trimming). Silent wrong math MUST NOT
occur.

#### Scenario: Unknown direction string raises

- GIVEN `api_source="SYSTEM"` and `direction="LONG"`
- WHEN `derive_close_source` is called
- THEN a `ValueError` is raised

#### Scenario: Empty direction string raises

- GIVEN `api_source="SYSTEM"` and `direction=""`
- WHEN `derive_close_source` is called
- THEN a `ValueError` is raised

#### Scenario: Mixed-case direction is accepted

- GIVEN `api_source="SYSTEM"` and `direction="buy"` (lowercase)
- WHEN `derive_close_source` is called with valid price levels
- THEN it classifies normally without raising

---

### Requirement: Adapter Returns Raw API Source

The history adapter MUST populate `ClosedTrade.close_source` with the raw
`source` value from the Capital.com API response. The adapter MUST NOT map or
reclassify `"SYSTEM"` to any fixed label.

#### Scenario: SYSTEM close carries raw source from adapter

- GIVEN a Capital.com activity record with `source="SYSTEM"`
- WHEN the history adapter builds a `ClosedTrade`
- THEN `ClosedTrade.close_source == "SYSTEM"`

---

### Requirement: Reconciler Applies Derivation Before Persisting

The reconciler use case MUST call `derive_close_source` using the raw
`ClosedTrade.close_source` and the entry's price fields, then pass the derived
label into `JournalResult(close_source=...)`. The raw API source MUST NOT be
written directly to the journal.

#### Scenario: SYSTEM close journaled with derived label

- GIVEN a `ClosedTrade` with `close_source="SYSTEM"` and a matching `JournalEntry`
  with all price fields populated
- WHEN `ReconcileClosedTradesUseCase.execute()` runs
- THEN the persisted `JournalResult.close_source` is `"TP"` or `"SL"` (never `"SYSTEM"`)

---

## Non-Goals

- No DB backfill of rows where `close_source` was previously hard-coded to `"SL"`.
- No schema change to `JournalEntry`, `JournalResult`, or `ClosedTrade`.
- No change to `TradeHistoryPort` or `TradeJournalPort` signatures.
- No `Direction` enum introduced in this change.
