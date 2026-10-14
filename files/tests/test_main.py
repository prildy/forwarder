"""Unit test untuk main.py — fungsi murni + gate forward auto-capture.

forward_autocapture di-test tanpa DB/jaringan: dependensi DB & panggilan Hermes
di-monkeypatch, dan konfigurasi FORWARD_* di-override di level modul. Fungsi async
dijalankan lewat asyncio.run(...) supaya tak butuh pytest-asyncio.
"""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock

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
                       hermes_exc=None, has_open=False, min_conf=0.6):
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
  monkeypatch.setattr(main, "fetch_latest_alert",
                      Mock(return_value={"id": 7, "payload": {}, "bar_time": None}))
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
  assert args[8] == 7          # alert_id dari fetch_latest_alert
  assert args[9] is None       # analysis_id


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
