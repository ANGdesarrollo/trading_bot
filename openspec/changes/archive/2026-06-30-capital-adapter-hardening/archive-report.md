# Archive Report: capital-adapter-hardening

**Change**: capital-adapter-hardening
**Archived**: 2026-06-30
**Status**: SHIP (all artifacts verified and shipped)
**Test Verdict**: 47/47 tests passing, 0 failures
**Artifact Store**: openspec

---

## What Shipped

Four surgical configuration corrections to unblock the T-23 demo smoke test:

1. **D1 — Base URLs (Verified)**
   - Demo: corrected to `https://demo-api-capital.backend-capital.com/api/v1` (verified against Capital.com demo API)
   - Live: set to `https://api-capital.backend-capital.com/api/v1` (inferred; flagged with `# UNVERIFIED` for live-cutover validation)
   - Test URL constants updated in `test_capital_broker.py` and `test_capital_session.py` for consistency

2. **D2 — API Key Environment Variable (Verified)**
   - Changed config to read `CAPITAL_API_KEY` instead of `API_KEY` (matches Capital.com SDK conventions and `.env` file)
   - Updated missing-var label to reflect the correct env variable name
   - Updated 3 test fixtures in `test_config.py` to use `CAPITAL_API_KEY`
   - Added regression test: legacy-API_KEY-only case now correctly raises `SystemExit`

3. **D3 — Default Trade Size (Verified)**
   - Changed default `SIZE` from `0.01` to `1000` (clears Capital.com's `minDealSize=100` constraint)
   - Added test asserting default trade_size resolves to 1000

4. **D4 — Warmup Guard Relocation (Verified)**
   - Bumped default `WARMUP_BARS` from 64 to 128 (matches strategy adapter's actual requirement)
   - Deleted `_assert_warmup_covers_strategy_burnin` from `config.py` (was reading frozen research constants; incorrect contract)
   - Moved guard to `src/__main__.py` composition root, immediately after `FadeStrategy()` instantiation
   - Guard now reads public `strategy.required_candles` port property (DIP-clean, no private imports)
   - Added tests for all four spec scenarios:
     - WARMUP=64 (below 128) rejected at startup → SystemExit
     - WARMUP=128 (at minimum) accepted → no exception
     - WARMUP=256 (above minimum) accepted → no exception
     - Default WARMUP (no env var) resolves to 128 → accepted

---

## Test Delta

| Metric | Before | After |
|--------|--------|-------|
| Passing tests | 40 | 47 |
| Failed tests | 0 | 0 |
| New tests added | — | 7 (2 API_KEY scenarios, 1 SIZE default, 4 warmup/guard scenarios) |

All new tests follow STRICT TDD mode (RED → GREEN). Suite is green throughout.

---

## Verification Summary

### Critical Issues (Initial)

Two CRITICAL issues flagged in initial verify-report:

1. **CRITICAL-01** — Missing test for "legacy API_KEY only → load fails" spec scenario
   - **Fixed**: Added `test_legacy_api_key_only_raises_system_exit` (test_config.py:L108–L117)
   - **Verified**: Test passes and correctly asserts SystemExit when CAPITAL_API_KEY is empty and API_KEY is set

2. **CRITICAL-02** — Missing test for "WARMUP=256 accepted" spec scenario
   - **Fixed**: Added `test_build_use_case_accepts_warmup_above_strategy_minimum` (test_main_loop.py:L114–L121)
   - **Verified**: Test passes and confirms warmup values above 128 are not incorrectly rejected

**Re-verification result**: Both CRITICALs are CLOSED. Suite remains green at 47/47.

### Non-Blocking Issues (Remain Open)

**WARNING-01** — Pre-existing unused `field` import in `src/config.py` (L11)
- Not introduced by this change; pre-existing dead code
- Recommend cleanup in a follow-up config hygiene pass or immediately after this PR merges
- Does not block archive

**SUGGESTION-01** — Stale module docstring in `tests/unit/test_config.py` (L1–L7)
- References old task IDs; does not reflect new tests added
- Minor discoverability issue only; recommend update during code review
- Does not block archive

---

## Deferred Future Work (Out of Scope)

**Broker-Specific Size Min/Step Validation**

The proposal noted that per-instrument `minDealSize` and `stepSize` constraints belong in the broker adapter layer (DIP), not config policy. This change correctly avoids that work:

- Config provides a safe default (1000)
- Broker adapter rejects oversized trades via `OrderRejectedError` at runtime
- Fine-grained validation is deferred to a future adapter improvement

This ensures config remains a pure data structure (no broker knowledge) and keeps validation at the right abstraction layer.

---

## Production Risk: Unverified Live URL

The live base URL is set to `https://api-capital.backend-capital.com/api/v1` and flagged with an inline `# UNVERIFIED` comment in `src/config.py` (L18).

- **Reason**: Live API was not accessible during development; URL inferred from demo pattern and Capital docs
- **T-23 impact**: None — smoke test uses DEMO mode only
- **Mitigation**: Comment serves as a live-cutover checklist item
- **Action**: Before any LIVE deploy, confirm the live base URL resolves and 200-OK responses are received from Capital.com

---

## Artifact Reconciliation

### Specs Synced

No domain spec merge needed. This change is infrastructure-focused (config + startup guard):
- No new `openspec/specs/{domain}/spec.md` file created
- The local `spec.md` documents the config contract for this change only
- No destructive merge or external spec modification required

### Archive Contents

- `proposal.md` ✅ Intent, scope, approach, risks, success criteria
- `explore.md` ✅ API research findings (verified demo URLs, Capital.com SDK patterns, adapter requirements)
- `spec.md` ✅ Four corrected requirements with test scenarios
- `design.md` ✅ Technical decisions (D1–D4), data flow, file changes, interfaces
- `tasks.md` ✅ 15 tasks across 5 groups, all [x] complete
- `verify-report.md` ✅ Test evidence (47/47), spec compliance matrix, line-by-line checks, CRITICAL fixes
- `archive-report.md` ✅ This document

### Source of Truth

Main repository is unaffected. No spec file changes needed. The four config defects have been corrected directly in:
- `src/config.py` (D1–D4)
- `src/__main__.py` (D4 guard relocation)
- `tests/unit/test_config.py` (API_KEY rename, new size/warmup tests)
- `tests/unit/test_capital_broker.py` (URL constant sync)
- `tests/unit/test_capital_session.py` (URL constant sync)

---

## SDD Cycle Complete

The change has been fully planned (proposal), specified (spec + design), tasked (15 tasks), implemented (all [x]), verified (SHIP), and archived.

Unblocks T-23 demo smoke test. Ready for PR merge and live integration.

---

## Archive Metadata

| Field | Value |
|-------|-------|
| Change name | capital-adapter-hardening |
| Artifact store | openspec |
| Archive date | 2026-06-30 |
| Archive destination | openspec/changes/archive/2026-06-30-capital-adapter-hardening/ |
| Proposal observation ID | *tracked in openspec only* |
| Spec observation ID | *tracked in openspec only* |
| Design observation ID | *tracked in openspec only* |
| Tasks observation ID | *tracked in openspec only* |
| Verify report observation ID | *tracked in openspec only* |
| Status | ARCHIVED |
