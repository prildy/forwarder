"""Unit test langsung untuk resolver.py — modul resolusi SL/TP bersama.

Menegaskan semantik inti (win/loss per arah, tie-break worst-case = loss, first-touch,
guard risk nol, skip bar tanpa high/low, rumus R) tanpa lewat wrapper backtest.
Semua in-memory, tanpa DB/jaringan.
"""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

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


# --- Tambahan: short, boundary, edge case, dan kontrak immutability ---


def test_resolve_short_loss_hits_stop_loss():
  # Short: high >= sl → LOSS di stop_loss, R = -1.
  res = resolve("short", Decimal("100"), Decimal("101"), Decimal("98"),
                [_bar(1, high=101, low=99)])

  assert res.status == "loss"
  assert res.exit_price == Decimal("101")
  assert res.r_multiple == Decimal(-1)
  assert res.closed_at == T0 + timedelta(minutes=1)


def test_resolve_short_both_touch_tie_break_is_loss():
  # Short: low <= tp DAN high >= sl dalam satu bar → LOSS (worst-case).
  res = resolve("short", Decimal("100"), Decimal("101"), Decimal("98"),
                [_bar(1, high=102, low=97)])

  assert res.status == "loss"
  assert res.exit_price == Decimal("101")
  assert res.r_multiple == Decimal(-1)


@pytest.mark.parametrize(
  "direction, entry, sl, tp, high, low, status, exit_price",
  [
    # Kesamaan persis tepat di level harus dihitung sebagai sentuh (>= / <=).
    ("long", "100", "99", "102", 102, 100, "win", "102"),
    ("long", "100", "99", "102", 100.5, 99, "loss", "99"),
    ("short", "100", "101", "98", 100.5, 98, "win", "98"),
    ("short", "100", "101", "98", 101, 99, "loss", "101"),
  ],
  ids=["long-tp", "long-sl", "short-tp", "short-sl"],
)
def test_resolve_exact_equality_touches_level(direction, entry, sl, tp, high, low,
                                              status, exit_price):
  res = resolve(direction, Decimal(entry), Decimal(sl), Decimal(tp),
                [_bar(1, high=high, low=low)])

  assert res.status == status
  assert res.exit_price == Decimal(exit_price)


def test_resolve_bar_with_only_high_none_is_skipped():
  # low=0 akan menyentuh SL kalau tidak di-skip; bar harus dilewati tanpa error.
  bars = [_bar(1, high=None, low=0), _bar(2, high=102, low=100)]
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), bars)

  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=2)


def test_resolve_bar_with_only_low_none_is_skipped():
  # high=200 akan menyentuh TP kalau tidak di-skip; bar harus dilewati tanpa error.
  bars = [_bar(1, high=200, low=None), _bar(2, high=100.5, low=99)]
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), bars)

  assert res.status == "loss"
  assert res.closed_at == T0 + timedelta(minutes=2)


def test_resolve_short_zero_risk_stays_open():
  # Short dengan entry == stop_loss → risk nol → open, identik dengan sentinel.
  res = resolve("short", Decimal("100"), Decimal("100"), Decimal("98"),
                [_bar(1, high=200, low=0)])

  assert res is resolver.OPEN


def test_resolve_fractional_r_is_exact_decimal():
  # Reward 1 / risk 3 → tepat Decimal(1)/Decimal(3), tanpa float.
  win = resolve("long", Decimal("100"), Decimal("97"), Decimal("101"),
                [_bar(1, high=101, low=100)])
  assert win.r_multiple == Decimal(1) / Decimal(3)
  assert isinstance(win.r_multiple, Decimal)

  # R pecahan sederhana: reward 0.5 / risk 1 = 0.5.
  half = resolve("long", Decimal("100"), Decimal("99"), Decimal("100.5"),
                 [_bar(1, high=100.5, low=100)])
  assert half.r_multiple == Decimal("0.5")


def test_resolve_stops_consuming_generator_after_first_touch():
  consumed = []

  def gen():
    for minute, high, low in [(1, 101, 99.5), (2, 103, 101), (3, 200, 0), (4, 200, 0)]:
      consumed.append(minute)
      yield _bar(minute, high=high, low=low)

  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), gen())

  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=2)
  # Bar 3 dan 4 tidak boleh diambil dari generator setelah sentuhan pertama.
  assert consumed == [1, 2]


def test_resolve_accepts_duck_typed_bar():
  # Kontrak PriceBarLike: cukup atribut bar_time/high/low, bukan kelas PriceBar.
  bar = SimpleNamespace(bar_time=T0 + timedelta(minutes=5),
                        high=Decimal("102"), low=Decimal("100"))
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), [bar])

  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=5)


def test_dataclasses_are_frozen():
  bar = _bar(1, high=101, low=99)
  with pytest.raises(FrozenInstanceError):
    bar.high = Decimal("0")

  with pytest.raises(FrozenInstanceError):
    resolver.OPEN.status = "win"


def test_open_paths_return_shared_sentinel_by_identity():
  # Zero-risk, tanpa bar, dan tak ada sentuhan → semuanya objek OPEN yang sama.
  zero_risk = resolve("long", Decimal("100"), Decimal("100"), Decimal("102"), [])
  no_bars = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), [])
  no_touch = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                     [_bar(1, high=101, low=99.5)])

  assert zero_risk is resolver.OPEN
  assert no_bars is resolver.OPEN
  assert no_touch is resolver.OPEN


def test_resolve_touch_after_neutral_bars_has_later_closed_at():
  bars = [
    _bar(1, high=101, low=99.5),
    _bar(2, high=100.8, low=99.8),
    _bar(3, high=101.5, low=100),
    _bar(7, high=102, low=101),
  ]
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), bars)

  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=7)
