# Design: Provider-Aware Data Model

## Technical Approach

Add `provider` (plain lowercase `str`) as a first-class identity attribute of stored candles and trades. It is stamped at **construction time**: `Config.provider` (env `PROVIDER`, default `"capital"`) flows through the composition roots into the Capital producers, which inject it into every `CandleRow`; `RunTradingCycleUseCase` injects it into every `JournalEntry`. WS payloads never carry provider. Backward compatibility is preserved end-to-end via `provider="capital"` code defaults and SQL `DEFAULT 'capital'`, so existing rows, callers, and tests stay green until each site is updated. Implements modified capabilities `candle-store`, `trading-cycle`, `capital-session`.

## Architecture Decisions

| # | Decision | Choice | Rejected | Rationale |
|---|----------|--------|----------|-----------|
| 1 | Representation | plain lowercase `str` | domain enum | Mirrors existing `epic`/`resolution`/`symbol` convention; no cross-layer type import; serializes cleanly for PR 2 API; new providers via config alone. Enum adds a domain type + migration coupling for zero current invariant. |
| 2 | Read path scope | `provider` param on `recent_candles`/`last_candle_start`/`fetch_history` NOW | write-only now, read later | PR 2 must READ by provider; adding it now avoids a second breaking port change and keeps read/write symmetric. |
| 3 | Param position | `provider` LEADS the arg list (first positional after `self`) | trailing param | Provider is the outermost identity dimension (it prefixes the unique key); leading position reads as `(provider, symbol/epic, resolution, …)` matching the new key order. Default keeps unpatched callers valid. |
| 4 | Stamp site | inject into producers/use-case constructors | parse from WS payload | Provider is knowable at construction; WS `ohlc.event` has no provider field. Construction is the only reliable source. |
| 5 | Migration 003 shape | additive column first, then swap constraint + index | table recreate / backfill script | Column add with `DEFAULT 'capital'` + constraint swap are metadata-only (no table rewrite); `DEFAULT` auto-corrects existing rows without a manual backfill. |
| 6 | Reconciler scope | untouched | wire provider into reconciler | `reconciler.py` never constructs `CandleRow`/`JournalEntry`; it reads/updates existing rows by `deal_id`. Provider flows in only via `trading_cycle` at write time. |

## Data Flow

```
env PROVIDER ──► Config.provider ──┬─► __main__.build_use_cases ─► RunTradingCycleUseCase(provider)
                                   │                                   └─► JournalEntry.provider ─► PostgresTradeJournal ─► trade_entries
                                   └─► ingestion.__main__ ─► CapitalWsIngester(provider)
                                                             ├─► PairBuffer(provider) ─► CandleRow.provider ┐
                                                             └─► CapitalCandleHistory(provider) ─► _to_rows ─┤
                                                                                                            ▼
                                                                                      CandleStorePort.upsert_candle ─► candles
```

## Migration 003 (candles) — DDL order

```sql
ALTER TABLE candles ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'capital';
ALTER TABLE candles DROP CONSTRAINT IF EXISTS candles_epic_resolution_candle_start_key;
DROP INDEX IF EXISTS idx_candles_recent;
ALTER TABLE candles ADD CONSTRAINT candles_provider_epic_resolution_candle_start_key
    UNIQUE (provider, epic, resolution, candle_start);
CREATE INDEX IF NOT EXISTS idx_candles_recent
    ON candles (provider, epic, resolution, candle_start DESC);
```

`candles_epic_resolution_candle_start_key` is Postgres' auto-generated name for the table-level `UNIQUE(epic,resolution,candle_start)` in `002`. Adding a column **with a constant `DEFAULT`** is metadata-only in PG 11+ (no rewrite). The new UNIQUE builds a fresh index (fast on current volume); `IF EXISTS`/`IF NOT EXISTS` keep it idempotent under the sorted-`.sql` runner.

## Migration 004 (trade_entries)

```sql
ALTER TABLE trade_entries ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'capital';
```

Additive only; no constraint change (`deal_id` remains the identity).

## Port signature evolution

