# Re-vendor Procedure

Run when `backend/research/lib/` constants or logic change and you want to absorb the update.

## Steps

1. Capture parent SHA: `git -C /path/to/parent rev-parse HEAD`
2. Copy files byte-identical:
   - `runs.py` ← `backend/research/lib/runs.py`
   - `trajectory.py` ← `backend/research/lib/trajectory.py`
   - `fade.py` ← `backend/research/lib/fade_strategy.py`
3. Prepend provenance header to each file (update SHA and date).
4. Re-apply the two relative import edits in `fade.py`:
   - `from research.lib.runs import ...` → `from .runs import ...`
   - `from research.lib.trajectory import ...` → `from .trajectory import ...`
5. Verify: `EURUSD_FIXTURE_PATH=<csv> python3 -m pytest tests/integration/test_fade_strategy_anti_drift.py`
   All assertions must pass — confirms the vendored copy is behaviorally identical.

## portfolio.py

Source: `backend/scripts/rebalance_portfolio.py`

Run when the equal-weight basket logic or BASKET tuple changes in the research repo.

### Steps

1. Capture parent SHA: `git -C /path/to/parent rev-parse HEAD`
2. Copy the domain functions only (strip `main()` and `argparse` blocks):
   - `BASKET`, `target_allocations`, `rebalance_orders`, `parse_positions` → `portfolio.py`
3. Update the provenance header SHA and date.
4. Verify: `uv run pytest tests/unit/test_portfolio_domain.py`
   All assertions must pass.
