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
  id             BIGSERIAL PRIMARY KEY,
  requested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  alert_id       BIGINT REFERENCES alerts(id),
  model          TEXT, prompt_version TEXT,
  output         JSONB,           -- trading plan dari LLM
  risk_verdict   JSONB            -- hasil cek R:R, daily loss cap, dll.
);