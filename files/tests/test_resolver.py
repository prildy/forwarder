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


# --- M2: biaya trading dan field hasil ---

def test_cost_zero_r_equals_gross_r():
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("102"),
                [_bar(1, high=102, low=100)])
  assert res.r_multiple == res.gross_r == Decimal("2")


def test_long_tp_with_cost():
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"),
                [_bar(1, high=104, low=100)], cost=Decimal("0.4"))
  assert res.status == "win"
  assert res.gross_r == Decimal("2")
  assert res.r_multiple == Decimal("1.8")
  assert res.exit_reason == "tp"


def test_long_sl_with_cost():
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"),
                [_bar(1, high=101, low=98)], cost=Decimal("0.4"))
  assert res.status == "loss"
  assert res.gross_r == Decimal("-1")
  assert res.r_multiple == Decimal("-1.2")
  assert res.exit_reason == "sl"


def test_short_mirror_with_cost():
  tp = resolve("short", Decimal("100"), Decimal("102"), Decimal("96"),
               [_bar(1, high=100, low=96)], cost=Decimal("0.4"))
  assert (tp.gross_r, tp.r_multiple, tp.exit_reason) == (Decimal("2"), Decimal("1.8"), "tp")
  sl = resolve("short", Decimal("100"), Decimal("102"), Decimal("96"),
               [_bar(1, high=102, low=99)], cost=Decimal("0.4"))
  assert (sl.gross_r, sl.r_multiple, sl.exit_reason) == (Decimal("-1"), Decimal("-1.2"), "sl")


def test_tp_touch_stays_win_even_if_cost_makes_r_negative():
  res = resolve("long", Decimal("100"), Decimal("99"), Decimal("100.5"),
                [_bar(1, high=101, low=100)], cost=Decimal("1"))
  assert res.status == "win"
  assert res.r_multiple < 0


def test_negative_cost_raises():
  with pytest.raises(ValueError):
    resolve("long", Decimal("100"), Decimal("99"), Decimal("102"), [], cost=Decimal("-0.1"))


def test_exit_reason_none_when_open():
  assert resolver.OPEN.exit_reason is None
  assert resolver.OPEN.gross_r is None and resolver.OPEN.filled_at is None


def test_pricebar_close_defaults_to_none():
  assert _bar(1, high=1, low=1).close is None


@pytest.mark.parametrize("r,expected", [
  (Decimal("0.049"), "breakeven"),
  (Decimal("-0.049"), "breakeven"),
  (Decimal("0"), "breakeven"),
  (Decimal("0.05"), "win"),
  (Decimal("-0.05"), "loss"),
  (Decimal("2"), "win"),
  (Decimal("-1"), "loss"),
])
def test_classify_r_boundaries(r, expected):
  assert resolver.classify_r(r) == expected


# --- M3: model fill entry ---

def test_fill_on_bar2_then_tp_on_bar3_long():
  bars = [_bar(1, high=99.5, low=99), _bar(2, high=100.5, low=99.5),
          _bar(3, high=102, low=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True)
  assert res.status == "win"
  assert res.filled_at == T0 + timedelta(minutes=2)
  assert res.closed_at == T0 + timedelta(minutes=3)


def test_fill_on_bar2_then_tp_on_bar3_short():
  bars = [_bar(1, high=101, low=100.5), _bar(2, high=100.5, low=99.5),
          _bar(3, high=100, low=98)]
  res = resolve("short", Decimal("100"), Decimal("102"), Decimal("98"), bars,
                require_fill=True)
  assert res.status == "win"
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_fill_bar_also_touches_sl_is_loss_long():
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"),
                [_bar(1, high=101, low=97.5)], require_fill=True)
  assert res.status == "loss"
  assert res.exit_reason == "sl"
  assert res.filled_at == T0 + timedelta(minutes=1)


def test_fill_bar_also_touches_sl_is_loss_short():
  res = resolve("short", Decimal("100"), Decimal("102"), Decimal("98"),
                [_bar(1, high=102.5, low=99)], require_fill=True)
  assert res.status == "loss"
  assert res.filled_at == T0 + timedelta(minutes=1)


def test_fill_bar_touching_only_tp_stays_open_long():
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"),
                [_bar(1, high=103, low=99.5)], require_fill=True)
  assert res.is_open
  assert res.status == "open"
  assert res.filled_at == T0 + timedelta(minutes=1)
  assert res.r_multiple is None and res.exit_price is None


