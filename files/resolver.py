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

Tambahan opsional (default-nya tidak mengubah perilaku di atas): biaya round-trip (`cost`),
model fill entry (`require_fill`; bar fill tidak pernah mengkredit TP), batas tunggu fill
(`max_fill_bars` → status 'skipped'), dan batas tahan (`max_hold_bars` → exit timeout di
close; status bisa 'win' | 'loss' | 'breakeven' lewat classify_r). Status touch TP tetap
'win' walau biaya membuat R negatif.

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
  Atribut `close: Optional[Decimal]` bersifat OPSIONAL dan sengaja tidak dideklarasikan
  di sini supaya bar tanpa `close` tetap valid; resolver membacanya lewat
  `getattr(bar, "close", None)` (hanya dipakai untuk exit timeout `max_hold_bars`).
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
  close: Optional[Decimal] = None


@dataclass(frozen=True)
class Resolution:
  """Hasil resolusi satu trade. closed_at None → masih open (tak ada bar yang menyentuh)."""

  status: str                       # 'win' | 'loss' | 'breakeven' | 'open' | 'skipped'
  exit_price: Optional[Decimal]
  r_multiple: Optional[Decimal]
  closed_at: Optional[datetime]
  gross_r: Optional[Decimal] = None     # R sebelum biaya
  filled_at: Optional[datetime] = None  # waktu entry terisi (model fill)
  exit_reason: Optional[str] = None     # 'tp' | 'sl' | 'no_fill' | 'timeout'

  @property
  def is_open(self) -> bool:
    return self.closed_at is None


# Sentinel immutable untuk hasil "masih open" — aman dibagi karena frozen dataclass.
OPEN = Resolution(status="open", exit_price=None, r_multiple=None, closed_at=None)


def classify_r(r: Decimal) -> str:
  """Klasifikasi status dari R — ambang sama dengan main.classify_r."""
  if abs(r) < Decimal("0.05"):
    return "breakeven"
  return "win" if r > 0 else "loss"


