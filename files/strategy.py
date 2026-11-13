"""Aturan entry mekanis (murni): trigger -> arah -> level SL/TP.

Modul ini SUMBER KEBENARAN tunggal untuk aturan entry yang dipakai backtest (dan nanti
live). Sengaja bebas env, DB, dan FastAPI — mirip `resolver.py` — jadi aman di-import
dari mana saja dan gampang dites. Semua harga/uang pakai `Decimal` (float dikonversi
lewat `Decimal(str(x))`).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Protocol


class BarLike(Protocol):
  """Bentuk minimal bar yang dibutuhkan aturan entry (backtest.Bar memenuhi ini)."""

  close: Optional[Decimal]
  atr: Optional[Decimal]
  triggers: list[str]
  structure_trend: Optional[str]
  swing_high: Optional[Decimal]
  swing_low: Optional[Decimal]


@dataclass(frozen=True)
class EntryParams:
  direction_override: str           # 'auto' | 'long' | 'short'
  qualifying_triggers: Optional[set[str]]   # None = semua bar bertrigger lolos
  use_swing: bool
  sl_atr: Decimal
  rr: Decimal
  allow_overlap: bool


@dataclass(frozen=True)
class Proposal:
  """Usulan trade mekanis: arah + level entry/SL/TP."""

  direction: str                    # 'long' | 'short'
  entry: Decimal
  stop_loss: Decimal
  take_profit: Decimal


@dataclass(frozen=True)
class PayloadBar:
  """Bar yang dibangun dari payload webhook (memenuhi BarLike)."""

  close: Optional[Decimal]
  atr: Optional[Decimal]
  triggers: list[str]
  structure_trend: Optional[str]
  swing_high: Optional[Decimal]
  swing_low: Optional[Decimal]


def resolve_direction(bar: BarLike, override: str) -> Optional[str]:
  # override 'long'/'short' memaksa arah; 'auto' baca smc.structure_trend.
  if override in ("long", "short"):
    return override

  trend = (bar.structure_trend or "").lower()
  if "bull" in trend:
    return "long"
  if "bear" in trend:
    return "short"
  # Netral / kosong / tak dikenal → tidak ada trade.
  return None


def compute_levels(bar: BarLike, direction: str, use_swing: bool,
                   sl_atr: Decimal, rr: Decimal) -> Optional[tuple[Decimal, Decimal, Decimal]]:
  """Kembalikan (entry, stop_loss, take_profit) Decimal, atau None kalau bar tak layak."""
  if bar.close is None:
    return None
  entry = bar.close

  if use_swing:
    # SL berbasis struktur: long pakai swing_low, short pakai swing_high.
    if direction == "long":
      stop_loss = bar.swing_low
      if stop_loss is None or stop_loss >= entry:
        return None
      risk = entry - stop_loss
      take_profit = entry + risk * rr
    else:
      stop_loss = bar.swing_high
      if stop_loss is None or stop_loss <= entry:
        return None
      risk = stop_loss - entry
      take_profit = entry - risk * rr
    return entry, stop_loss, take_profit

  # Default: SL/TP berbasis ATR bar tersebut.
  if bar.atr is None or bar.atr <= 0:
    return None
  offset = bar.atr * sl_atr
  if direction == "long":
    stop_loss = entry - offset
    take_profit = entry + offset * rr
  else:
    stop_loss = entry + offset
    take_profit = entry - offset * rr
  return entry, stop_loss, take_profit


def propose(bar: BarLike, params: EntryParams) -> tuple[Optional[Proposal], Optional[str]]:
  """Terapkan guard entry; kembalikan (Proposal, None) atau (None, alasan_skip).

  Urutan guard HARUS tetap: no_trigger -> trigger_filter -> no_direction -> bad_levels.
  """
  # Guard: trigger wajib non-empty.
  if not bar.triggers:
    return None, "no_trigger"

  # Guard: filter trigger qualifying (kalau di-set).
  if params.qualifying_triggers is not None:
    if not (set(bar.triggers) & params.qualifying_triggers):
      return None, "trigger_filter"

  # Guard: arah harus jelas.
  direction = resolve_direction(bar, params.direction_override)
  if direction is None:
    return None, "no_direction"

  # Guard: level entry/SL/TP harus valid.
  levels = compute_levels(bar, direction, params.use_swing, params.sl_atr, params.rr)
  if levels is None:
    return None, "bad_levels"

  entry, stop_loss, take_profit = levels
  return Proposal(direction=direction, entry=entry,
                  stop_loss=stop_loss, take_profit=take_profit), None


def _dec(value) -> Optional[Decimal]:
  # Angka payload (float/int/str) → Decimal lewat str; kosong/tak valid → None.
  if value is None or isinstance(value, bool):
    return None
  try:
    return Decimal(str(value))
  except ArithmeticError:
    return None


def bar_from_payload(payload: dict) -> PayloadBar:
  """Bangun PayloadBar dari payload webhook; field yang hilang jadi None / list kosong."""
  candle = payload.get("candle")
  smc = payload.get("smc")
  candle = candle if isinstance(candle, dict) else {}
  smc = smc if isinstance(smc, dict) else {}

  raw_triggers = payload.get("triggers")
  triggers = [str(t) for t in raw_triggers] if isinstance(raw_triggers, list) else []

  trend = smc.get("structure_trend")
  return PayloadBar(
      close=_dec(candle.get("close")),
      atr=_dec(candle.get("atr")),
      triggers=triggers,
      structure_trend=str(trend) if trend is not None else None,
      swing_high=_dec(smc.get("swing_high")),
      swing_low=_dec(smc.get("swing_low")),
  )