def test_fill_bar_touching_only_tp_stays_open_short():
  res = resolve("short", Decimal("100"), Decimal("102"), Decimal("98"),
                [_bar(1, high=100.5, low=97)], require_fill=True)
  assert res.is_open
  assert res.filled_at == T0 + timedelta(minutes=1)


def test_tp_on_bar_after_fill_bar_counts():
  bars = [_bar(1, high=103, low=99.5), _bar(2, high=103, low=100.5)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True)
  assert res.status == "win"
  assert res.closed_at == T0 + timedelta(minutes=2)
  assert res.filled_at == T0 + timedelta(minutes=1)


def test_tie_after_fill_is_loss():
  bars = [_bar(1, high=100.5, low=99.5), _bar(2, high=103, low=97)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True)
  assert res.status == "loss"
  assert res.filled_at == T0 + timedelta(minutes=1)


def test_never_filled_within_max_fill_bars_is_skipped():
  bars = [_bar(i, high=105, low=104) for i in range(1, 6)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True, max_fill_bars=3)
  assert res.status == "skipped"
  assert res.exit_reason == "no_fill"
  assert res.closed_at == T0 + timedelta(minutes=3)
  assert res.exit_price is None and res.r_multiple is None
  assert not res.is_open


def test_fill_on_last_allowed_bar_is_not_skipped():
  bars = [_bar(1, high=105, low=104), _bar(2, high=105, low=104),
          _bar(3, high=101, low=99.5)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True, max_fill_bars=3)
  assert res.status == "open"
  assert res.filled_at == T0 + timedelta(minutes=3)


def test_gap_down_across_entry_fills_long():
  # bar1 seluruhnya di atas entry, bar2 seluruhnya di bawah → entry terlewati.
  bars = [_bar(1, high=102, low=101), _bar(2, high=99.5, low=99)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"), bars,
                require_fill=True)
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_gap_up_across_entry_fills_short():
  bars = [_bar(1, high=99, low=98.5), _bar(2, high=101.5, low=101)]
  res = resolve("short", Decimal("100"), Decimal("103"), Decimal("97"), bars,
                require_fill=True)
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_gap_fill_bar_that_hits_stop_is_loss():
  bars = [_bar(1, high=102, low=101), _bar(2, high=99.5, low=97)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"), bars,
                require_fill=True)
  assert res.status == "loss"
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_none_bars_not_counted_for_fill_limit():
  bars = [_bar(1, high=105, low=104), _bar(2), _bar(3, high=105, low=104),
          _bar(4), _bar(5, high=105, low=104)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), bars,
                require_fill=True, max_fill_bars=3)
  assert res.status == "skipped"
  assert res.closed_at == T0 + timedelta(minutes=5)


def test_none_bar_does_not_break_gap_detection():
  bars = [_bar(1, high=102, low=101), _bar(2), _bar(3, high=99.5, low=99)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"), bars,
                require_fill=True)
  assert res.filled_at == T0 + timedelta(minutes=3)


def test_require_fill_no_bars_returns_open_sentinel():
  assert resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), [],
                 require_fill=True) is resolver.OPEN


def test_require_fill_never_touched_no_max_returns_open_sentinel():
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("102"),
                [_bar(1, high=105, low=104)], require_fill=True)
  assert res is resolver.OPEN


def test_max_fill_bars_without_require_fill_raises():
  # Diubah dari "diabaikan diam-diam" menjadi ValueError (perbaikan review).
  bars = [_bar(i, high=105, low=104) for i in range(1, 6)]
  with pytest.raises(ValueError):
    resolve("long", Decimal("100"), Decimal("98"), Decimal("104.5"), bars,
            max_fill_bars=2)


