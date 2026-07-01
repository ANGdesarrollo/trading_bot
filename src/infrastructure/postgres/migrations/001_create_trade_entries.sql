CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade_entries (
    id                 BIGSERIAL PRIMARY KEY,
    deal_id            TEXT NOT NULL UNIQUE,
    symbol             TEXT NOT NULL,
    direction          TEXT NOT NULL,
    opened_at          TIMESTAMPTZ NOT NULL,
    decision_candle_ts TIMESTAMPTZ NOT NULL,
    filled_price       DOUBLE PRECISION NOT NULL,
    sl_distance        DOUBLE PRECISION NOT NULL,
    tp_distance        DOUBLE PRECISION NOT NULL,
    atr_at_entry       DOUBLE PRECISION,
    position_size      DOUBLE PRECISION NOT NULL,
    bid_at_decision    DOUBLE PRECISION,
    ask_at_decision    DOUBLE PRECISION,
    closed_at          TIMESTAMPTZ,
    close_price        DOUBLE PRECISION,
    close_source       TEXT,
    realized_pnl       DOUBLE PRECISION,
    fees               DOUBLE PRECISION,
    realized_r         DOUBLE PRECISION,
    reconciled_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trade_entries_open
    ON trade_entries (reconciled_at)
    WHERE reconciled_at IS NULL;
