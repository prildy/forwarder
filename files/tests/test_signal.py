"""Test model Signal (schema 2.0/2.1) + endpoint POST /webhook/{token}.

Tanpa DB/jaringan: append_jsonl, already_seen, dan ingest_signal di-monkeypatch.
TestClient dipakai TANPA blok `with` supaya lifespan (migrate DB) tidak jalan.
"""
import copy
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import main


def _valid() -> dict:
  # Payload minimal yang lolos validasi (schema 2.0); selalu kembalikan salinan baru.
  return copy.deepcopy({
    "schema": "2.0",
    "event_id": "XAUUSD-30S-1700000000000",
    "source": "tradingview",
    "symbol": "XAUUSD",
    "ticker": "OANDA:XAUUSD",
    "timeframe": "30S",
    "bar_time": "2024-01-01T00:00:00Z",
    "bar_time_ms": 1704067200000,
    "triggers": ["bbma_reentry"],
    "candle": {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0,
               "volume": 10, "atr": 1.5, "atr_len": 14},
    "liquidity_pools": {"bsl_nearest": 103.0, "ssl_nearest": 98.0},
    "smc": {"structure_trend": "bullish"},
    "bbma": {"x": 1},
    "ichimoku": {"x": 1},
    "vw_trend": {"x": 1},
    "adx_di": {"x": 1},
    "stoch_rsi": {"x": 1},
    "macd": {"x": 1},
  })


def _locs(exc: ValidationError) -> list:
  return [".".join(str(p) for p in e["loc"]) for e in exc.errors()]


# ===================== model Signal =====================


def test_signal_valid_20():
  s = main.Signal.model_validate(_valid())
  assert s.schema_version == "2.0"
  assert s.event_id == "XAUUSD-30S-1700000000000"
  # field opsional 2.1 punya default
  assert s.mtf == {} and s.momentum_filter == {}
  assert s.bar_confirmed is None and s.session is None


def test_signal_valid_21_keeps_extra_and_optional_blocks():
  p = _valid()
  p["schema"] = "2.1"
  p["bar_confirmed"] = True
  p["session"] = "london"
  p["mtf"] = {"M5": {"bias": "bull"}}
  p["field_baru"] = 42
  s = main.Signal.model_validate(p)
  assert s.schema_version == "2.1"
  assert s.bar_confirmed is True
  assert s.mtf == {"M5": {"bias": "bull"}}
  # extra="allow": field tak dikenal tetap tersimpan
  assert s.model_extra["field_baru"] == 42


@pytest.mark.parametrize("bad", ["1.0", "2.2", "", "2"])
def test_signal_bad_schema_value(bad):
  p = _valid()
  p["schema"] = bad
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert "schema" in _locs(ei.value)


@pytest.mark.parametrize("key", [
  "schema", "event_id", "source", "symbol", "ticker", "timeframe", "bar_time",
  "bar_time_ms", "triggers", "candle", "liquidity_pools", "smc", "bbma",
  "ichimoku", "vw_trend", "adx_di", "stoch_rsi", "macd",
])
def test_signal_missing_required_key(key):
  p = _valid()
  del p[key]
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert key in _locs(ei.value)


@pytest.mark.parametrize("key,value", [
  ("source", "binance"),
  ("event_id", ""),
  ("triggers", []),
  ("bar_time", "bukan-tanggal"),
  ("bar_time_ms", "abc"),
  ("bbma", []),
  ("macd", []),
])
def test_signal_bad_values(key, value):
  p = _valid()
  p[key] = value
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert key in _locs(ei.value)


@pytest.mark.parametrize("patch", [
  {"atr": 0},
  {"atr": -1.0},
  {"atr_len": 0},
  {"high": 100.5},   # high < close (101)
  {"low": 100.5},    # low > open (100)
])
def test_signal_candle_out_of_range(patch):
  p = _valid()
  p["candle"].update(patch)
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert any(loc.startswith("candle") for loc in _locs(ei.value))


def test_signal_candle_missing_atr():
  p = _valid()
  del p["candle"]["atr"]
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert "candle.atr" in _locs(ei.value)


def test_signal_candle_ohlc_boundary_ok():
  # high == close dan low == open persis di batas → masih valid
  p = _valid()
  p["candle"].update({"open": 100.0, "close": 101.0, "high": 101.0, "low": 100.0})
  main.Signal.model_validate(p)


def test_signal_smc_missing_structure_trend():
  p = _valid()
  p["smc"] = {"swing_high": 1.0}
  with pytest.raises(ValidationError) as ei:
    main.Signal.model_validate(p)
  assert "smc.structure_trend" in _locs(ei.value)


# ===================== endpoint /webhook/{token} =====================


@pytest.fixture
def env(monkeypatch):
  records = []
  monkeypatch.setattr(main, "ENFORCE_TV_IPS", False)
  monkeypatch.setattr(main, "append_jsonl", lambda name, rec: records.append((name, rec)))
  client = TestClient(main.app)
  return client, records


def _url(token=None):
  return f"/webhook/{main.WEBHOOK_SECRET if token is None else token}"


def _fail_if_called(*a, **k):
  raise AssertionError("already_seen tidak boleh dipanggil untuk payload invalid")


def test_webhook_invalid_payload_422_and_rejected_logged(env, monkeypatch):
  client, records = env
  monkeypatch.setattr(main, "already_seen", _fail_if_called)
  p = _valid()
  del p["smc"]
  r = client.post(_url(), content=json.dumps(p))
  assert r.status_code == 422
  assert any(e["loc"] == "smc" for e in r.json()["detail"])
  rejected = [rec for name, rec in records if name == "rejected"]
  assert len(rejected) == 1
  assert any(e["loc"] == "smc" for e in rejected[0]["errors"])


def test_webhook_wrong_token_404(env, monkeypatch):
  client, records = env
  monkeypatch.setattr(main, "already_seen", _fail_if_called)
  r = client.post(_url("salah-token"), content=json.dumps(_valid()))
  assert r.status_code == 404
  # ditolak sebelum body dibaca/dicatat
  assert records == []


def test_webhook_invalid_json_400(env, monkeypatch):
  client, records = env
  monkeypatch.setattr(main, "already_seen", _fail_if_called)
  r = client.post(_url(), content="{bukan json")
  assert r.status_code == 400
  assert not [1 for name, _ in records if name == "rejected"]


def test_webhook_happy_path_strips_secret(env, monkeypatch):
  client, records = env
  ingest = AsyncMock()
  monkeypatch.setattr(main, "ingest_signal", ingest)
  monkeypatch.setattr(main, "already_seen", lambda event_id: False)
  p = _valid()
  p["secret"] = "rahasia"
  r = client.post(_url(), content=json.dumps(p))
  assert r.status_code == 200
  assert r.json() == {"status": "accepted", "event_id": p["event_id"]}
  ingest.assert_awaited_once()
  forwarded, bar_time = ingest.await_args.args
  assert "secret" not in forwarded
  assert forwarded["event_id"] == p["event_id"]
  assert bar_time.year == 2024


def test_webhook_duplicate_not_ingested(env, monkeypatch):
  client, _ = env
  ingest = AsyncMock()
  monkeypatch.setattr(main, "ingest_signal", ingest)
  monkeypatch.setattr(main, "already_seen", lambda event_id: True)
  r = client.post(_url(), content=json.dumps(_valid()))
  assert r.status_code == 200
  assert r.json() == {"status": "duplicate"}
  ingest.assert_not_awaited()
