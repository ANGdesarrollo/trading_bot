ALTER TABLE candles ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'capital';

ALTER TABLE candles DROP CONSTRAINT IF EXISTS candles_epic_resolution_candle_start_key;

DROP INDEX IF EXISTS idx_candles_recent;

ALTER TABLE candles
    ADD CONSTRAINT candles_provider_epic_resolution_candle_start_key
    UNIQUE (provider, epic, resolution, candle_start);

CREATE INDEX IF NOT EXISTS idx_candles_recent
    ON candles (provider, epic, resolution, candle_start DESC);
