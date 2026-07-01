# Tasks: close-source-by-price

**Delivery**: single PR — 2 new files, 3 edits. TDD: RED → GREEN → REFACTOR each task.
**Test runner**: `cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator && .venv/bin/python3 -m pytest`

---

## Task 1 — Pure deriver: RED → GREEN → REFACTOR [SEQUENTIAL, first] [x]

**Satisfies**: Requirement: Price-Based SYSTEM Close Derivation, Requirement: API-Unambiguous Source Passthrough, Requirement: Invalid Direction Raises ValueError

### RED

Create `tests/unit/test_close_source_derivation.py` with all 10 cases below. Run the suite — **all 10 must FAIL** (ImportError or AttributeError) before writing the implementation.

Cases (use `filled_price=1.1000`, `sl_distance=0.0020`, `tp_distance=0.0040` unless noted):

| # | api_source | direction | close_price | expected |
|---|-----------|-----------|-------------|----------|
| 1 | SYSTEM | BUY | 1.1040 (== tp_level) | "TP" |
| 2 | SYSTEM | BUY | 1.0980 (== sl_level) | "SL" |
| 3 | SYSTEM | SELL | 1.0960 (== tp_level) | "TP" |
| 4 | SYSTEM | SELL | 1.1020 (== sl_level) | "SL" |
| 5 | SYSTEM | BUY | 1.1010 (equidistant; sl_dist=tp_dist=0.0020) | "SL" (tie-break) |
| 6 | USER | BUY | any | "USER" (passthrough) |
| 7 | CLOSE_OUT | BUY | any | "CLOSE_OUT" (passthrough) |
| 8 | SYSTEM | LONG | any | raises ValueError |
| 9 | SYSTEM | "" | any | raises ValueError |
| 10 | SYSTEM | "buy" | 1.1040 | "TP" (mixed-case accepted) |

### GREEN

Create `src/domain/services/close_source.py` with the `derive_close_source` function (exact signature below). No `__init__.py` needed. Run suite — all 10 must PASS.

```python
def derive_close_source(
    api_source: str,
    close_price: float,
    filled_price: float,
    sl_distance: float,
    tp_distance: float,
    direction: str,
) -> str:
```

Logic:
- `api_source in ("USER", "CLOSE_OUT")` → return `api_source`
- `api_source != "SYSTEM"` → return `"USER"` (unknown source fallback)
- `d = direction.strip().upper()`
- BUY: `sl_level = filled_price - sl_distance`, `tp_level = filled_price + tp_distance`
- SELL: `sl_level = filled_price + sl_distance`, `tp_level = filled_price - tp_distance`
- else: `raise ValueError(f"invalid direction: {direction!r}")`
- `return "SL" if abs(close_price - sl_level) <= abs(close_price - tp_level) else "TP"`

### REFACTOR

Inspect for readability only. The function is already minimal — no restructuring expected.

**Files touched**: `tests/unit/test_close_source_derivation.py` (NEW), `src/domain/services/close_source.py` (NEW)

---

## Task 2 — Adapter passthrough: RED → GREEN [PARALLEL-SAFE after Task 1 GREEN] [x]

**Satisfies**: Requirement: Adapter Returns Raw API Source

### RED

Open `tests/unit/test_capital_trade_history.py`. Find the assertion `close_source == "SL"` (approximately line 91 in the SYSTEM-source test). Change it to `close_source == "SYSTEM"`. Run suite — this test must FAIL (actual `"SL"` ≠ expected `"SYSTEM"`).

### GREEN

Open `src/infrastructure/capital/history_adapter.py`. In `_ACTIVITY_SOURCE_TO_CLOSE_SOURCE` (or the equivalent mapping), remove the `"SYSTEM": "SL"` entry so that `"SYSTEM"` passes through raw. Keep `"USER"` and `"CLOSE_OUT"` identity entries and the unknown→`"USER"` fallback. Run suite — the flipped test must PASS and no regressions.

**Files touched**: `tests/unit/test_capital_trade_history.py` (MODIFY), `src/infrastructure/capital/history_adapter.py` (MODIFY)

---

## Task 3 — Reconciler wiring: RED → GREEN [SEQUENTIAL, after Tasks 1 & 2 GREEN] ⭐ KEYSTONE [x]

**Satisfies**: Requirement: Reconciler Applies Derivation Before Persisting

### RED

In the reconciler's use-case test file (or create a focused test if none exists for this path), add a test that:
1. Builds a `ClosedTrade` fake with `close_source="SYSTEM"`, `close_price` at the TP level for a BUY trade.
2. Builds a matching `JournalEntry` fake with `filled_price`, `sl_distance`, `tp_distance`, `direction="BUY"`.
3. Runs `ReconcileClosedTradesUseCase.execute()` using in-memory fakes for all ports.
4. Asserts that the persisted `JournalResult.close_source == "TP"`.

Run suite — this test must FAIL (reconciler currently passes raw `"SYSTEM"` through without derivation).

### GREEN

Edit `src/application/reconcile_closed_trades.py`:
1. Add import: `from src.domain.services.close_source import derive_close_source`
2. Inside the loop, after `closed` is obtained:
   ```python
   derived = derive_close_source(
       closed.close_source, closed.close_price,
       entry.filled_price, entry.sl_distance, entry.tp_distance, entry.direction,
   )
   ```
3. Pass `close_source=derived` into `JournalResult(...)` instead of the raw value.

Run suite — keystone test must PASS.

**Keystone assertion**: reconciler stores `"TP"` (not `"SYSTEM"`) for a SYSTEM-closed BUY trade where `close_price == tp_level`.

**Files touched**: `src/application/reconcile_closed_trades.py` (MODIFY)

---

## Task 4 — Full suite verification [SEQUENTIAL, last] [x]

**Satisfies**: all requirements (regression guard)

Run the complete test suite:

```bash
cd /home/alexis/Documents/Projects/TRADING_PROJECT_DEFINITIVE/operator && .venv/bin/python3 -m pytest -q
```

Expected outcome:
- All pre-existing tests pass (baseline ~91–96 depending on fixture state).
- All 10 new deriver unit tests pass (Task 1).
- The flipped adapter test passes as `"SYSTEM"` (Task 2).
- The keystone reconciler integration test passes (Task 3).
- **Zero failures, zero errors.**

Report final pass/fail counts. If any test fails, fix it before marking this task done.

---

## Execution Order

```
Task 1 (RED→GREEN→REFACTOR)
    └── Task 2 (can start once Task 1 GREEN; parallel-safe, different files)
    └── Task 3 (requires Task 1 GREEN + Task 2 GREEN)
            └── Task 4 (full suite, last)
```

Tasks 1 and 2 share no files and can be done concurrently by a single implementer back-to-back with minimal context switch. Task 3 depends on the deriver (Task 1) and the adapter passthrough (Task 2) both being green before integration wiring is tested.

---

## Review Workload Forecast

| Dimension | Value |
|-----------|-------|
| New files | 2 (`close_source.py`, `test_close_source_derivation.py`) |
| Modified files | 3 (`reconcile_closed_trades.py`, `history_adapter.py`, `test_capital_trade_history.py`) |
| Estimated changed lines | ~80–100 (well under 400-line budget) |
| Chained PRs recommended | No |
| 400-line budget risk | Low |
| Decision needed before apply | No |
| Schema changes | None |
| Port changes | None |
| Migration required | No |
