# Proposal: Capital.com Adapter Hardening

## Intent

The live Capital.com trading engine is built and archived, but 4 config defects in `src/config.py` block the demo smoke test (T-23). All 4 were verified against the REAL demo API via curl. This is a small, surgical config-correctness pass to unblock the smoke test. (Explore-listed D5 async `/confirms` is ALREADY fixed — not in scope.)

## Scope

### In Scope
- **D1 — Base URLs**: set demo to `https://demo-api-capital.backend-capital.com/api/v1` (VERIFIED). Set live to `https://api-capital.backend-capital.com/api/v1` (INFERRED — see Risks).
- **D2 — API key env var**: read `CAPITAL_API_KEY` instead of `API_KEY` (matches `.env` + Capital docs). Co-delivered: fix the 3 `API_KEY` fixtures in `tests/unit/test_config.py`.
- **D3 — Default trade size**: change default `SIZE` from `0.01` to `1000` (Option A — fix default only). `1000` units = 0.01 std lots = ~1141 USD notional, clears `minDealSize=100`.
- **D4 — Warmup**: (a) bump default `WARMUP_BARS` from 64 to 128; (b) fix `_assert_warmup_covers_strategy_burnin` to validate against the adapter's real requirement (`_REQUIRED_CANDLES=128`) instead of `max(L_FROZEN=32, ATR_PERIOD=14)=32`.

### Out of Scope
- Dynamic `/markets/{epic}` dealingRules fetching and multi-instrument size validation.
- `dealStatus` OPEN-vs-ACCEPTED branch semantics.
- The actual T-23 smoke-test run (manual step after this ships).
- **Future work (DIP)**: broker-specific min/step size validation belongs in the adapter — infrastructure knowledge, not config policy. Deferred; a REJECTED confirm already surfaces bad sizes via `OrderRejectedError`.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- None (config-value + validator correction; no spec-level behavior change).

## Approach

Edit the 4 constants/reads in `src/config.py`. For D4, also correct the startup validator so it stops passing WARMUP values the domain adapter rejects at runtime. Update the co-dependent config tests. Single-instrument bot → the minimum safe fix (Option A for size, Option B for warmup) is correct.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/config.py` | Modified | D1, D2, D3, D4 |
| `tests/unit/test_config.py` | Modified | `API_KEY` → `CAPITAL_API_KEY` (3 fixtures) |
| `tests/unit/test_capital_broker.py` | Modified | old URL constant (cosmetic) |
| `tests/unit/test_capital_session.py` | Modified | old URL constant (cosmetic) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Live base URL is INFERRED, not verified | Med | Do NOT block on it — demo is what T-23 tests. Flag for live-cutover verification. |
| Validator-only bump leaves guard lying | Low | D4 fixes validator AND constant together. |
| Default size still bad for other instruments | Low | Single-instrument bot; DIP adapter validation deferred as future work. |

## Rollback Plan

Revert the single commit touching `src/config.py` and the co-delivered test files. No data migrations, no schema, no runtime state — pure config revert.

## Dependencies

- Verified demo API facts from exploration (base URL, `minDealSize=100`, size equivalence, `_REQUIRED_CANDLES=128`).

## Success Criteria

- [ ] Demo base URL resolves; startup no longer fails on `Missing required environment variables: API_KEY`.
- [ ] Default `SIZE` (1000) clears `minDealSize=100`.
- [ ] `WARMUP_BARS` default is 128 AND the validator rejects any value below `_REQUIRED_CANDLES`.
- [ ] `tests/unit/test_config.py` passes with `CAPITAL_API_KEY`.
- [ ] Diff well under 400 lines.
