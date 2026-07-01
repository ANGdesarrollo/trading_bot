# Design: Capital.com Adapter Hardening

## Technical Approach

Four surgical corrections in `src/config.py` (D1–D4) plus co-dependent test updates. Three are pure value edits. D4 is the only architectural decision: the startup warmup guard currently validates against the wrong source of truth. We relocate the guard to the composition root (`src/__main__.py`) so it reads the strategy's public `required_candles` port property instead of re-deriving from raw research constants. This makes the guard honest (checks 128, the real runtime gate) and DIP-clean (config stops knowing strategy internals). No new abstractions. The frozen `research.lib.*` is untouched.

## Architecture Decisions

### Decision: D4 warmup guard — where it lives and what it reads

| Option | What | Tradeoff | Verdict |
|--------|------|----------|---------|
| B1 | Validator in config imports `_REQUIRED_CANDLES` from domain adapter | Config → domain dependency; imports an underscore-private constant across layers | Reject |
| B2 | Validator reads a public constant/property on the strategy | Cleaner contract; but keeping it in config still forces config to import a strategy class | Partial |
| B3 | Keep private import, drop the underscore | Cosmetic; config still owns strategy knowledge | Reject |
| **B2+CR** | **Move guard to `__main__.py`; assert `warmup_bars >= strategy.required_candles` on the already-built instance** | **DIP-clean: policy check where the strategy instance exists; config becomes pure data** | **Chosen** |

**Choice**: Delete `_assert_warmup_covers_strategy_burnin` from `config.py`. Add the check in `__main__.py` after `FadeStrategy()` is instantiated, consulting the public `required_candles` port property.

**Rationale**: `StrategyPort.required_candles` is already declared abstract (strategy_port.py:15-18) and implemented by `FadeStrategy` returning `_REQUIRED_CANDLES=128` (fade_strategy.py:41-43). The composition root is the ONLY layer that legitimately touches both config values and concrete strategy instances (`__main__.py:60`). Validating there depends on an abstraction (the port property), not on a private constant or a research symbol. Config reverts to a pure data structure — it no longer imports research, mutates `sys.path`, or asserts strategy burn-in. The old validator's `max(L_FROZEN=32, ATR_PERIOD=14)=32` threshold was structurally wrong: those constants describe the frozen research indicator windows, NOT the adapter's 128-candle buffer gate. Reading `required_candles` eliminates the drift by construction.

### Decision: D1 live URL — inferred value retained but flagged

**Choice**: Set live URL to `https://api-capital.backend-capital.com/api/v1` with an inline `# UNVERIFIED` comment. **Rationale**: Demo (verified) is what T-23 exercises. Blocking on live verification would stall the smoke test; the comment carries the risk to the live cutover.

### Decision: D3 size — fix default only (Option A)

**Choice**: Default `SIZE` `0.01` → `1000`. **Rationale**: Single-instrument bot. Broker-specific min/step validation is infrastructure knowledge that belongs in the adapter, not config policy — deferred as future work (a REJECTED confirm already surfaces bad sizes via `OrderRejectedError`).

## Data Flow

Startup guard, before (broken) vs after (correct):

    BEFORE:  load_config() ──imports──▶ research.lib (L_FROZEN=32, ATR_PERIOD=14)
                  │  asserts warmup >= 32   ← WRONG gate; 64 passes, adapter rejects <128
                  ▼
             Config

    AFTER:   load_config() ─────────────▶ Config (pure data)
                  │
    __main__ ─────┼──▶ FadeStrategy()  ──.required_candles──▶ 128
                  │
                  └──▶ assert warmup_bars >= strategy.required_candles  ← TRUE gate

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/config.py` | Modify | D1 URLs (L20-21); D2 read `CAPITAL_API_KEY` (L58) + missing-list label (L70); D3 default `1000` (L64); D4 bump `WARMUP_BARS=128` (L23), DELETE `_assert_warmup_covers_strategy_burnin` (L96-110) and its call (L78); drop the now-unused module docstring line about startup validation |
| `src/__main__.py` | Modify | After `strategy = FadeStrategy()` (L60), assert `config.warmup_bars >= strategy.required_candles`, raise `SystemExit` with a clear message if not |
| `tests/unit/test_config.py` | Modify | 3 fixtures `API_KEY` → `CAPITAL_API_KEY` (L42, L55, L70) |
| `tests/unit/test_capital_broker.py` | Modify | Old URL constant (L36) → new host (cosmetic) |
| `tests/unit/test_capital_session.py` | Modify | Old URL constant (L19) → new host (cosmetic) |
| `src/domain/adapters/fade_strategy.py` | None | Source of truth for `required_candles`; not touched |
| `research.lib.*` | None | Frozen; never touched |

## Interfaces / Contracts

No new interface. Reuses the existing port contract:

```python
# domain/ports/strategy_port.py (unchanged)
@property
@abstractmethod
def required_candles(self) -> int: ...

# __main__.py (new guard, replaces config-side validator)
strategy = FadeStrategy()
if config.warmup_bars < strategy.required_candles:
    raise SystemExit(
        f"warmup_bars={config.warmup_bars} < strategy requirement "
        f"{strategy.required_candles}"
    )
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | Config loads with `CAPITAL_API_KEY`; default `SIZE==1000`; `WARMUP_BARS==128`; demo URL resolves | Update 3 existing fixtures; env-patch loader already in `test_config.py` |
| Unit | Guard rejects `warmup < required_candles`, passes when `>=` | New test in `__main__` scope: assert `SystemExit` on `warmup_bars=64` against `required_candles=128` |
| Cosmetic | URL constants in broker/session tests | String update only |

## Migration / Rollout

No migration. Pure config + guard-relocation. Rollback = revert the single commit.

## Open Questions

- [ ] Live base URL host is INFERRED — verify before any live cutover (out of scope for T-23).
- [ ] Future (DIP): broker-specific size min/step validation belongs in the broker adapter, not config. Deferred.
