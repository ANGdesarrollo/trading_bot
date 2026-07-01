# Exploration: capital-adapter-hardening

## Context

The live trading engine works but has defects discovered when probing the REAL
Capital.com demo API via curl. Ground-truth facts verified against the demo API:

- Working demo base URL: `https://demo-api-capital.backend-capital.com/api/v1`
- Auth: `POST /session` with `X-CAP-API-KEY` header + `{identifier, password}` body
  returns `CST` + `X-SECURITY-TOKEN` response headers.
- `POST /positions` is ASYNC: returns only `{"dealReference": "o_..."}`. Must then
  `GET /confirms/{dealReference}` for `dealStatus`, `dealId`, fill `level`.
- EURUSD epic is literally `EURUSD` (not IG-style `CS.D.EURUSD.MINI.IP`).
- EURUSD dealingRules: `minDealSize=100`, `minSizeIncrement=100`, leverage 100.
- Size equivalence (verified with a real demo order): size 1000 = 1000 base units
  = 1141 USD notional at 1.14137 = 0.01 standard lots (one micro-lot). size 100 =
  sub-micro (~114 USD notional, 0.10 USD/pip at size 1000).

## Defect Map

### D1 — Wrong base URLs (`src/config.py:20-21`)
`_DEMO_BASE_URL = "https://demo-api.capital.com/api/v1"` does NOT resolve. Correct
host: `demo-api-capital.backend-capital.com`. Live host `api-capital.backend-capital.com`
is an INFERENCE — not externally verified. Flag for proposal.

### D2 — Wrong API key env var (`src/config.py:58`)
Reads `os.environ.get("API_KEY", "")`. The `.env` and Capital docs use
`CAPITAL_API_KEY`. Startup fails: "Missing required environment variables: API_KEY".
Test breakage: `tests/unit/test_config.py:42,55,70` all pass `"API_KEY"` — must
change to `"CAPITAL_API_KEY"` in the same task.

### D3 — Invalid default trade size (`src/config.py:64`)
`trade_size = float(os.environ.get("SIZE", "0.01"))`. `0.01 < minDealSize=100` →
order rejected. Default must become 1000 (= 0.01 lots).

### D4 — Stale WARMUP_BARS + wrong validator (`src/config.py:23,96-110`)
`WARMUP_BARS = 64` but `fade_strategy.py:37` `_REQUIRED_CANDLES = 128`. Secondary
bug: `_assert_warmup_covers_strategy_burnin` checks `warmup_bars >= max(L_FROZEN=32,
ATR_PERIOD=14) = 32`, so WARMUP=64 passes startup but the domain adapter rejects
the buffer at runtime (raises on < 128). Must bump the default AND fix the validator
to check against the adapter's `_REQUIRED_CANDLES`, not the raw strategy constants.

### D5 — open_position async confirm: ALREADY FIXED (`src/infrastructure/capital/broker.py:57-94`)
The two-step flow is already implemented: POST → `dealReference`, then
GET `/confirms/{dealReference}` → `dealStatus`/`dealId`/`level`. `OrderRejectedError`
raised for status not in `("ACCEPTED", "OPEN")`. OrderResult built from confirm
fields. Covered in `tests/unit/test_capital_broker.py`. NO CODE CHANGE NEEDED.
Note: `dealStatus="OPEN"` acceptance (line 85) is unverified against the real API —
may be a dead branch.

## Design Decisions (deferred to proposal)

### Size validation ownership
- A. Fix default only (SIZE=1000). Low effort; REJECTED confirm surfaces bad config.
- B. Fetch `/markets/{epic}` dealingRules at startup; fail fast with clear message.
- C. Inject minDealSize as config param; adapter enforces.
DIP argument: broker dealing rules are infrastructure knowledge; config is policy.
Recommend A as the minimum safe fix for a single-instrument bot.

### Warmup validator fix
- A. Bump constant to 128 only — leaves the startup guard lying (still checks 32).
- B. Bump + fix validator to check against adapter `_REQUIRED_CANDLES`.
- C. Bump + expose class-level constant from FadeStrategy (touches domain interface).
Recommend B.

## Affected Files
- `src/config.py` — D1, D2, D3, D4
- `tests/unit/test_config.py` — API_KEY → CAPITAL_API_KEY (3 fixtures)
- `tests/unit/test_capital_broker.py:36` — old URL constant (cosmetic)
- `tests/unit/test_capital_session.py:19` — old URL constant (cosmetic)
- `src/infrastructure/capital/broker.py` — D5 already fixed; no change
- `src/domain/adapters/fade_strategy.py` — source of `_REQUIRED_CANDLES=128`

## Test Coverage Gaps
- Config tests use wrong env var name (will break when D2 is fixed).
- No test for base URL correctness.
- No test for `WARMUP_BARS >= _REQUIRED_CANDLES` validator threshold.
- No test that default SIZE meets minDealSize.

## Risks
- Live URL is inferred, not verified — flag for proposal.
- `dealStatus="OPEN"` branch semantics unverified.
- Warmup validator gap silently passes bad WARMUP values — fix the validator, not just the constant.

## Next Recommended
`sdd-propose`
