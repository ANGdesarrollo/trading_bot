# Proposal: close-source-by-price

## Why

The trade journal exists to attribute every closed position to a correct
outcome so the fade strategy can be evaluated on real profit and loss. Today
that attribution is silently wrong for a whole class of trades.

Capital.com's `/history/activity` endpoint reports broker-triggered closes with
`source = "SYSTEM"` for BOTH stop-loss and take-profit exits — the payload has
no field that distinguishes them. The shipped adapter hard-codes
`"SYSTEM" → "SL"` (`history_adapter.py:18`), so every TP winner is journaled as
an SL loss.

The business impact is direct: win rate, realized-R distribution, and any
strategy decision derived from the journal are corrupted in the pessimistic
direction. A profitable strategy can look like a losing one. Since the journal's
entire purpose is correct P/L attribution, this defect defeats the reason the
journal was built.

The fix is deterministic and needs no new data: the reconciler already holds the
entry's `filled_price`, `sl_distance`, `tp_distance`, `direction`, and the
observed `close_price`. From those we can compute the actual SL and TP price
levels and classify a SYSTEM close by which level the fill price landed nearest.

## What Changes

1. Add a pure domain function
   `derive_close_source(api_source, close_price, filled_price, sl_distance,
   tp_distance, direction)` in a new module
   `operator/src/domain/services/close_source.py`. It returns the corrected
   close source string:
   - `USER` and `CLOSE_OUT` pass through unchanged from the API source.
   - `SYSTEM` is disambiguated by nearest price level:
     - BUY: `sl_level = filled_price - sl_distance`,
       `tp_level = filled_price + tp_distance`
     - SELL: `sl_level = filled_price + sl_distance`,
       `tp_level = filled_price - tp_distance`
     - `return "SL" if abs(close_price - sl_level) <= abs(close_price - tp_level)
       else "TP"` (tie-breaks to SL, conservative).
   - Any other/unknown API source falls back to the current `USER` default.
2. Wire the deriver into `ReconcileClosedTradesUseCase.execute()`
   (`reconcile_closed_trades.py`): compute the corrected close source from
   `closed.close_source` (raw API source) plus the entry fields already in the
   loop, and pass the result into `JournalResult(close_source=...)`.
3. Drop the `"SYSTEM" → "SL"` hack in `history_adapter.py`: the adapter now
   returns the raw API `source` in `ClosedTrade.close_source` (keeping the raw
   value is useful for debugging and lets the deriver own classification).

### Classification rule (single source of truth)

```
if api_source in {"USER", "CLOSE_OUT"}:
    return api_source
if api_source == "SYSTEM":
    # compute sl_level / tp_level from direction, then nearest-level compare
    return "SL" if dist_to_sl <= dist_to_tp else "TP"
return "USER"   # unknown source fallback (unchanged behavior)
```

No magic tolerance constant. The comparison is purely relative distance to each
computed level.

## Scope

### In scope
- New pure deriver function + its unit tests.
- Reconciler calls the deriver before building `JournalResult`.
- Adapter stops hard-coding SYSTEM→SL and returns the raw API source.
- Update the one adapter test that asserts the old mapping
  (`test_capital_trade_history.py:91` currently asserts `close_source == "SL"`
  for a SYSTEM close; it must assert `"SYSTEM"` now that the adapter passes the
  raw source through).
- Minimal `direction` normalization/guard inside the deriver (see Decision 2).

### Out of scope (non-goals)
- **No DB backfill migration** for existing mislabeled rows (Decision 1).
- **No schema change** — no new columns; `JournalEntry`, `JournalResult`,
  `ClosedTrade` shapes are unchanged.
- **No port change** — `TradeHistoryPort` and `TradeJournalPort` signatures are
  untouched; the deriver reads data already present in the use-case loop
  (rules out exploration Approach B).
- **No new injected service class** — a module-level pure function is enough
  (rules out Approach C).
- **No autonomous live orders.** Empirically confirming the real
  `/history/activity` payload for a TP close is a MANUAL follow-up (Decision 5).

