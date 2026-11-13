"""Unit test untuk main.py — fungsi murni + gate forward auto-capture.

forward_autocapture di-test tanpa DB/jaringan: dependensi DB & panggilan Hermes
di-monkeypatch, dan konfigurasi FORWARD_* di-override di level modul. Fungsi async
dijalankan lewat asyncio.run(...) supaya tak butuh pytest-asyncio.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest
from psycopg import errors as pg_errors

import main


# ===================== parse_json_loose =====================


def test_parse_json_loose_plain_json():
  assert main.parse_json_loose('{"decision": "long"}') == {"decision": "long"}


def test_parse_json_loose_json_fenced():
  assert main.parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_loose_bare_fenced():
  assert main.parse_json_loose('```\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_loose_garbage_returns_none():
  assert main.parse_json_loose("bukan json sama sekali") is None


def test_parse_json_loose_non_dict_json_returns_none():
  # JSON valid tapi bukan object (list) → None.
  assert main.parse_json_loose("[1, 2, 3]") is None


# ===================== classify_r =====================


def test_classify_r_win():
  assert main.classify_r(1.0) == "win"


def test_classify_r_loss():
  assert main.classify_r(-1.0) == "loss"


def test_classify_r_exact_zero_breakeven():
  assert main.classify_r(0.0) == "breakeven"


def test_classify_r_small_positive_breakeven():
  assert main.classify_r(0.04) == "breakeven"


def test_classify_r_small_negative_breakeven():
  assert main.classify_r(-0.04) == "breakeven"


def test_classify_r_just_above_threshold_win():
  assert main.classify_r(0.06) == "win"


def test_classify_r_just_below_threshold_loss():
  assert main.classify_r(-0.06) == "loss"


# ===================== _coerce_float =====================


def test_coerce_float_int():
  assert main._coerce_float(5) == 5.0


def test_coerce_float_float():
  assert main._coerce_float(1.5) == 1.5


def test_coerce_float_numeric_string():
  assert main._coerce_float("2.5") == 2.5


def test_coerce_float_numeric_string_with_whitespace():
  assert main._coerce_float("  3  ") == 3.0


def test_coerce_float_bool_is_none():
  # bool subclass dari int, tapi harga true/false tak masuk akal → None.
  assert main._coerce_float(True) is None
  assert main._coerce_float(False) is None


def test_coerce_float_na_string_is_none():
  assert main._coerce_float("na") is None


def test_coerce_float_none_is_none():
  assert main._coerce_float(None) is None


def test_coerce_float_non_numeric_string_is_none():
  assert main._coerce_float("abc") is None


def test_coerce_float_list_is_none():
  assert main._coerce_float([1, 2]) is None


# ===================== parse_hermes_decision =====================


def test_parse_hermes_decision_valid_long():
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 99, "take_profit": 102,
      "confidence": 0.8, "setup_tags": ["bbma", "reentry"],
  })
  result = main.parse_hermes_decision(content)

  assert result == {
      "decision": "long",
      "entry": 100.0,
      "stop_loss": 99.0,
      "take_profit": 102.0,
      "confidence": 0.8,
      "setup_tags": ["bbma", "reentry"],
  }


def test_parse_hermes_decision_uppercase_is_normalized():
  content = json.dumps({"decision": "LONG", "confidence": 0.7})
  result = main.parse_hermes_decision(content)

  assert result["decision"] == "long"


def test_parse_hermes_decision_no_trade():
  content = json.dumps({
      "decision": "no_trade", "entry": None, "stop_loss": None,
      "take_profit": None, "confidence": 0.3,
  })
  result = main.parse_hermes_decision(content)

  assert result["decision"] == "no_trade"
  assert result["entry"] is None
  assert result["stop_loss"] is None
  assert result["take_profit"] is None


def test_parse_hermes_decision_missing_confidence_defaults_zero():
  content = json.dumps({"decision": "long"})
  assert main.parse_hermes_decision(content)["confidence"] == 0.0


def test_parse_hermes_decision_na_confidence_defaults_zero():
  content = json.dumps({"decision": "long", "confidence": "na"})
  assert main.parse_hermes_decision(content)["confidence"] == 0.0


def test_parse_hermes_decision_non_numeric_levels_become_none():
  content = json.dumps({
      "decision": "long", "entry": "na", "stop_loss": "x",
      "take_profit": "y", "confidence": 0.6,
  })
  result = main.parse_hermes_decision(content)

  assert result["entry"] is None
  assert result["stop_loss"] is None
  assert result["take_profit"] is None


def test_parse_hermes_decision_unknown_decision_returns_none():
  content = json.dumps({"decision": "hold", "confidence": 0.9})
  assert main.parse_hermes_decision(content) is None


def test_parse_hermes_decision_non_string_decision_returns_none():
  content = json.dumps({"decision": 123, "confidence": 0.9})
  assert main.parse_hermes_decision(content) is None


def test_parse_hermes_decision_garbage_returns_none():
  assert main.parse_hermes_decision("bukan json") is None


def test_parse_hermes_decision_non_list_setup_tags_becomes_empty():
  content = json.dumps({"decision": "long", "confidence": 0.7, "setup_tags": "bbma"})
  assert main.parse_hermes_decision(content)["setup_tags"] == []


# ===================== _levels_sane =====================


def test_levels_sane_long_valid():
  assert main._levels_sane("long", 100, 99, 102) is True


def test_levels_sane_long_invalid():
  # sl > entry melanggar sl < entry < tp.
  assert main._levels_sane("long", 100, 101, 102) is False


def test_levels_sane_short_valid():
  assert main._levels_sane("short", 100, 101, 98) is True


def test_levels_sane_short_invalid():
  assert main._levels_sane("short", 100, 99, 98) is False


# ===================== _triggers_qualify =====================


def test_triggers_qualify_empty_triggers_is_false(monkeypatch):
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", set())
  assert main._triggers_qualify([]) is False


def test_triggers_qualify_empty_filter_any_nonempty_passes(monkeypatch):
  # FORWARD_TRIGGERS kosong = trigger apa pun lolos asal daftar tidak kosong.
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", set())
  assert main._triggers_qualify(["anything"]) is True


def test_triggers_qualify_with_filter_requires_intersection(monkeypatch):
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", {"a", "b"})
  assert main._triggers_qualify(["a"]) is True


def test_triggers_qualify_with_filter_no_intersection_is_false(monkeypatch):
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", {"a"})
  assert main._triggers_qualify(["x"]) is False


# ===================== forward_autocapture =====================


def _setup_autocapture(monkeypatch, *, enabled=True, hermes_content="",
                       hermes_exc=None, has_open=False, min_conf=0.6, newer=False):
  """Pasang semua dependensi forward_autocapture dengan test double. Return (hermes, create)."""
  monkeypatch.setattr(main, "FORWARD_AUTOCAPTURE", enabled)
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", set())
  monkeypatch.setattr(main, "FORWARD_MIN_CONFIDENCE", min_conf)

  if hermes_exc is not None:
    hermes = AsyncMock(side_effect=hermes_exc)
  else:
    hermes = AsyncMock(return_value=(hermes_content, 0.1))
  monkeypatch.setattr(main, "forward_to_hermes", hermes)

  create = Mock(return_value=123)
  monkeypatch.setattr(main, "create_journal_entry", create)
  monkeypatch.setattr(main, "has_open_forward_trade", Mock(return_value=has_open))
  monkeypatch.setattr(main, "fetch_alert_id", Mock(return_value=7))
  monkeypatch.setattr(main, "has_newer_alert", Mock(return_value=newer))
  return hermes, create


def _payload():
  return {"symbol": main.DEFAULT_SYMBOL, "timeframe": main.DEFAULT_TF, "triggers": ["x"]}


def _run_autocapture():
  asyncio.run(main.forward_autocapture(_payload(), datetime.now(timezone.utc)))


def test_forward_autocapture_default_off_is_noop(monkeypatch):
  # Master switch off: tak ada panggilan Hermes dan tak ada jurnal dibuat.
  hermes, create = _setup_autocapture(monkeypatch, enabled=False)
  _run_autocapture()

  hermes.assert_not_called()
  create.assert_not_called()


def test_forward_autocapture_enabled_valid_long_creates_entry(monkeypatch):
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 99, "take_profit": 102,
      "confidence": 0.8, "setup_tags": ["bbma"],
  })
  hermes, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)
  _run_autocapture()

  hermes.assert_called_once()
  create.assert_called_once()
  args = create.call_args.args
  # create_journal_entry(symbol, timeframe, mode, direction, entry, sl, tp, tags, alert_id, analysis_id)
  assert args[0] == main.DEFAULT_SYMBOL
  assert args[1] == main.DEFAULT_TF
  assert args[2] == "forward"
  assert args[3] == "long"
  assert args[4] == 100.0
  assert args[5] == 99.0
  assert args[6] == 102.0
  assert args[7] == ["bbma"]
  assert args[8] == 7          # alert_id dari fetch_alert_id (cocok persis per bar)
  assert args[9] is None       # analysis_id


def test_forward_autocapture_empty_triggers_never_calls_hermes(monkeypatch):
  # Bar tanpa trigger: tak ada panggilan Hermes dan tak ada jurnal.
  hermes, create = _setup_autocapture(monkeypatch, enabled=True)
  payload = _payload()
  payload["triggers"] = []
  asyncio.run(main.forward_autocapture(payload, datetime.now(timezone.utc)))

  hermes.assert_not_called()
  create.assert_not_called()


def test_forward_autocapture_below_min_confidence_no_capture(monkeypatch):
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 99, "take_profit": 102,
      "confidence": 0.5,
  })
  _, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content,
                                 min_conf=0.6)
  _run_autocapture()

  create.assert_not_called()


def test_forward_autocapture_open_trade_guard_blocks(monkeypatch):
  # Anti-pyramiding: ada forward trade open → Hermes tak dipanggil, tak ada capture.
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 99, "take_profit": 102,
      "confidence": 0.9,
  })
  hermes, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content,
                                      has_open=True)
  _run_autocapture()

  hermes.assert_not_called()
  create.assert_not_called()


def test_forward_autocapture_no_trade_no_capture(monkeypatch):
  content = json.dumps({
      "decision": "no_trade", "entry": None, "stop_loss": None,
      "take_profit": None, "confidence": 0.9,
  })
  _, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)
  _run_autocapture()

  create.assert_not_called()


def test_forward_autocapture_bad_levels_no_capture(monkeypatch):
  # Decision long tapi level tak masuk akal (sl > entry) → _levels_sane gagal → skip.
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 101, "take_profit": 102,
      "confidence": 0.9,
  })
  _, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)
  _run_autocapture()

  create.assert_not_called()


def test_forward_autocapture_null_levels_no_capture(monkeypatch):
  content = json.dumps({
      "decision": "long", "entry": None, "stop_loss": None,
      "take_profit": None, "confidence": 0.9,
  })
  _, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)
  _run_autocapture()

  create.assert_not_called()


def test_forward_autocapture_hermes_exception_is_swallowed(monkeypatch):
  # Hermes meledak → tidak boleh propagate keluar; tak ada capture.
  _, create = _setup_autocapture(monkeypatch, enabled=True,
                                 hermes_exc=RuntimeError("hermes mati"))
  # Tak ada exception yang keluar.
  _run_autocapture()

  create.assert_not_called()


def test_forward_autocapture_unique_violation_is_graceful(monkeypatch):
  # Finding 2: race lolos pre-check, INSERT forward kedua kena unique index →
  # create_journal_entry lempar ForwardTradeExists → ditangani rapi, tak propagate.
  content = json.dumps({
      "decision": "long", "entry": 100, "stop_loss": 99, "take_profit": 102,
      "confidence": 0.9,
  })
  _, create = _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)
  create.side_effect = main.ForwardTradeExists("sudah ada forward terbuka")
  # Tak ada exception yang keluar dari background task.
  _run_autocapture()

  create.assert_called_once()


# ===================== fake POOL untuk tes query path (tanpa DB nyata) =====================


class _FakeCursor:
  def __init__(self, rows):
    self._rows = rows
    self.rowcount = len(rows)

  def fetchall(self):
    return self._rows

  def fetchone(self):
    return self._rows[0] if self._rows else None


class _FakeConn:
  """Konektor palsu: rekam tiap execute dan balas hasil sesuai urutan panggilan."""

  def __init__(self, results_by_call):
    self.executed = []            # list of (sql, params)
    self._results = results_by_call

  def execute(self, sql, params=None):
    index = len(self.executed)
    self.executed.append((sql, params))
    rows = self._results[index] if index < len(self._results) else []
    return _FakeCursor(rows)

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    return False


class _FakePool:
  def __init__(self, conn):
    self._conn = conn

  def connection(self):
    return self._conn


# ===================== create_journal_entry: unique violation (Finding 2) =====================


def test_create_journal_entry_raises_forward_trade_exists_on_unique_violation(monkeypatch):
  class _RaisingConn(_FakeConn):
    def execute(self, sql, params=None):
      raise pg_errors.UniqueViolation("duplicate key journal_one_open_forward")

  monkeypatch.setattr(main, "POOL", _FakePool(_RaisingConn([])))

  with pytest.raises(main.ForwardTradeExists):
    main.create_journal_entry("FX:XAUUSD", "30S", "forward", "long",
                              100.0, 99.0, 102.0, [], None, None)


def test_create_journal_entry_returns_id_on_success(monkeypatch):
  conn = _FakeConn([[(42,)]])   # INSERT ... RETURNING id
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  journal_id = main.create_journal_entry("FX:XAUUSD", "30S", "live", "long",
                                         100.0, 99.0, 102.0, [], None, None)

  assert journal_id == 42


# ===================== resolve_open_trades: scoping & delegasi (Finding 1 + 3) =====================


def test_resolve_open_trades_query_scoped_to_live_and_forward(monkeypatch):
  # Finding 1: SELECT open trades harus memfilter mode live/forward supaya baris
  # mode='backtest' tak pernah ikut terseleksi/ditutup resolver live.
  conn = _FakeConn([[]])         # query open-trades balas kosong (seperti DB tanpa live/forward)
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  resolved = main.resolve_open_trades()

  assert resolved == 0
  open_sql = conn.executed[0][0]
  assert "mode IN ('live', 'forward')" in open_sql
  assert "status = 'open'" in open_sql
  # Tak ada query/UPDATE lanjutan karena tak ada open trade.
  assert len(conn.executed) == 1


def test_resolve_open_trades_closes_live_trade_via_resolver(monkeypatch):
  # Finding 3: resolver bersama dipakai — trade live long yang TP-nya tersentuh ditutup win.
  opened_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
  bar_time = opened_at + timedelta(minutes=1)
  open_row = (7, "FX:XAUUSD", "30S", "long",
              Decimal("100"), Decimal("99"), Decimal("102"), opened_at)
  bar_row = (bar_time, Decimal("102"), Decimal("100"))   # high>=tp → win

  conn = _FakeConn([
      [open_row],     # SELECT open trades
      [bar_row],      # SELECT bars
      [],             # UPDATE
  ])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  resolved = main.resolve_open_trades()

  assert resolved == 1
  update_sql, update_params = conn.executed[2]
  assert "UPDATE journal" in update_sql
  # (status, exit_price, r_multiple, closed_at, id)
  assert update_params[0] == "win"
  assert update_params[1] == Decimal("102")
  assert update_params[2] == Decimal(2)
  assert update_params[3] == bar_time
  assert update_params[4] == 7


# ===================== save_alert: kembalikan bool berdasarkan rowcount =====================


def test_save_alert_returns_true_on_fresh_insert(monkeypatch):
  # rowcount=1 → baris baru diinsert → True
  conn = _FakeConn([[("inserted",)]])   # rowcount = len(rows) = 1
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  bar_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
  payload = {"symbol": "FX:XAUUSD", "timeframe": "30S"}
  result = main.save_alert(payload, bar_time)

  assert result is True


def test_save_alert_returns_false_on_conflict(monkeypatch):
  # rowcount=0 → ON CONFLICT DO NOTHING menyerap baris → False
  conn = _FakeConn([[]])   # rowcount = len(rows) = 0
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  bar_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
  payload = {"symbol": "FX:XAUUSD", "timeframe": "30S"}
  result = main.save_alert(payload, bar_time)

  assert result is False


# ===================== ingest_signal: guard per-bar =====================


@pytest.fixture
def _fresh_autocaptured(monkeypatch):
  # State modul dipakai lintas test → pakai instance baru per test.
  from collections import OrderedDict
  monkeypatch.setattr(main, "_autocaptured", OrderedDict())


def _setup_ingest(monkeypatch, *, consulted=True):
  monkeypatch.setattr(main, "save_alert", Mock(return_value=True))
  autocapture = AsyncMock(return_value=consulted)
  monkeypatch.setattr(main, "forward_autocapture", autocapture)
  return autocapture


_BAR = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ALERT = {"symbol": "FX:XAUUSD", "timeframe": "30S"}


def test_ingest_signal_calls_forward_autocapture_when_inserted(monkeypatch, _fresh_autocaptured):
  autocapture = _setup_ingest(monkeypatch)
  asyncio.run(main.ingest_signal(_ALERT, _BAR))

  autocapture.assert_awaited_once_with(_ALERT, _BAR)


def test_ingest_signal_conflict_alone_does_not_skip_autocapture(monkeypatch, _fresh_autocaptured):
  # Alert kedua utk bar yang sama (save_alert=False, trigger berbeda) belum pernah
  # dikonsultasikan → tetap harus diteruskan (mis. split konteks + signal).
  autocapture = _setup_ingest(monkeypatch)
  main.save_alert.return_value = False
  asyncio.run(main.ingest_signal(_ALERT, _BAR))

  autocapture.assert_awaited_once()


def test_ingest_signal_skips_bar_already_consulted(monkeypatch, _fresh_autocaptured):
  # Hermes sudah dikonsultasi utk bar ini → alert duplikat tidak memicu panggilan kedua.
  autocapture = _setup_ingest(monkeypatch, consulted=True)
  asyncio.run(main.ingest_signal(_ALERT, _BAR))
  asyncio.run(main.ingest_signal(dict(_ALERT), _BAR))

  autocapture.assert_awaited_once()


def test_ingest_signal_retries_bar_when_hermes_not_consulted(monkeypatch, _fresh_autocaptured):
  # Hermes gagal / skip pra-Hermes (return False) → bar tidak terkunci, re-send boleh coba lagi.
  autocapture = _setup_ingest(monkeypatch, consulted=False)
  asyncio.run(main.ingest_signal(_ALERT, _BAR))
  asyncio.run(main.ingest_signal(dict(_ALERT), _BAR))

  assert autocapture.await_count == 2


def test_ingest_signal_releases_key_when_autocapture_raises(monkeypatch, _fresh_autocaptured):
  autocapture = _setup_ingest(monkeypatch)
  autocapture.side_effect = RuntimeError("boom")

  with pytest.raises(RuntimeError):
    asyncio.run(main.ingest_signal(_ALERT, _BAR))
  assert not main._autocaptured


def test_forward_autocapture_skips_stale_out_of_order_bar(monkeypatch):
  # Sudah ada bar lebih baru → bar telat tidak boleh sampai ke Hermes; return False
  # (belum dikonsultasi) supaya kuncinya dilepas.
  hermes, create = _setup_autocapture(monkeypatch, enabled=True, newer=True)

  assert asyncio.run(main.forward_autocapture(_payload(), _BAR)) is False
  hermes.assert_not_called()
  create.assert_not_called()


def test_forward_autocapture_newer_check_runs_after_cheap_gates(monkeypatch):
  # Bar kosong (tanpa trigger) tidak boleh memicu query has_newer_alert.
  _setup_autocapture(monkeypatch, enabled=True)
  payload = _payload()
  payload["triggers"] = []
  monkeypatch.setattr(main, "FORWARD_TRIGGERS", {"x"})

  assert asyncio.run(main.forward_autocapture(payload, _BAR)) is False
  main.has_newer_alert.assert_not_called()


def test_ingest_signal_bounds_autocaptured_size(monkeypatch, _fresh_autocaptured):
  monkeypatch.setattr(main, "DEDUPE_SIZE", 2)
  _setup_ingest(monkeypatch)
  for minute in range(5):
    asyncio.run(main.ingest_signal(_ALERT, _BAR + timedelta(minutes=minute)))

  assert len(main._autocaptured) == 2


# ===================== fetch_alert_id / has_newer_alert =====================


def test_fetch_alert_id_matches_exact_unique_key(monkeypatch):
  conn = _FakeConn([[(42,)]])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  assert main.fetch_alert_id("FX:XAUUSD", "30S", _BAR) == 42
  sql, params = conn.executed[0]
  assert "bar_time = %s" in sql
  assert "ORDER BY" not in sql
  assert params == ("FX:XAUUSD", "30S", _BAR)


def test_fetch_alert_id_none_when_missing(monkeypatch):
  monkeypatch.setattr(main, "POOL", _FakePool(_FakeConn([[]])))

  assert main.fetch_alert_id("FX:XAUUSD", "30S", _BAR) is None


def test_has_newer_alert_true_and_false(monkeypatch):
  conn = _FakeConn([[(1,)], []])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  assert main.has_newer_alert("FX:XAUUSD", "30S", _BAR) is True
  assert main.has_newer_alert("FX:XAUUSD", "30S", _BAR) is False
  assert "bar_time > %s" in conn.executed[0][0]
  assert conn.executed[0][1] == ("FX:XAUUSD", "30S", _BAR)


# ===================== forward_autocapture: nilai balik "sudah dikonsultasi" =====================


def test_forward_autocapture_returns_true_after_hermes_consulted(monkeypatch):
  content = json.dumps({"decision": "no_trade", "confidence": 0.1})
  _setup_autocapture(monkeypatch, enabled=True, hermes_content=content)

  assert asyncio.run(main.forward_autocapture(_payload(), _BAR)) is True


def test_forward_autocapture_returns_false_before_hermes(monkeypatch):
  hermes, _ = _setup_autocapture(monkeypatch, enabled=True, has_open=True)

  assert asyncio.run(main.forward_autocapture(_payload(), _BAR)) is False
  hermes.assert_not_called()


def test_forward_autocapture_returns_false_when_hermes_fails(monkeypatch):
  _setup_autocapture(monkeypatch, enabled=True, hermes_exc=RuntimeError("down"))

  assert asyncio.run(main.forward_autocapture(_payload(), _BAR)) is False


# ===================== async DB audit: migrate() via asyncio.to_thread =====================


def test_migrate_is_sync_callable():
  # migrate() harus fungsi sinkron (bukan coroutine) supaya aman dipakai asyncio.to_thread.
  import inspect
  assert not inspect.iscoroutinefunction(main.migrate)


def test_lifespan_runs_migrate_off_the_event_loop_thread(monkeypatch):
  # Bukti nyata (bukan sekadar "terpanggil"): migrate harus jalan di thread BERBEDA
  # dari thread event loop. Kalau lifespan memanggil migrate() langsung, test ini gagal.
  import threading
  seen = {}

  monkeypatch.setattr(main, "migrate", lambda: seen.setdefault("migrate", threading.get_ident()))
  monkeypatch.setattr(main.POOL, "open", lambda: None)
  monkeypatch.setattr(main.POOL, "close", lambda: None)
  monkeypatch.setattr(main, "SCHEDULER", type("FakeSched", (), {
    "add_job": lambda *a, **k: None,
    "start": lambda self: None,
    "shutdown": lambda self: None,
  })())

  async def _run():
    seen["loop"] = threading.get_ident()
    async with main.lifespan(main.app):
      pass

  asyncio.run(_run())
  assert "migrate" in seen, "migrate harus dipanggil saat startup lifespan"
  assert seen["migrate"] != seen["loop"], "migrate tidak boleh jalan di thread event loop"


# ===================== fetch_latest_alert: require_trigger =====================


def test_fetch_latest_alert_require_trigger_adds_jsonb_filter(monkeypatch):
  conn = _FakeConn([[]])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))
  main.fetch_latest_alert("XAUUSD", "30S", require_trigger=True)

  sql, params = conn.executed[0]
  assert "jsonb_array_length(payload->'triggers') > 0" in sql
  assert params == ("XAUUSD", "30S")


def test_fetch_latest_alert_default_has_no_trigger_filter(monkeypatch):
  conn = _FakeConn([[]])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))
  main.fetch_latest_alert("XAUUSD", "30S")

  assert "jsonb_array_length" not in conn.executed[0][0]


def test_run_hermes_analysis_fetches_with_require_trigger(monkeypatch):
  fetch = Mock(return_value=None)
  monkeypatch.setattr(main, "fetch_latest_alert", fetch)
  with pytest.raises(LookupError):
    asyncio.run(main.run_hermes_analysis("XAUUSD", "30S"))

  assert fetch.call_args.kwargs == {"require_trigger": True}


def test_analyze_endpoint_fetches_with_require_trigger(monkeypatch):
  from fastapi.testclient import TestClient
  fetch = Mock(return_value=None)
  monkeypatch.setattr(main, "fetch_latest_alert", fetch)
  client = TestClient(main.app)
  r = client.post(f"/analyze/{main.ANALYZE_SECRET}")

  assert r.status_code == 404
  assert fetch.call_args.kwargs == {"require_trigger": True}


# ===================== ingest_signal: save gagal =====================


def test_ingest_signal_save_failure_forgets_event_and_skips_autocapture(monkeypatch):
  main._seen.clear()
  assert main.already_seen("evt-p2") is False
  monkeypatch.setattr(main, "save_alert", Mock(side_effect=RuntimeError("db down")))
  autocapture = AsyncMock()
  monkeypatch.setattr(main, "forward_autocapture", autocapture)
  logged = []
  monkeypatch.setattr(main, "append_jsonl", lambda name, rec: logged.append((name, rec)))

  asyncio.run(main.ingest_signal({"event_id": "evt-p2"}, datetime.now(timezone.utc)))

  assert "evt-p2" not in main._seen
  autocapture.assert_not_called()
  assert len(logged) == 1
  assert logged[0][0] == "errors"
  assert logged[0][1]["event_id"] == "evt-p2"
  assert "db down" in logged[0][1]["error"]
  # replay event_id yang sama sekarang diterima
  assert main.already_seen("evt-p2") is False
  main._seen.clear()


def test_ingest_signal_success_keeps_event_and_runs_autocapture(monkeypatch, _fresh_autocaptured):
  main._seen.clear()
  main.already_seen("evt-ok")
  monkeypatch.setattr(main, "save_alert", Mock())
  autocapture = AsyncMock(return_value=True)
  monkeypatch.setattr(main, "forward_autocapture", autocapture)

  asyncio.run(main.ingest_signal({"event_id": "evt-ok"}, datetime.now(timezone.utc)))

  assert main.already_seen("evt-ok") is True
  autocapture.assert_called_once()
  main._seen.clear()


def test_forget_event_unknown_is_noop():
  main._seen.clear()
  main.forget_event("nope")
  assert "nope" not in main._seen


# ===================== resolve_open_trades: level terbalik tidak menghentikan loop =====================


def test_resolve_open_trades_skips_inverted_levels_and_resolves_the_rest(monkeypatch):
  bar_time = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
  opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
  trades = [
    # id 1: long dengan SL di atas entry (terbalik) -> resolver raise ValueError
    (1, "FX:XAUUSD", "30S", "long", Decimal(100), Decimal(101), Decimal(102), opened),
    # id 2: normal, TP tersentuh
    (2, "FX:XAUUSD", "30S", "long", Decimal(100), Decimal(98), Decimal(102), opened),
  ]
  bars = [(bar_time, Decimal(103), Decimal(100))]
  conn = _FakeConn([trades, bars, bars])
  monkeypatch.setattr(main, "POOL", _FakePool(conn))

  resolved = main.resolve_open_trades()

  assert resolved == 1
  updates = [(sql, params) for sql, params in conn.executed if "UPDATE journal" in sql]
  assert len(updates) == 1
  assert updates[0][1][4] == 2          # hanya trade id 2 yang ditutup
  assert updates[0][1][0] == "win"


# ===================== /journal dan /status: pilih alert ber-trigger =====================


def test_tg_cmd_journal_links_latest_signal_not_empty_bar(monkeypatch):
  fetch = Mock(return_value={"id": 55, "payload": {}, "bar_time": _BAR})
  monkeypatch.setattr(main, "fetch_latest_alert", fetch)
  create = Mock(return_value=9)
  monkeypatch.setattr(main, "create_journal_entry", create)
  monkeypatch.setattr(main, "tg_send", AsyncMock())

  asyncio.run(main.tg_cmd_journal(1, ["live", "long", "100", "99", "102"]))

  assert fetch.call_args.kwargs == {"require_trigger": True}
  assert create.call_args.args[8] == 55       # alert_id = sinyal ber-trigger


def test_status_command_shows_latest_bar_and_last_signal(monkeypatch):
  from fastapi.testclient import TestClient
  now = datetime.now(timezone.utc)
  latest = {"id": 1, "payload": {}, "bar_time": now}
  signal = {"id": 2, "payload": {}, "bar_time": now - timedelta(minutes=90)}

  def fake_fetch(symbol, timeframe, *, require_trigger=False):
    return signal if require_trigger else latest

  monkeypatch.setattr(main, "fetch_latest_alert", fake_fetch)
  send = AsyncMock()
  monkeypatch.setattr(main, "tg_send", send)
  chat_id = next(iter(main.TG_ALLOWED))

  r = TestClient(main.app).post(
      "/telegram/webhook",
      headers={"x-telegram-bot-api-secret-token": main.TG_SECRET},
      json={"message": {"chat": {"id": chat_id}, "text": "/status"}},
  )

  assert r.status_code == 200
  text = send.call_args.args[1]
  assert "Alert terakhir" in text
  assert "Sinyal terakhir" in text and "90 mnt" in text