```python
# candle_store_port.py  (provider LEADS)
def recent_candles(self, provider: str, symbol: str, resolution: str, count: int) -> Sequence[Candle]
def last_candle_start(self, provider: str, symbol: str, resolution: str) -> datetime | None
def upsert_candle(self, row: CandleRow) -> None            # unchanged sig; row now carries provider

# candle_history_port.py
def fetch_history(self, provider: str, epic: str, resolution: str,
                  count: int, since: datetime | None) -> Sequence[CandleRow]
```

Defaults `provider: str = "capital"` on each new param keep existing callers/tests green until updated. `PostgresCandleStore` SQL: `provider` becomes the first `INSERT`/`ON CONFLICT` column and the leading `WHERE provider=%s AND epic=%s AND resolution=%s` predicate on both SELECTs.

## Entity changes

`CandleRow`: add `provider: str` as the FIRST field (frozen `slots=True` dataclass). Construction sites: `PairBuffer.on_event` and `candle_history._to_rows` (module fn) — both must receive and pass `provider`. `JournalEntry`: add `provider: str`; stamped in `RunTradingCycleUseCase._build_entry`. `PostgresTradeJournal` `_INSERT_ENTRY`/`_SELECT_OPEN`/`_row_to_entry` add the `provider` column/field.

## Producer wiring (injection points)

| Site | Injection |
|------|-----------|
| `config.py` | `Config.provider: str`; `load_config` reads `env.get("PROVIDER", "capital").lower()` |
| `ingestion.py __main__` | pass `provider=_config.provider` to `CapitalWsIngester` and `CapitalCandleHistory` |
| `ws_ingester.py` | `__init__(provider)`; store it; construct `PairBuffer(provider=…)`; pass into `fetch_history` calls |
| `_pair_buffer.py` | `PairBuffer.__init__(provider)`; stamp `CandleRow(provider=self._provider, …)` |
| `candle_history.py` | `CapitalCandleHistory.__init__(provider)`; thread through `_cold_backfill`/`_gap_fill` into `_to_rows(provider, …)` |
| `__main__.build_use_cases` | pass `provider=config.provider` to `RunTradingCycleUseCase` |
| `trading_cycle.py` | `__init__(provider)`; `recent_candles(self._provider, …)`; stamp `JournalEntry(provider=self._provider, …)` |

## Implementation order / TDD (per layer, small red/green)

1. Migration 003/004 (integration test: column exists, new unique key rejects dup `(provider,epic,res,start)`, old-key dup now allowed across providers).
2. `CandleRow`/`JournalEntry` field (unit: construct with provider; default holds).
3. Ports + Postgres adapters (integration: upsert+select round-trips provider; filter isolates a provider).
4. Producers (`PairBuffer`, `candle_history`, `ws_ingester`) stamp injected provider (unit with fakes).
5. `Config` + composition roots wiring (unit: `PROVIDER` env parsed; producers built with it).

## Delivery slices (>400 lines → chained PRs)

- **Slice 1**: migrations 003/004 + `CandleRow`/`JournalEntry` provider field + `Config.provider`/`load_config`. Self-contained; defaults keep every caller green.
- **Slice 2**: ports (read+write `provider`) + Postgres adapters (`candle_store`, `journal_adapter`) + test fakes.
- **Slice 3**: Capital producers (`ws_ingester`, `_pair_buffer`, `candle_history`) + composition roots (`__main__`, `ingestion`) wiring + remaining tests.

Each slice has a clear start/finish, is independently green (defaults bridge un-migrated call sites), and rolls back via git.

## Risks

| Risk | Mitigation |
|------|-----------|
| Schema-lock moment on live `candles` (constraint/index swap) | Metadata-only column add; brief `ACCESS EXCLUSIVE` only for constraint swap on a low-volume table; idempotent `IF EXISTS`. |
| Silent `"capital"` default masks a missing provider when IC Markets lands | Default is correct for all current data; second producer process MUST set `PROVIDER` explicitly. Flag as an operational precondition for IC Markets onboarding. |
| ~25-site fan-out; a missed write site persists an unstamped/defaulted row | Two CandleRow construction sites (`_pair_buffer`, `candle_history._to_rows`) + one JournalEntry site are the ONLY stamps — enumerate and cover each with a strict-TDD test asserting the stamped provider. |

## Open Questions

- [ ] Confirm PG server version ≥ 11 so the `ADD COLUMN … DEFAULT` no-rewrite guarantee holds (assumed; verify at migration-run time).
