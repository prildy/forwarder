"""Logika resolusi trade murni — TANPA env var, TANPA DB, TANPA FastAPI.

Modul ini satu-satunya sumber kebenaran untuk aturan SL/TP. Dipakai bersama oleh
resolver live (main.resolve_open_trades) dan backtest (backtest.resolve_trade) supaya
semantik resolusi tidak bisa menyimpang antara live dan backtest. Karena bebas efek
samping (tak baca env, tak buka koneksi, tak bikin app), modul ini aman di-import oleh
main.py, backtest.py, maupun test.

Semantik yang dijaga identik dengan perilaku lama kedua resolver:
- aturan sentuh SL/TP per arah (long: high>=tp / low<=sl; short: low<=tp / high>=sl),
- tie-break worst-case intrabar: satu bar menyentuh SL dan TP sekaligus → LOSS di stop_loss,
- bar PERTAMA yang menyentuh level menentukan hasil,
- guard risk nol (entry == stop_loss) → tetap open tanpa menelusuri bar,
- rumus R (long: reward = exit - entry, risk = entry - sl; short cerminannya; r = reward/risk),
- semua perhitungan dalam Decimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, Optional, Protocol


class PriceBarLike(Protocol):
  """Kontrak minimal bar yang dibutuhkan resolver: high/low + waktu bar.

  Baik `backtest.Bar` maupun `resolver.PriceBar` memenuhi kontrak ini (duck typing).
  """

  bar_time: datetime
  high: Optional[Decimal]
  low: Optional[Decimal]


@dataclass(frozen=True)
class PriceBar:
  """Bar harga minimal untuk resolver — dipakai resolver live dari baris SQL mentah."""

  bar_time: datetime
  high: Optional[Decimal]
  low: Optional[Decimal]


@dataclass(frozen=True)
class Resolution:
  """Hasil resolusi satu trade. closed_at None → masih open (tak ada bar yang menyentuh)."""

  status: str                       # 'win' | 'loss' | 'open'
  exit_price: Optional[Decimal]
  r_multiple: Optional[Decimal]
  closed_at: Optional[datetime]

  @property
  def is_open(self) -> bool:
    return self.closed_at is None


# Sentinel immutable untuk hasil "masih open" — aman dibagi karena frozen dataclass.
OPEN = Resolution(status="open", exit_price=None, r_multiple=None, closed_at=None)


def resolve(direction: str, entry: Decimal, stop_loss: Decimal,
            take_profit: Decimal, bars: Iterable[PriceBarLike]) -> Resolution:
  """Resolusi satu trade terhadap deretan bar yang SUDAH terurut waktu naik.

  `bars` wajib hanya berisi bar SETELAH entry (pemfilteran bar_time > opened_at adalah
  tanggung jawab pemanggil: resolver live memfilter lewat SQL, backtest memfilter list
  in-memory sebelum delegasi ke sini).
  """
  # Risk dihitung dulu supaya bisa guard pembagian nol sebelum menelusuri bar.
  risk = (entry - stop_loss) if direction == "long" else (stop_loss - entry)
  if risk == 0:
    return OPEN

  for bar in bars:
    if bar.high is None or bar.low is None:
      continue

    if direction == "long":
      hit_tp = bar.high >= take_profit
      hit_sl = bar.low <= stop_loss
    else:  # short
      hit_tp = bar.low <= take_profit
      hit_sl = bar.high >= stop_loss

    if not hit_tp and not hit_sl:
      continue

    # Worst-case intrabar: kalau satu bar menyentuh SL dan TP sekaligus,
    # anggap LOSS (asumsi jujur/konservatif, bukan optimis TP duluan).
    if hit_sl:
      status, exit_price = "loss", stop_loss
    else:
      status, exit_price = "win", take_profit

    reward = (exit_price - entry) if direction == "long" else (entry - exit_price)
    r_multiple = reward / risk
    # Bar pertama yang menyentuh level menentukan hasil.
    return Resolution(status=status, exit_price=exit_price,
                      r_multiple=r_multiple, closed_at=bar.bar_time)

  # Tak ada bar yang menyentuh di history yang tersedia → tetap open.
  return OPEN
