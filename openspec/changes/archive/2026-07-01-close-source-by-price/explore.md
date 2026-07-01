# Exploration: close-source-by-price

## Current State

`_map_close_source` in `history_adapter.py` converts the Capital.com
`/history/activity` `source` field to the `close_source` stored in `ClosedTrade`.
The mapping table hard-codes `"SYSTEM" → "SL"`. Capital.com uses `"SYSTEM"` for
BOTH SL and TP broker-triggered closes — there is no field in the activity
response that distinguishes them. A TP winner is therefore stored as `"SL"`,
corrupting profit/loss analysis.

The fix reads the close price from `match["level"]` (already extracted to
`ClosedTrade.close_price`) and computes SL/TP price levels from
`JournalEntry.filled_price ± sl_distance / tp_distance` at reconcile time to
disambiguate SYSTEM closes deterministically.

## Data-Flow Analysis (the crux)

ALL data needed for price-based disambiguation is already available in the
reconciler's `execute()` loop:

- `entry.filled_price`, `entry.sl_distance`, `entry.tp_distance`,
  `entry.direction` — from `JournalEntry` (returned by `open_entries()` via
  `_SELECT_OPEN` SQL which fetches all these columns)
- `closed.close_price` — from `ClosedTrade` (extracted from `match["level"]` in
  the API response)

No schema changes, no port widening, no new SQL columns are required. Zero
data-flow gap.

## Approaches

| Approach | Description | Pros | Cons | Effort |
|----------|-------------|------|------|--------|
| A — Pure domain function in use case | `derive_close_source(api_source, close_price, entry)` called inside `ReconcileClosedTradesUseCase.execute()` | Pure function, trivially unit-testable; adapter stays simple; adapter still passes raw API source (useful for debugging) | Mild SRP concern in use case | Low |
| B — Widen history adapter port | Pass filled_price/sl/tp/direction into `closed_trade()` | Adapter fully encapsulates Capital API logic | Adapter needs entry data it has no business knowing; port signature widens | Medium |
| C — New domain service class | Extract `CloseSourceDeriver` injected into use case | Maximally SRP | Overkill for one pure function | Low-Medium |

**Recommendation: Approach A** — pure domain function
`derive_close_source(api_source, close_price, filled_price, sl_distance,
tp_distance, direction)` in `domain/services/close_source.py`, called in the use
case to replace `closed.close_source` before building `JournalResult`. The
adapter returns raw API source unchanged in `ClosedTrade.close_source`.

## Tolerance Strategy

Nearest-level classification (recommended):

```
sl_level = filled_price - sl_distance  (BUY)  / filled_price + sl_distance  (SELL)
tp_level = filled_price + tp_distance  (BUY)  / filled_price - tp_distance  (SELL)
dist_to_sl = abs(close_price - sl_level)
dist_to_tp = abs(close_price - tp_level)
return "SL" if dist_to_sl <= dist_to_tp else "TP"
```

No magic tolerance constant needed. Tie-breaks to SL (conservative).
USER and CLOSE_OUT pass through unchanged from API source.

## Empirical Verification Gap (CRITICAL)

We have NOT observed a real Capital.com demo close to confirm what
`/history/activity` returns for TP vs SL. Current assumption (SYSTEM for both) is
based on the comment in the shipped code only. Before production, manually
open/close a demo position via TP and observe the actual `source` field. This is
a MANUAL follow-up — do NOT place real orders autonomously.

## Affected Files

- `operator/src/infrastructure/capital/history_adapter.py` — adapter keeps
  returning raw API source; `test_closed_trade_maps_system_source_to_sl` must be
  updated (will now assert `"SYSTEM"` not `"SL"`)
- `operator/src/application/reconcile_closed_trades.py` — call
  `derive_close_source()` before building `JournalResult`
- `operator/src/domain/entities/journal.py` — no changes
- `operator/src/domain/ports/trade_history_port.py` — no changes
- `operator/src/domain/ports/trade_journal_port.py` — no changes
- `operator/src/infrastructure/postgres/journal_adapter.py` — no changes
- NEW: `operator/src/domain/services/close_source.py` — pure
  `derive_close_source()` function
- NEW: `operator/tests/unit/test_close_source_derivation.py` — unit test cases

## Open Questions for Propose

1. Should `ClosedTrade.close_source` be renamed `raw_api_source` for clarity?
2. What to do with existing DB rows that have `close_source = "SL"` due to the
   bug? Backfill migration needed?
3. Confirm direction values stored: always `"BUY"`/`"SELL"` exactly? (no enum
   currently)
4. Guard for `sl_distance == 0`?

## Risks

- Empirical API risk: if Capital.com DOES distinguish SL/TP via source and we
  don't know it, price logic is redundant but still correct.
- Existing DB rows with wrong `close_source = "SL"` (mislabeled TP winners) need
  backfill.
- `direction` is an unvalidated string — a typo would silently produce wrong
  level math.
- If `sl_distance == tp_distance` AND close price exactly at midpoint, tie-breaks
  to SL (correct conservative behavior).

## Ready for Proposal

Yes — all data is already available, the fix is a pure function in the domain
layer, no port/schema changes required.
