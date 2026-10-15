"""Unit test langsung untuk resolver.py — modul resolusi SL/TP bersama.

Menegaskan semantik inti (win/loss per arah, tie-break worst-case = loss, first-touch,
guard risk nol, skip bar tanpa high/low, rumus R) tanpa lewat wrapper backtest.
Semua in-memory, tanpa DB/jaringan.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import resolver
from resolver import PriceBar, resolve

T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def _bar(minutes: int, *, high=None, low=None) -> PriceBar:
  def dec(value):
    return Decimal(str(value)) if value is not None else None

  return PriceBar(bar_time=T0 + timedelta(minutes=minutes), high=dec(high), low=dec(low))


def test_resolve_long_win_hits_take_profit():
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                [_bar(1, high=102, low=100)])

  assert res.status == "win"
  assert res.exit_price == Decimal("102")
  assert res.r_multiple == Decimal(2)
  assert res.closed_at == T0 + timedelta(minutes=1)
  assert res.is_open is False


def test_resolve_long_loss_hits_stop_loss():
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                [_bar(1, high=100.5, low=99)])

  assert res.status == "loss"
  assert res.exit_price == Decimal("99")
  assert res.r_multiple == Decimal(-1)


def test_resolve_short_win_hits_take_profit():
  res = resolve("short", Decimal("100"), Decimal("101"), Decimal("98"),
                [_bar(1, high=100.5, low=98)])

  assert res.status == "win"
  assert res.exit_price == Decimal("98")
  assert res.r_multiple == Decimal(2)


def test_resolve_both_touch_tie_break_is_loss():
  # Satu bar menyentuh SL dan TP sekaligus → LOSS di stop_loss (worst-case).
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                [_bar(1, high=103, low=98)])

  assert res.status == "loss"
  assert res.exit_price == Decimal("99")


def test_resolve_first_touching_bar_decides():
  bars = [_bar(1, high=100.5, low=99), _bar(2, high=103, low=101)]
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), bars)

  assert res.status == "loss"
  assert res.closed_at == T0 + timedelta(minutes=1)


def test_resolve_no_touching_bar_stays_open():
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                [_bar(1, high=101, low=99.5)])

  assert res.is_open is True
  assert res.status == "open"
  assert res.exit_price is None
  assert res.r_multiple is None
  assert res.closed_at is None


def test_resolve_zero_risk_stays_open_without_scanning():
  # entry == stop_loss → risk nol → open tanpa menelusuri bar (meski bar menyentuh).
  res = resolve("long", Decimal("100"), Decimal("100"), Decimal("102"),
                [_bar(1, high=200, low=0)])

  assert res.is_open is True


def test_resolve_skips_bars_with_missing_high_low():
  bars = [_bar(1, high=None, low=None), _bar(2, high=102, low=100)]
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), bars)

  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=2)


def test_resolve_empty_bars_stays_open():
  assert resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), []).is_open is True


def test_open_sentinel_is_resolution():
  assert isinstance(resolver.OPEN, resolver.Resolution)
  assert resolver.OPEN.is_open is True