def resolve(direction: str, entry: Decimal, stop_loss: Decimal,
            take_profit: Decimal, bars: Iterable[PriceBarLike], *,
            cost: Decimal = Decimal(0), require_fill: bool = False,
            max_fill_bars: Optional[int] = None,
            max_hold_bars: Optional[int] = None) -> Resolution:
  """Resolusi satu trade terhadap deretan bar yang SUDAH terurut waktu naik.

  `bars` wajib hanya berisi bar SETELAH entry (pemfilteran bar_time > opened_at adalah
  tanggung jawab pemanggil: resolver live memfilter lewat SQL, backtest memfilter list
  in-memory sebelum delegasi ke sini).

  `cost` = biaya round-trip dalam satuan harga (spread + slippage kedua sisi); dikurangkan
  dari R sebesar cost/risk. Status tetap ditentukan level yang tersentuh.

  `require_fill=True` → entry dianggap limit order: trade baru berjalan setelah harga
  menyentuh/melompati entry. Di bar fill hanya SL yang dicek (worst-case, TP tak pernah
  dikreditkan di bar fill). Bar tanpa high/low dilewati dan tidak dihitung.
  `max_fill_bars` → batas jumlah bar (terhitung) menunggu fill; lewat batas → 'skipped'.

  `max_hold_bars` → batas lama menahan posisi. Bar terhitung dimulai dari bar fill
  (bar fill = 1) kalau require_fill=True, selain itu dari bar terhitung pertama. Setelah
  SL/TP dievaluasi di bar ke-`max_hold_bars` tanpa sentuhan, posisi ditutup di `close`
  bar itu (exit_reason='timeout'); kalau close None, ditunda ke bar berikutnya yang
  punya close (SL/TP tetap dievaluasi lebih dulu di bar-bar itu).
  """
  if cost < 0:
    raise ValueError("cost tidak boleh negatif")
  if max_fill_bars is not None and max_fill_bars < 1:
    raise ValueError("max_fill_bars harus >= 1")
  if max_hold_bars is not None and max_hold_bars < 1:
    raise ValueError("max_hold_bars harus >= 1")
  if max_fill_bars is not None and not require_fill:
    # Tanpa model fill parameter ini tak berefek — tolak daripada diam-diam diabaikan.
    raise ValueError("max_fill_bars hanya berlaku kalau require_fill=True")
  # Risk dihitung dulu supaya bisa guard pembagian nol sebelum menelusuri bar.
  risk = (entry - stop_loss) if direction == "long" else (stop_loss - entry)
  if risk == 0:
    return OPEN
  if risk < 0:
    # Level terbalik (long dengan SL >= entry / short dengan SL <= entry): biaya/risk
    # akan berbalik tanda dan hasilnya tak bermakna → tolak.
    raise ValueError("stop_loss berada di sisi yang salah dari entry")

  filled = not require_fill
  filled_at: Optional[datetime] = None
  counted = 0   # jumlah bar terhitung (high & low ada), dipakai untuk batas fill
  prev = None   # bar terhitung sebelumnya, untuk deteksi lompatan (gap) melewati entry
  held = 0      # jumlah bar terhitung sejak posisi aktif (bar fill = 1)

  for bar in bars:
    if bar.high is None or bar.low is None:
      continue
    counted += 1
    prev_bar, prev = prev, bar
    fill_bar = False

    if not filled:
      # Keterbatasan yang disengaja: (1) fill akibat gap dianggap terjadi di `entry`,
      # padahal harga tak pernah trade di sana (optimistis kalau harga melompati SL —
      # tanpa harga open tak bisa dihitung lebih akurat); bar fill yang menembus SL
      # tetap LOSS. (2) Bar terhitung PERTAMA tak punya bar sebelumnya dan resolver tak
      # punya referensi bar sinyal, jadi gap di bar pertama tak terdeteksi (tidak terisi
      # sampai ada bar yang menyentuh entry atau gap antar-bar berikutnya).
      touched = bar.low <= entry <= bar.high
      gapped = prev_bar is not None and (
        (prev_bar.high < entry and bar.low > entry)
        or (prev_bar.low > entry and bar.high < entry))
      if touched or gapped:
        filled, fill_bar, filled_at = True, True, bar.bar_time
      else:
        if max_fill_bars is not None and counted >= max_fill_bars:
          return Resolution(status="skipped", exit_price=None, r_multiple=None,
                            closed_at=bar.bar_time, exit_reason="no_fill")
        continue

    if direction == "long":
      hit_tp = bar.high >= take_profit
      hit_sl = bar.low <= stop_loss
    else:  # short
      hit_tp = bar.low <= take_profit
      hit_sl = bar.high >= stop_loss

    # Di bar fill urutan intrabar tak diketahui → TP tak pernah dikreditkan.
    if fill_bar:
      hit_tp = False

    held += 1

    if not hit_tp and not hit_sl:
      # Timeout: tutup di close bar ini (SL/TP sudah dicek dan tidak tersentuh).
      close = getattr(bar, "close", None)
      if max_hold_bars is not None and held >= max_hold_bars and close is not None:
        reward = (close - entry) if direction == "long" else (entry - close)
        gross_r = reward / risk
        r_multiple = gross_r - (cost / risk)
        return Resolution(status=classify_r(r_multiple), exit_price=close,
                          r_multiple=r_multiple, closed_at=bar.bar_time,
                          gross_r=gross_r, filled_at=filled_at,
                          exit_reason="timeout")
      continue

    # Worst-case intrabar: kalau satu bar menyentuh SL dan TP sekaligus,
    # anggap LOSS (asumsi jujur/konservatif, bukan optimis TP duluan).
    if hit_sl:
      status, exit_price = "loss", stop_loss
    else:
      status, exit_price = "win", take_profit

    reward = (exit_price - entry) if direction == "long" else (entry - exit_price)
    gross_r = reward / risk
    r_multiple = gross_r - (cost / risk)
    # Bar pertama yang menyentuh level menentukan hasil.
    return Resolution(status=status, exit_price=exit_price,
                      r_multiple=r_multiple, closed_at=bar.bar_time,
                      gross_r=gross_r, filled_at=filled_at,
                      exit_reason="sl" if hit_sl else "tp")

  # Sudah terisi tapi belum tersentuh level → open dengan filled_at; belum terisi → OPEN.
  if filled_at is not None:
    return Resolution(status="open", exit_price=None, r_multiple=None,
                      closed_at=None, filled_at=filled_at)
  return OPEN
