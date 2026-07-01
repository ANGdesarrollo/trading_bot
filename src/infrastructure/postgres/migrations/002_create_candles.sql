CREATE TABLE IF NOT EXISTS candles (
    epic          TEXT        NOT NULL,
    resolution    TEXT        NOT NULL,
    candle_start  TIMESTAMPTZ NOT NULL,
    open_bid      NUMERIC     NOT NULL,
    high_bid      NUMERIC     NOT NULL,
    low_bid       NUMERIC     NOT NULL,
    close_bid     NUMERIC     NOT NULL,
    open_ask      NUMERIC     NOT NULL,
    high_ask      NUMERIC     NOT NULL,
    low_ask       NUMERIC     NOT NULL,
    close_ask     NUMERIC     NOT NULL,
    UNIQUE (epic, resolution, candle_start)
);

CREATE INDEX IF NOT EXISTS idx_candles_recent
    ON candles (epic, resolution, candle_start DESC);