def test_fill_with_cost_closed_result_carries_filled_at_and_net_r():
  bars = [_bar(1, high=100.5, low=99.5), _bar(2, high=104, low=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"), bars,
                cost=Decimal("0.4"), require_fill=True)
  assert res.gross_r == Decimal("2")
  assert res.r_multiple == Decimal("1.8")
  assert res.filled_at == T0 + timedelta(minutes=1)


# --- M4: batas waktu tahan posisi ---

def _cbar(minutes: int, *, high, low, close=None) -> PriceBar:
  def dec(value):
    return Decimal(str(value)) if value is not None else None

  return PriceBar(bar_time=T0 + timedelta(minutes=minutes), high=dec(high),
                  low=dec(low), close=dec(close))


def test_timeout_in_profit_is_win_long():
  bars = [_cbar(1, high=100.5, low=99.5, close=100), _cbar(2, high=101, low=100, close=101)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=2)
  assert res.status == "win"
  assert res.exit_reason == "timeout"
  assert res.exit_price == Decimal("101")
  assert res.gross_r == Decimal("0.5")
  assert res.closed_at == T0 + timedelta(minutes=2)


def test_timeout_in_loss_is_loss_short():
  bars = [_cbar(1, high=101, low=99.5, close=101)]
  res = resolve("short", Decimal("100"), Decimal("104"), Decimal("90"), bars,
                max_hold_bars=1)
  assert res.status == "loss"
  assert res.r_multiple == Decimal("-0.25")
  assert res.exit_reason == "timeout"


def test_timeout_near_zero_is_breakeven():
  bars = [_cbar(1, high=100.5, low=99.5, close=100.05)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=1)
  assert res.status == "breakeven"
  assert res.exit_reason == "timeout"


def test_timeout_cost_can_turn_small_win_into_loss():
  bars = [_cbar(1, high=101, low=99.5, close=100.5)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                cost=Decimal("1"), max_hold_bars=1)
  assert res.gross_r == Decimal("0.25")
  assert res.r_multiple == Decimal("-0.25")
  assert res.status == "loss"


def test_sl_touch_on_timeout_bar_wins_over_timeout():
  bars = [_cbar(1, high=100.5, low=99.5, close=100), _cbar(2, high=100.5, low=97, close=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=2)
  assert res.status == "loss"
  assert res.exit_reason == "sl"


def test_tp_touch_on_timeout_bar_wins_over_timeout():
  bars = [_cbar(1, high=100.5, low=99.5, close=100), _cbar(2, high=110, low=100, close=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=2)
  assert res.exit_reason == "tp"


def test_close_none_defers_timeout_to_next_bar_with_close():
  bars = [_cbar(1, high=100.5, low=99.5, close=None),
          _cbar(2, high=100.5, low=99.5, close=None),
          _cbar(3, high=101, low=99.5, close=100.8)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=1)
  assert res.exit_reason == "timeout"
  assert res.closed_at == T0 + timedelta(minutes=3)
  assert res.exit_price == Decimal("100.8")


def test_deferred_timeout_still_checks_sl_on_later_bars():
  bars = [_cbar(1, high=100.5, low=99.5, close=None),
          _cbar(2, high=100.5, low=97, close=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=1)
  assert res.exit_reason == "sl"


def test_duck_typed_bar_without_close_never_times_out():
  from types import SimpleNamespace
  bars = [SimpleNamespace(bar_time=T0 + timedelta(minutes=i), high=Decimal("100.5"),
                          low=Decimal("99.5")) for i in range(1, 4)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=1)
  assert res is resolver.OPEN


def test_max_hold_bars_none_keeps_old_behaviour():
  bars = [_cbar(i, high=100.5, low=99.5, close=100) for i in range(1, 50)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars)
  assert res is resolver.OPEN


def test_not_yet_at_max_hold_stays_open():
  bars = [_cbar(i, high=100.5, low=99.5, close=100) for i in range(1, 3)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=3)
  assert res is resolver.OPEN


def test_none_bars_not_counted_for_hold():
  bars = [_cbar(1, high=100.5, low=99.5, close=100), _cbar(2, high=None, low=None, close=100),
          _cbar(3, high=100.5, low=99.5, close=100.4)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=2)
  assert res.closed_at == T0 + timedelta(minutes=3)


def test_hold_count_starts_at_first_bar_without_fill_model():
  bars = [_cbar(1, high=100.5, low=99.5, close=100.2)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                max_hold_bars=1)
  assert res.exit_reason == "timeout"
  assert res.filled_at is None


# --- M3 x M4: hold dihitung mulai bar fill ---

def test_hold_counting_starts_at_fill_bar_not_first_bar():
  # bar 1-2 menunggu fill (tidak dihitung hold); fill di bar 3 (=hold 1), bar 4 = hold 2.
  bars = [_cbar(1, high=105, low=104, close=104.5), _cbar(2, high=105, low=104, close=104.5),
          _cbar(3, high=100.5, low=99.5, close=100.2), _cbar(4, high=100.8, low=99.8, close=100.6)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_hold_bars=2)
  assert res.exit_reason == "timeout"
  assert res.closed_at == T0 + timedelta(minutes=4)
  assert res.filled_at == T0 + timedelta(minutes=3)
  assert res.exit_price == Decimal("100.6")


def test_not_timed_out_before_hold_reached_after_fill():
  bars = [_cbar(1, high=105, low=104, close=104.5), _cbar(2, high=100.5, low=99.5, close=100.2),
          _cbar(3, high=100.8, low=99.8, close=100.6)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_hold_bars=3)
  assert res.is_open
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_max_hold_one_times_out_on_fill_bar_at_close():
  bars = [_cbar(1, high=100.5, low=99.5, close=100.3)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_hold_bars=1)
  assert res.exit_reason == "timeout"
  assert res.filled_at == res.closed_at == T0 + timedelta(minutes=1)


def test_fill_bar_tp_touch_not_credited_then_timeout_at_close():
  # TP tersentuh di bar fill tidak dikreditkan; max_hold=1 → keluar di close bar fill.
  bars = [_cbar(1, high=111, low=99.5, close=100.5)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_hold_bars=1)
  assert res.exit_reason == "timeout"
  assert res.exit_price == Decimal("100.5")


def test_fill_bar_sl_touch_beats_timeout_on_fill_bar():
  bars = [_cbar(1, high=100.5, low=97, close=100)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_hold_bars=1)
  assert res.exit_reason == "sl"


def test_no_fill_skips_even_with_max_hold_set():
  bars = [_cbar(i, high=105, low=104, close=104.5) for i in range(1, 4)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                require_fill=True, max_fill_bars=2, max_hold_bars=1)
  assert res.status == "skipped"
  assert res.exit_reason == "no_fill"


def test_timeout_after_fill_carries_cost_and_filled_at():
  bars = [_cbar(1, high=100.5, low=99.5, close=100.2), _cbar(2, high=101.5, low=100, close=101)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("110"), bars,
                cost=Decimal("0.4"), require_fill=True, max_hold_bars=2)
  assert res.gross_r == Decimal("0.5")
  assert res.r_multiple == Decimal("0.3")
  assert res.status == "win"
  assert res.filled_at == T0 + timedelta(minutes=1)


# --- perbaikan review: validasi parameter, risk terbalik, keterbatasan gap ---

@pytest.mark.parametrize("kwargs", [
  {"max_hold_bars": 0},
  {"max_hold_bars": -1},
  {"require_fill": True, "max_fill_bars": 0},
  {"require_fill": True, "max_fill_bars": -2},
])
def test_invalid_bar_limits_raise(kwargs):
  with pytest.raises(ValueError):
    resolve("long", Decimal("100"), Decimal("98"), Decimal("102"), [], **kwargs)


def test_inverted_levels_raise_long_and_short():
  with pytest.raises(ValueError):
    resolve("long", Decimal("100"), Decimal("101"), Decimal("102"), [])
  with pytest.raises(ValueError):
    resolve("short", Decimal("100"), Decimal("99"), Decimal("98"), [])


def test_gap_fill_is_booked_at_entry_and_stop_breach_is_loss():
  # Perilaku terdokumentasi: fill gap dianggap di `entry`; bar fill yang menembus SL = LOSS
  # dengan exit di level stop (R = -1, optimistis kalau harga sebenarnya melompati SL).
  bars = [_bar(1, high=102, low=101), _bar(2, high=97.5, low=97)]
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"), bars,
                require_fill=True)
  assert res.status == "loss"
  assert res.exit_price == Decimal("98")
  assert res.gross_r == Decimal("-1")
  assert res.filled_at == T0 + timedelta(minutes=2)


def test_gap_on_first_counted_bar_is_not_detected():
  # Keterbatasan terdokumentasi: bar pertama tak punya bar sebelumnya, jadi bar yang
  # seluruhnya di bawah entry (long limit) tidak dianggap fill.
  res = resolve("long", Decimal("100"), Decimal("98"), Decimal("104"),
                [_bar(1, high=99.5, low=99)], require_fill=True)
  assert res is resolver.OPEN


def test_resolver_classify_r_agrees_with_main_classify_r():
  import main
  for value in ["-0.05", "-0.0499", "0", "0.0499", "0.05", "1", "-1"]:
    assert resolver.classify_r(Decimal(value)) == main.classify_r(float(value)), value
