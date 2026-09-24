CREATE TABLE IF NOT EXISTS alerts (
  id          BIGSERIAL PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol      TEXT NOT NULL,
  timeframe   TEXT NOT NULL,
  bar_time    TIMESTAMPTZ NOT NULL,
  payload     JSONB NOT NULL,
  UNIQUE (symbol, timeframe, bar_time)   -- dedup kalau alert terkirim dua kali
);

CREATE TABLE IF NOT EXISTS analyses (
    id           BIGSERIAL PRIMARY KEY,
    alert_id     BIGINT REFERENCES alerts(id) ON DELETE SET NULL,
    symbol       TEXT NOT NULL,
    timeframe    TEXT NOT NULL,
    bar_time     TIMESTAMPTZ NOT NULL,
    trigger_src  TEXT NOT NULL,          -- 'api' | 'telegram'
    latency_s    REAL,
    response_raw TEXT NOT NULL,          -- teks mentah dari Hermes
    response     JSONB,                  -- hasil parse JSON (NULL kalau gagal parse)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analyses_symbol_tf_created
    ON analyses (symbol, timeframe, created_at DESC);