"""Unit test untuk backtest.py — resolver + strategy math.

Fokus pada logika yang mengkodekan perilaku trading: resolve_trade (tie-break,
first-touch, rumus R), compute_levels (ATR & swing), resolve_direction,
generate_trades (no-pyramiding, filter), dan build_summary (metrik).
Semua in-memory, tanpa DB/jaringan.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import backtest
from backtest import (
    Bar,
    EntryParams,
    GeneratedTrade,
    Resolution,
    build_summary,
    compute_levels,
    generate_trades,
    resolve_direction,
    resolve_trade,
)

# Waktu dasar; opened_at memakai T0, bar kandidat memakai T1 dst (bar_time > opened_at).
T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _t(minutes: int) -> datetime:
  return T0 + timedelta(minutes=minutes)


def make_bar(minutes: int, *, high=None, low=None, close=None, atr=None,
             triggers=None, structure_trend=None, swing_high=None, swing_low=None,
             alert_id: int = 1) -> Bar:
  """Bar fixture dengan nilai Decimal (mencerminkan kolom NUMERIC dari DB)."""
  def dec(value):
    return Decimal(str(value)) if value is not None else None

  return Bar(
      alert_id=alert_id,
      bar_time=_t(minutes),
      high=dec(high),
      low=dec(low),
      close=dec(close),
      atr=dec(atr),
      triggers=list(triggers) if triggers is not None else [],
      structure_trend=structure_trend,
      swing_high=dec(swing_high),
      swing_low=dec(swing_low),
  )


# ===================== resolve_trade =====================


def test_resolve_trade_long_win_hits_take_profit():
  # entry 100, sl 99, tp 102 → risk 1, reward 2, R = 2 (R:R 2.0 bersih).
  bars = [make_bar(1, high=102, low=100)]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "win"
  assert res.exit_price == Decimal("102")
  assert res.r_multiple == Decimal(2)
  assert res.closed_at == _t(1)
  assert res.is_open is False


def test_resolve_trade_long_loss_hits_stop_loss():
  # Low menyentuh SL → loss di stop_loss, R = -1.
  bars = [make_bar(1, high=100.5, low=99)]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "loss"
  assert res.exit_price == Decimal("99")
  assert res.r_multiple == Decimal(-1)


def test_resolve_trade_short_win_hits_take_profit():
  # short entry 100, sl 101, tp 98 → low <= tp menang, R = 2.
  bars = [make_bar(1, high=100.5, low=98)]
  res = resolve_trade("short", Decimal("100"), Decimal("101"), Decimal("98"), T0, bars)

  assert res.status == "win"
  assert res.exit_price == Decimal("98")
  assert res.r_multiple == Decimal(2)


def test_resolve_trade_short_loss_hits_stop_loss():
  # short high >= sl → loss, R = -1.
  bars = [make_bar(1, high=101, low=99)]
  res = resolve_trade("short", Decimal("100"), Decimal("101"), Decimal("98"), T0, bars)

  assert res.status == "loss"
  assert res.exit_price == Decimal("101")
  assert res.r_multiple == Decimal(-1)


def test_resolve_trade_both_touch_tie_break_is_loss():
  # Satu bar yang spannya [low, high] menyentuh SL dan TP sekaligus → LOSS di stop_loss.
  bars = [make_bar(1, high=103, low=98)]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "loss"
  assert res.exit_price == Decimal("99")


def test_resolve_trade_both_touch_tie_break_is_loss_short():
  # Simetris untuk short: bar menyentuh tp (low<=98) dan sl (high>=101) → loss di sl.
  bars = [make_bar(1, high=102, low=97)]
  res = resolve_trade("short", Decimal("100"), Decimal("101"), Decimal("98"), T0, bars)

  assert res.status == "loss"
  assert res.exit_price == Decimal("101")


def test_resolve_trade_first_touching_bar_decides():
  # Bar awal menyentuh SL (loss) menang atas bar berikutnya yang akan menyentuh TP.
  bars = [
      make_bar(1, high=100.5, low=99),    # sentuh SL dulu → loss
      make_bar(2, high=103, low=101),     # akan sentuh TP, tapi sudah telat
  ]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "loss"
  assert res.closed_at == _t(1)


def test_resolve_trade_no_touching_bar_stays_open():
  # Tak ada bar yang mencapai SL/TP → tetap open.
  bars = [make_bar(1, high=101, low=99.5), make_bar(2, high=101.5, low=99.2)]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "open"
  assert res.exit_price is None
  assert res.r_multiple is None
  assert res.closed_at is None
  assert res.is_open is True


def test_resolve_trade_zero_risk_stays_open():
  # entry == stop_loss → risk nol → guard: open tanpa menelusuri bar.
  bars = [make_bar(1, high=200, low=0)]
  res = resolve_trade("long", Decimal("100"), Decimal("100"), Decimal("102"), T0, bars)

  assert res.status == "open"
  assert res.is_open is True


def test_resolve_trade_ignores_bars_at_or_before_opened_at():
  # Bar di waktu opened_at (atau sebelumnya) harus dilewati (setara bar_time > opened_at).
  bars = [make_bar(0, high=103, low=98)]   # T0 == opened_at → diabaikan
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "open"


def test_resolve_trade_skips_bars_with_missing_high_low():
  # Bar tanpa high/low di-skip; bar valid berikutnya yang menentukan.
  bars = [
      make_bar(1, high=None, low=None),
      make_bar(2, high=102, low=100),
  ]
  res = resolve_trade("long", Decimal("100"), Decimal("99"), Decimal("102"), T0, bars)

  assert res.status == "win"
  assert res.closed_at == _t(2)


# ===================== compute_levels (ATR mode) =====================


def test_compute_levels_atr_long():
  bar = make_bar(1, close=100, atr=2)
  entry, sl, tp = compute_levels(bar, "long", False, Decimal("1.5"), Decimal("2"))

  # offset = atr*sl_atr = 3 ; sl = entry-3 ; tp = entry + 3*2
  assert entry == Decimal("100")
  assert sl == Decimal("97")
  assert tp == Decimal("106")


def test_compute_levels_atr_short():
  bar = make_bar(1, close=100, atr=2)
  entry, sl, tp = compute_levels(bar, "short", False, Decimal("1.5"), Decimal("2"))

  assert entry == Decimal("100")
  assert sl == Decimal("103")
  assert tp == Decimal("94")


def test_compute_levels_atr_missing_atr_returns_none():
  bar = make_bar(1, close=100, atr=None)
  assert compute_levels(bar, "long", False, Decimal("1.5"), Decimal("2")) is None


def test_compute_levels_atr_zero_atr_returns_none():
  bar = make_bar(1, close=100, atr=0)
  assert compute_levels(bar, "long", False, Decimal("1.5"), Decimal("2")) is None


def test_compute_levels_missing_close_returns_none():
  bar = make_bar(1, close=None, atr=2)
  assert compute_levels(bar, "long", False, Decimal("1.5"), Decimal("2")) is None


# ===================== compute_levels (swing mode) =====================


def test_compute_levels_swing_long():
  bar = make_bar(1, close=100, swing_low=98)
  entry, sl, tp = compute_levels(bar, "long", True, Decimal("1.5"), Decimal("2"))

  # risk = entry - swing_low = 2 ; tp = entry + risk*rr = 104
  assert entry == Decimal("100")
  assert sl == Decimal("98")
  assert tp == Decimal("104")


def test_compute_levels_swing_short():
  bar = make_bar(1, close=100, swing_high=103)
  entry, sl, tp = compute_levels(bar, "short", True, Decimal("1.5"), Decimal("2"))

  # risk = swing_high - entry = 3 ; tp = entry - risk*rr = 94
  assert entry == Decimal("100")
  assert sl == Decimal("103")
  assert tp == Decimal("94")


def test_compute_levels_swing_long_missing_swing_low_returns_none():
  bar = make_bar(1, close=100, swing_low=None)
  assert compute_levels(bar, "long", True, Decimal("1.5"), Decimal("2")) is None


def test_compute_levels_swing_long_invalid_swing_level_returns_none():
  # swing_low >= entry → tak masuk akal untuk long → None.
  bar = make_bar(1, close=100, swing_low=100)
  assert compute_levels(bar, "long", True, Decimal("1.5"), Decimal("2")) is None


def test_compute_levels_swing_short_missing_swing_high_returns_none():
  bar = make_bar(1, close=100, swing_high=None)
  assert compute_levels(bar, "short", True, Decimal("1.5"), Decimal("2")) is None


def test_compute_levels_swing_short_invalid_swing_level_returns_none():
  # swing_high <= entry → tak masuk akal untuk short → None.
  bar = make_bar(1, close=100, swing_high=100)
  assert compute_levels(bar, "short", True, Decimal("1.5"), Decimal("2")) is None


# ===================== resolve_direction =====================


def test_resolve_direction_auto_bullish_is_long():
  assert resolve_direction(make_bar(1, structure_trend="bullish"), "auto") == "long"


def test_resolve_direction_auto_bearish_is_short():
  assert resolve_direction(make_bar(1, structure_trend="bearish"), "auto") == "short"


def test_resolve_direction_auto_neutral_is_none():
  assert resolve_direction(make_bar(1, structure_trend="neutral"), "auto") is None


def test_resolve_direction_auto_empty_is_none():
  assert resolve_direction(make_bar(1, structure_trend=None), "auto") is None


def test_resolve_direction_override_long_forces_long():
  # Override memaksa arah meski struktur bearish.
  assert resolve_direction(make_bar(1, structure_trend="bearish"), "long") == "long"


def test_resolve_direction_override_short_forces_short():
  assert resolve_direction(make_bar(1, structure_trend="bullish"), "short") == "short"


# ===================== generate_trades =====================


def _params(**overrides) -> EntryParams:
  base = dict(direction_override="auto", qualifying_triggers=None, use_swing=False,
              sl_atr=Decimal("1.5"), rr=Decimal("2"), allow_overlap=False)
  base.update(overrides)
  return EntryParams(**base)


def test_generate_trades_no_pyramiding_blocks_while_open():
  # Tiga bar bullish yang trade-nya tak pernah resolve (high/low selalu di dalam SL/TP).
  # Tanpa overlap: hanya bar pertama yang membuka trade, sisanya skip 'overlap'.
  bars = [
      make_bar(1, close=100, atr=2, high=100.5, low=99.5, triggers=["x"], structure_trend="bullish"),
      make_bar(2, close=100, atr=2, high=100.6, low=99.6, triggers=["x"], structure_trend="bullish"),
      make_bar(3, close=100, atr=2, high=100.4, low=99.4, triggers=["x"], structure_trend="bullish"),
  ]
  trades, skipped = generate_trades(bars, _params(allow_overlap=False))

  assert len(trades) == 1
  assert skipped["overlap"] == 2


def test_generate_trades_allow_overlap_lifts_pyramiding_block():
  bars = [
      make_bar(1, close=100, atr=2, high=100.5, low=99.5, triggers=["x"], structure_trend="bullish"),
      make_bar(2, close=100, atr=2, high=100.6, low=99.6, triggers=["x"], structure_trend="bullish"),
      make_bar(3, close=100, atr=2, high=100.4, low=99.4, triggers=["x"], structure_trend="bullish"),
  ]
  trades, skipped = generate_trades(bars, _params(allow_overlap=True))

  assert len(trades) == 3
  assert skipped["overlap"] == 0


def test_generate_trades_trigger_filter_excludes_non_qualifying():
  # qualifying = {"a"} → bar bertrigger ["x"] di-skip 'trigger_filter', ["a"] lolos.
  bars = [
      make_bar(1, close=100, atr=2, high=100.5, low=99.5, triggers=["x"], structure_trend="bullish"),
      make_bar(2, close=100, atr=2, high=100.6, low=99.6, triggers=["a"], structure_trend="bullish"),
  ]
  trades, skipped = generate_trades(
      bars, _params(qualifying_triggers={"a"}, allow_overlap=True))

  assert len(trades) == 1
  assert skipped["trigger_filter"] == 1


def test_generate_trades_skip_reason_counts():
  # Satu bar untuk tiap alasan skip + satu bar valid.
  bars = [
      make_bar(1, close=100, atr=2, high=100.5, low=99.5, triggers=[], structure_trend="bullish"),        # no_trigger
      make_bar(2, close=100, atr=2, high=100.5, low=99.5, triggers=["x"], structure_trend="neutral"),     # no_direction
      make_bar(3, close=100, atr=None, high=100.5, low=99.5, triggers=["x"], structure_trend="bullish"),  # bad_levels (atr None)
      make_bar(4, close=100, atr=2, high=100.5, low=99.5, triggers=["x"], structure_trend="bullish"),     # valid
  ]
  trades, skipped = generate_trades(bars, _params(allow_overlap=True))

  assert len(trades) == 1
  assert skipped["no_trigger"] == 1
  assert skipped["no_direction"] == 1
  assert skipped["bad_levels"] == 1
  assert skipped["trigger_filter"] == 0
  assert skipped["overlap"] == 0


# ===================== build_summary =====================


_DUMMY_BAR = make_bar(0, close=100)


def _trade(status: str, r_multiple) -> GeneratedTrade:
  res = Resolution(
      status=status,
      exit_price=None,
      r_multiple=(Decimal(str(r_multiple)) if r_multiple is not None else None),
      closed_at=(None if status == "open" else _t(1)),
  )
  return GeneratedTrade(bar=_DUMMY_BAR, direction="long", entry=Decimal("100"),
                        stop_loss=Decimal("99"), take_profit=Decimal("102"),
                        resolution=res)


def test_build_summary_hand_computed_numbers():
  # win, win, loss, loss, loss, open → generated 6, resolved 5.
  trades = [
      _trade("win", 2), _trade("win", 2),
      _trade("loss", -1), _trade("loss", -1), _trade("loss", -1),
      _trade("open", None),
  ]
  summary = build_summary(trades)

  assert summary["generated"] == 6
  assert summary["wins"] == 2
  assert summary["losses"] == 3
  assert summary["opens"] == 1
  assert summary["resolved"] == 5
  # total_r = 2+2-1-1-1 = 1
  assert summary["total_r"] == Decimal(1)
  # win_rate = wins/resolved*100 = 2/5*100 = 40
  assert summary["win_rate"] == Decimal(40)
  # avg_r = total_r/resolved = 1/5
  assert summary["avg_r"] == Decimal(1) / Decimal(5)
  # expectancy = total_r/generated = 1/6 (open dihitung 0R lewat pembagi 'generated')
  assert summary["expectancy"] == Decimal(1) / Decimal(6)
  # Urutan: win,win,loss,loss,loss,open → beruntun loss = 3
  assert summary["max_consecutive_losses"] == 3


def test_build_summary_empty_trades_all_zero():
  summary = build_summary([])

  assert summary["generated"] == 0
  assert summary["resolved"] == 0
  assert summary["win_rate"] == Decimal(0)
  assert summary["total_r"] == Decimal(0)
  assert summary["avg_r"] == Decimal(0)
  assert summary["expectancy"] == Decimal(0)
  assert summary["max_consecutive_losses"] == 0


def test_build_summary_max_consecutive_losses_resets_on_win():
  # loss, loss, win, loss → beruntun maksimum 2 (win mematahkan streak).
  trades = [_trade("loss", -1), _trade("loss", -1), _trade("win", 2), _trade("loss", -1)]
  summary = build_summary(trades)

  assert summary["max_consecutive_losses"] == 2


def test_build_summary_open_does_not_break_loss_streak():
  # loss, open, loss → open tak menambah & tak memutus streak → beruntun 2.
  trades = [_trade("loss", -1), _trade("open", None), _trade("loss", -1)]
  summary = build_summary(trades)

  assert summary["max_consecutive_losses"] == 2
