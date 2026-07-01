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
