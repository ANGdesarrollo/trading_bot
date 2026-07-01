# Design: close-source-by-price

## Technical Approach

Move `close_source` classification out of the infrastructure adapter (where it is
a hard-coded lie) into a pure domain policy called by the application use case.
The adapter becomes a dumb passthrough of the raw API `source`; the reconciler
computes the true label from price levels already in scope. This restores the
hexagonal edge: infra reports facts, domain decides meaning, application wires
them. Matches spec requirements 1-5.

## Architecture Decisions

### Decision: Deriver accepts `direction: str`, not the `Direction` enum

**Choice**: `derive_close_source(...)` takes `direction: str` and normalizes
(`.strip().upper()`) internally.
**Alternatives considered**: Accept the `Direction` enum and convert at the call
site.
**Rationale**: `JournalEntry.direction` is a plain `str` (`journal.py:11`); the
reconciler passes `entry.direction` (a str). Taking a str avoids an artificial
str→enum conversion in the use case and keeps the deriver's validation the single
guard. The `Direction` enum (`direction.py`) is only used by `Signal` and is NOT
imported here — the proposal explicitly forbids introducing enum coupling
(Decision 2, Non-Goals).

### Decision: Pure module-level function under new `domain/services/`

**Choice**: New file `src/domain/services/close_source.py`, one free function, no
class, no I/O, no `__init__.py`.
**Alternatives considered**: Injected service class; helper inside the use case.
**Rationale**: The logic is stateless policy — a pure function is the minimal
correct shape. The project uses implicit namespace packages (no `__init__.py`
under `domain/entities/`), so `domain/services/` needs none. `services/` names it
as domain policy distinct from `entities/` data shapes.

### Decision: Invalid direction raises `ValueError`

**Choice**: Anything other than `BUY`/`SELL` (post-normalize) raises.
**Rationale**: A bad direction silently inverts SL/TP level math. Raising makes
corruption loud (spec Requirement: Invalid Direction). `sl_distance>0` is already
guaranteed at `Signal.__post_init__`, so no extra guard needed.

## Data Flow

    Capital API ──(raw "SYSTEM")──▶ history_adapter ──ClosedTrade.close_source="SYSTEM"──▶
       reconcile use case ──derive_close_source(raw, close_price, filled_price,
                             sl_distance, tp_distance, direction)──▶ "SL"|"TP"|"USER"|"CLOSE_OUT"
                          └──────────────▶ JournalResult.close_source ──▶ journal

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/domain/services/close_source.py` | Create | Pure `derive_close_source` |
| `src/application/reconcile_closed_trades.py` | Modify | Call deriver before `JournalResult` |
| `src/infrastructure/capital/history_adapter.py` | Modify | Drop SYSTEM→SL; pass raw source |
| `tests/unit/test_close_source_derivation.py` | Create | Deriver unit tests |
| `tests/unit/test_capital_trade_history.py` | Modify | Assert `"SYSTEM"` not `"SL"` |

## Interfaces / Contracts

```python
def derive_close_source(
    api_source: str, close_price: float, filled_price: float,
    sl_distance: float, tp_distance: float, direction: str,
) -> str:
    if api_source in ("USER", "CLOSE_OUT"):
        return api_source
    if api_source != "SYSTEM":
        return "USER"                       # unknown source fallback (unchanged)
    d = direction.strip().upper()
    if d == "BUY":
        sl_level, tp_level = filled_price - sl_distance, filled_price + tp_distance
    elif d == "SELL":
        sl_level, tp_level = filled_price + sl_distance, filled_price - tp_distance
    else:
        raise ValueError(f"invalid direction: {direction!r}")
    return "SL" if abs(close_price - sl_level) <= abs(close_price - tp_level) else "TP"
```

**Adapter edit** — remove `"SYSTEM": "SL"`; `_map_close_source` keeps
`USER`/`CLOSE_OUT`/`SYSTEM` identity and unknown→`USER`. Simplest form:
`ClosedTrade(..., close_source=match.get("source", "") or "USER", ...)` or retain
a map that no longer substitutes SL. Keep the raw-source doc comment.

**Reconciler edit** — inside the loop, after `closed` is fetched:
`derived = derive_close_source(closed.close_source, closed.close_price,
entry.filled_price, entry.sl_distance, entry.tp_distance, entry.direction)`, then
`JournalResult(..., close_source=derived, ...)`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Deriver: BUY→TP, BUY→SL, SELL→TP, SELL→SL, USER passthrough, CLOSE_OUT passthrough, tie→SL, invalid direction ValueError, empty direction ValueError, mixed-case accepted | Table/param tests, spec fixtures (1.1000 / 0.0020 / 0.0040) |
| Unit | Adapter passthrough | Flip `test_closed_trade_maps_system_source_to_sl` assertion to `"SYSTEM"` |

## Migration / Rollout

No migration. No schema, port, or backfill (proposal Decision 1). Existing rows
keep stale labels until a deferred offline recompute.

## Open Questions

- None. Direction contract (raise on invalid) is settled per spec.
