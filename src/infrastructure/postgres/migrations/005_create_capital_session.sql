CREATE TABLE IF NOT EXISTS capital_session (
    id              INTEGER     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    cst             TEXT        NOT NULL,
    security_token  TEXT        NOT NULL,
    streaming_host  TEXT        NOT NULL,
    authenticated_at TIMESTAMPTZ NOT NULL
);