## Decisions

### 1. DB backfill of existing mislabeled rows — DEFERRED (no migration here)
Existing rows with `close_source = "SL"` may be mislabeled TP winners. This is a
fresh demo bot with likely few or no real closed rows yet, so a backfill is not
worth the scope and migration risk now. **Decision: no backfill in this change.**
Recorded as an explicit follow-up: if meaningful closed-trade data already
exists, run a one-off recompute that applies `derive_close_source` to historical
rows (all inputs are stored, so the correction is reproducible offline). The
deriver being pure makes that follow-up trivial to build later.

### 2. `direction` typing — add a minimal guard/normalization in the deriver
`JournalEntry.direction` is an unvalidated `str` (`journal.py:11`); there is no
`Direction` enum in the domain today. A wrong-case or unexpected value would
silently invert the SL/TP level math and produce a confidently-wrong label.
**Decision:** normalize `direction` inside the deriver (uppercase/trim) and
accept only `"BUY"`/`"SELL"`; anything else raises `ValueError` so corruption is
loud, not silent. Keep it minimal — no new enum introduced in this change.

### 3. `ClosedTrade.close_source` naming — keep + document
The field now carries the raw API source and is overridden downstream by the
deriver. **Decision:** keep the name to avoid churn across the adapter, entity,
and any readers; document in the adapter that this holds the raw API `source`
and that final classification happens in the reconciler via
`derive_close_source`. Renaming to `raw_api_source` is a possible later cleanup,
not part of this fix.

### 4. `sl_distance == 0` guard — cannot occur for real entries
`Signal.__post_init__` rejects `sl_distance <= 0` at construction
(`signal.py:22-23`), so no journaled entry can carry a zero SL distance. The
nearest-level comparison never divides by `sl_distance`, so even a degenerate
value would not raise. **Decision:** no special-case branch; note the invariant.
The `direction` guard from Decision 2 is the only input validation added.

### 5. Empirical validation — MANUAL follow-up, not automated
We have not observed a real Capital.com demo TP close; the "SYSTEM for both"
assumption comes from the shipped code comment only. **Decision:** confirming the
actual payload requires manually opening and closing a demo position and
inspecting the `source` field — this is a manual operator task and must NOT be
automated into this change (no autonomous order placement). Importantly, the
price-based logic is correct regardless of the API-field ambiguity: even if
Capital.com later exposes a distinguishing field, nearest-level classification
still yields the right answer.

## PR Footprint

Tiny and self-contained:
- 2 new files: `domain/services/close_source.py`,
  `tests/unit/test_close_source_derivation.py`.
- 2 edited files: `application/reconcile_closed_trades.py` (call the deriver),
  `infrastructure/capital/history_adapter.py` (remove the SYSTEM→SL hack, return
  raw source).
- 1 edited test: `tests/unit/test_capital_trade_history.py` (assert raw
  `"SYSTEM"` instead of `"SL"`).

No schema, no ports, no infra, no dependencies. Well under a single small PR.

## Risks

- **Empirical API risk (low, non-blocking):** if Capital.com actually does
  distinguish SL from TP via `source`, the price logic is redundant but still
  correct. Resolved by the manual demo check in Decision 5.
- **Silent direction corruption (mitigated):** a bad `direction` value would
  invert level math; Decision 2's guard converts that into a loud `ValueError`.
- **Stale historical rows (accepted, out of scope):** pre-existing rows keep
  their wrong `"SL"` labels until the deferred backfill in Decision 1 is run.
- **Floating-point edge at the exact midpoint:** if `close_price` is equidistant
  from both levels, the tie deterministically resolves to `"SL"` (conservative,
  intended).

## Open Questions for Design

Minimal — the approach is settled. The only real design detail:

1. **Direction contract:** confirm the deriver should accept exactly
   `"BUY"`/`"SELL"` (case-normalized) and raise on anything else, versus a softer
   fallback. Proposal recommends raising to keep corruption loud.

Everything else (pure function placement, nearest-level rule, no
schema/port/backfill) is resolved above and ready for spec + design.
