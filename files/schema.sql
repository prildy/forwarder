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

CREATE TABLE IF NOT EXISTS journal (
  id            BIGSERIAL PRIMARY KEY,
  alert_id      BIGINT REFERENCES alerts(id)   ON DELETE SET NULL,
  analysis_id   BIGINT REFERENCES analyses(id) ON DELETE SET NULL,
  symbol        TEXT NOT NULL,
  timeframe     TEXT NOT NULL,
  mode          TEXT NOT NULL DEFAULT 'live',   -- 'live' | 'forward' | 'backtest'
  direction     TEXT NOT NULL,                  -- 'long' | 'short'
  entry         NUMERIC NOT NULL,
  stop_loss     NUMERIC NOT NULL,
  take_profit   NUMERIC NOT NULL,
  status        TEXT NOT NULL DEFAULT 'open',   -- open|win|loss|breakeven|skipped
  exit_price    NUMERIC,
  r_multiple    NUMERIC,
  opened_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at     TIMESTAMPTZ,
  setup_tags    TEXT[] DEFAULT '{}',
  lesson        TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journal_mode_symbol_status ON journal (mode, symbol, status);
CREATE INDEX IF NOT EXISTS journal_open ON journal (status) WHERE status = 'open';
-- Anti-pyramiding tingkat DB: maksimal satu forward trade OPEN per symbol+timeframe.
-- Ini penjamin sebenarnya terhadap race check-then-act di forward_autocapture
-- (dua webhook bersamaan bisa lolos pre-check sebelum call Hermes yang lambat).
-- Catatan migrasi: kalau tabel journal sudah berisi >=2 baris forward open untuk
-- symbol/tf yang sama, pembuatan index ini akan gagal. Tabel ini baru di PR ini
-- (belum ada di DB manapun yang berjalan), jadi aman.
CREATE UNIQUE INDEX IF NOT EXISTS journal_one_open_forward
    ON journal (symbol, timeframe) WHERE mode = 'forward' AND status = 'open';