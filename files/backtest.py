#!/usr/bin/env python
"""Backtest replay: putar ulang alert yang sudah tersimpan jadi trade jurnal backtest.

Script CLI manual (BUKAN bagian dari server / scheduler / railway.json). Dia baca tabel
`alerts` untuk satu symbol+timeframe, membangkitkan trade sintetis berdasarkan entry-rule
yang bisa di-tune, lalu meresolusi tiap trade PERSIS seperti resolver live
(main.py:resolve_open_trades) — supaya angka backtest dan live sebanding.

Karena main.py membaca env wajib (ANALYZE_SECRET, WEBHOOK_SECRET, TELEGRAM_*, dst) saat
import dan langsung membangun app FastAPI, script ini TIDAK meng-import main.py. Dia
konek sendiri ke DATABASE_URL pakai psycopg3 (lib yang sama dengan app). Logika resolusi
SL/TP TIDAK digandakan lagi: keduanya (live & backtest) delegasi ke modul `resolver`
yang bebas env/DB, jadi angka backtest dan live mustahil menyimpang.

Catatan: alert dibersihkan setelah 7 hari oleh cleanup job, jadi backtest hanya melihat
history ~7 hari terakhir. Itu batasan yang diketahui dan diterima.

Contoh:
  python -I backtest.py --symbol FX:XAUUSD --timeframe 30S --dry-run
  python -I backtest.py --symbol FX:XAUUSD --timeframe 30S --purge-backtest
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

import psycopg

import resolver
from resolver import Resolution

# Mode jurnal yang HARAM disentuh script ini — hanya 'backtest' yang boleh ditulis/dihapus.
PROTECTED_MODES = ("live", "forward")
BACKTEST_MODE = "backtest"


# ===================== Domain model =====================


@dataclass(frozen=True)
class Bar:
  """Satu bar alert yang sudah di-ekstrak dari payload JSONB."""

  alert_id: int
  bar_time: datetime
  high: Optional[Decimal]
  low: Optional[Decimal]
  close: Optional[Decimal]
  atr: Optional[Decimal]
  triggers: list[str]
  structure_trend: Optional[str]
  swing_high: Optional[Decimal]
  swing_low: Optional[Decimal]


@dataclass(frozen=True)
class GeneratedTrade:
  """Trade sintetis hasil replay: info entry + hasil resolusi."""

  bar: Bar
  direction: str                    # 'long' | 'short'
  entry: Decimal
  stop_loss: Decimal
  take_profit: Decimal
  resolution: Resolution


# ===================== Data layer (psycopg3) =====================


def load_bars(conn: psycopg.Connection, symbol: str, timeframe: str) -> list[Bar]:
  # Ambil semua bar untuk symbol+timeframe, urut waktu naik. Cast ke numeric supaya
  # high/low/close/atr balik sebagai Decimal (sama seperti resolve_open_trades).
  rows = conn.execute(
      """SELECT id, bar_time,
                (payload->'candle'->>'high')::numeric,
                (payload->'candle'->>'low')::numeric,
                (payload->'candle'->>'close')::numeric,
                (payload->'candle'->>'atr')::numeric,
                payload->'triggers',
                payload->'smc'->>'structure_trend',
                (payload->'smc'->>'swing_high')::numeric,
                (payload->'smc'->>'swing_low')::numeric
         FROM alerts
         WHERE symbol = %s AND timeframe = %s
         ORDER BY bar_time ASC""",
      (symbol, timeframe),
  ).fetchall()

  bars: list[Bar] = []
  for row in rows:
    raw_triggers = row[6]
    triggers = [str(t) for t in raw_triggers] if isinstance(raw_triggers, list) else []
    bars.append(
        Bar(
            alert_id=row[0],
            bar_time=row[1],
            high=row[2],
            low=row[3],
            close=row[4],
            atr=row[5],
            triggers=triggers,
            structure_trend=row[7],
            swing_high=row[8],
            swing_low=row[9],
        )
    )
  return bars


def count_backtest_rows(conn: psycopg.Connection, symbol: str, timeframe: str) -> int:
  row = conn.execute(
      """SELECT count(*) FROM journal
         WHERE mode = %s AND symbol = %s AND timeframe = %s""",
      (BACKTEST_MODE, symbol, timeframe),
  ).fetchone()
  return int(row[0])


def purge_backtest_rows(conn: psycopg.Connection, symbol: str, timeframe: str) -> int:
  # WHERE mode='backtest' eksplisit: baris live/forward mustahil ikut terhapus.
  result = conn.execute(
      """DELETE FROM journal
         WHERE mode = %s AND symbol = %s AND timeframe = %s""",
      (BACKTEST_MODE, symbol, timeframe),
  )
  return result.rowcount


def insert_backtest_trade(conn: psycopg.Connection, symbol: str, timeframe: str,
                          trade: GeneratedTrade) -> int:
  # opened_at = bar_time kandidat (BUKAN now()), supaya resolver menelusuri bar setelahnya.
  row = conn.execute(
      """INSERT INTO journal
         (symbol, timeframe, mode, direction, entry, stop_loss, take_profit,
          setup_tags, alert_id, opened_at, status)
         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
         RETURNING id""",
      (symbol, timeframe, BACKTEST_MODE, trade.direction, trade.entry,
       trade.stop_loss, trade.take_profit, trade.bar.triggers, trade.bar.alert_id,
       trade.bar.bar_time),
  ).fetchone()
  return int(row[0])


def close_backtest_trade(conn: psycopg.Connection, journal_id: int,
                         resolution: Resolution) -> None:
  # Mirror persis UPDATE di resolve_open_trades: WHERE status='open' bikin idempoten.
  conn.execute(
      """UPDATE journal
         SET status = %s, exit_price = %s, r_multiple = %s, closed_at = %s
         WHERE id = %s AND status = 'open'""",
      (resolution.status, resolution.exit_price, resolution.r_multiple,
       resolution.closed_at, journal_id),
  )


# ===================== Service layer: resolusi (delegasi ke modul resolver) =====================


def resolve_trade(direction: str, entry: Decimal, stop_loss: Decimal,
                  take_profit: Decimal, opened_at: datetime, bars: list[Bar]) -> Resolution:
  """Wrapper tipis ke resolver.resolve (SUMBER KEBENARAN tunggal, dipakai juga live).

  Perbedaan dengan resolver live cuma bentuk sumber data: live query ulang `alerts` lewat
  SQL (bar_time > opened_at), di sini kita filter list bar in-memory dengan syarat sama,
  lalu delegasikan keputusan SL/TP ke resolver. `Bar` backtest sudah punya atribut
  bar_time/high/low yang dibutuhkan resolver, jadi diteruskan apa adanya.
  """
  # Setara WHERE bar_time > opened_at ORDER BY bar_time ASC pada resolver live.
  candidate_bars = [bar for bar in bars if bar.bar_time > opened_at]
  return resolver.resolve(direction, entry, stop_loss, take_profit, candidate_bars)


# ===================== Service layer: entry rule (jantung yang bisa di-tune) =====================


def resolve_direction(bar: Bar, override: str) -> Optional[str]:
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


def compute_levels(bar: Bar, direction: str, use_swing: bool,
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


@dataclass(frozen=True)
class EntryParams:
  direction_override: str           # 'auto' | 'long' | 'short'
  qualifying_triggers: Optional[set[str]]   # None = semua bar bertrigger lolos
  use_swing: bool
  sl_atr: Decimal
  rr: Decimal
  allow_overlap: bool


def generate_trades(bars: list[Bar], params: EntryParams) -> tuple[list[GeneratedTrade], dict]:
  """Replay bar jadi trade. Terapkan filter trigger, arah, SL/TP, dan no-pyramiding.

  No-pyramiding (default): selama trade yang dibuka bar sebelumnya belum resolve di waktu
  bar sekarang, lewati — satu posisi pada satu waktu, meniru trader tunggal. Resolusi
  disimulasikan in-memory hanya untuk gating entry; angka final tetap dari resolve_trade.
  """
  trades: list[GeneratedTrade] = []
  skipped = {"no_trigger": 0, "trigger_filter": 0, "no_direction": 0,
             "bad_levels": 0, "overlap": 0}

  blocked_until: Optional[datetime] = None   # waktu tutup trade terakhir (no-pyramiding)
  blocked_forever = False                    # trade terakhir tak pernah resolve

  for bar in bars:
    if not params.allow_overlap:
      if blocked_forever:
        # Posisi terbuka tak pernah tertutup → tak ada entry baru lagi.
        skipped["overlap"] += 1
        continue
      if blocked_until is not None and bar.bar_time <= blocked_until:
        skipped["overlap"] += 1
        continue

    # Guard: trigger wajib non-empty.
    if not bar.triggers:
      skipped["no_trigger"] += 1
      continue

    # Guard: filter trigger qualifying (kalau di-set).
    if params.qualifying_triggers is not None:
      if not (set(bar.triggers) & params.qualifying_triggers):
        skipped["trigger_filter"] += 1
        continue

    # Guard: arah harus jelas.
    direction = resolve_direction(bar, params.direction_override)
    if direction is None:
      skipped["no_direction"] += 1
      continue

    # Guard: level entry/SL/TP harus valid.
    levels = compute_levels(bar, direction, params.use_swing, params.sl_atr, params.rr)
    if levels is None:
      skipped["bad_levels"] += 1
      continue

    entry, stop_loss, take_profit = levels
    resolution = resolve_trade(direction, entry, stop_loss, take_profit, bar.bar_time, bars)
    trades.append(
        GeneratedTrade(bar=bar, direction=direction, entry=entry,
                       stop_loss=stop_loss, take_profit=take_profit, resolution=resolution)
    )

    if not params.allow_overlap:
      if resolution.is_open:
        blocked_forever = True
      else:
        blocked_until = resolution.closed_at

  return trades, skipped


# ===================== Service layer: metrik ringkasan =====================


def build_summary(trades: list[GeneratedTrade]) -> dict:
  wins = sum(1 for t in trades if t.resolution.status == "win")
  losses = sum(1 for t in trades if t.resolution.status == "loss")
  opens = sum(1 for t in trades if t.resolution.is_open)
  generated = len(trades)
  resolved = wins + losses

  total_r = sum((t.resolution.r_multiple for t in trades if t.resolution.r_multiple is not None),
                Decimal(0))
  win_rate = (Decimal(wins) / Decimal(resolved) * 100) if resolved else Decimal(0)
  avg_r = (total_r / Decimal(resolved)) if resolved else Decimal(0)
  # Expectancy per trade yang diambil: trade open dihitung 0R (belum ada hasil).
  expectancy = (total_r / Decimal(generated)) if generated else Decimal(0)

  # Max beruntun loss: urutkan kronologis (trades sudah urut entry), hitung hanya yang closed.
  max_consecutive_losses = 0
  current_streak = 0
  for trade in trades:
    status = trade.resolution.status
    if status == "loss":
      current_streak += 1
      max_consecutive_losses = max(max_consecutive_losses, current_streak)
    elif status == "win":
      current_streak = 0
    # status 'open' dilewati: tak menambah dan tak memutus streak.

  return {
      "generated": generated,
      "wins": wins,
      "losses": losses,
      "opens": opens,
      "resolved": resolved,
      "win_rate": win_rate,
      "total_r": total_r,
      "avg_r": avg_r,
      "expectancy": expectancy,
      "max_consecutive_losses": max_consecutive_losses,
  }


# ===================== Protocol layer: CLI =====================


def parse_args(argv: list[str]) -> argparse.Namespace:
  parser = argparse.ArgumentParser(
      prog="backtest.py",
      description=(
          "Replay alert tersimpan jadi trade jurnal mode='backtest' dan resolusi dengan "
          "logika SL/TP yang sama persis dengan resolver live. Jalankan manual, bukan "
          "bagian server/scheduler."
      ),
  )
  parser.add_argument("--symbol", default=os.getenv("DEFAULT_SYMBOL", "FX:XAUUSD"),
                      help="Symbol persis seperti di kolom alerts.symbol (default: FX:XAUUSD).")
  parser.add_argument("--timeframe", default=os.getenv("DEFAULT_TF", "30S"),
                      help="Timeframe persis seperti di alerts.timeframe (default: 30S).")
  parser.add_argument("--triggers", default="",
                      help="Daftar trigger qualifying dipisah koma. Kosong = semua bar "
                           "bertrigger lolos (default).")
  parser.add_argument("--direction", choices=("auto", "long", "short"), default="auto",
                      help="Sumber arah: 'auto' dari smc.structure_trend (default), atau "
                           "paksa long/short.")
  parser.add_argument("--sl-atr", type=float, default=1.5,
                      help="Pengali ATR untuk jarak stop-loss (default: 1.5).")
  parser.add_argument("--rr", type=float, default=2.0,
                      help="Risk:reward — TP = jarak SL x rr (default: 2.0).")
  parser.add_argument("--sl-swing", action="store_true",
                      help="Pakai SL berbasis swing (smc.swing_low/high) alih-alih ATR. "
                           "TP tetap risk x rr.")
  parser.add_argument("--allow-overlap", action="store_true",
                      help="Izinkan trade tumpang-tindih (pyramiding). Default: satu posisi "
                           "pada satu waktu.")
  parser.add_argument("--purge-backtest", action="store_true",
                      help="Hapus dulu baris mode='backtest' untuk symbol+timeframe ini "
                           "sebelum run (hindari duplikat saat re-run).")
  parser.add_argument("--dry-run", action="store_true",
                      help="Bangkitkan + simulasi di memori dan cetak ringkasan TANPA "
                           "menulis ke DB.")
  parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"),
                      help="Postgres DSN (default: env DATABASE_URL).")
  parser.add_argument("-v", "--verbose", action="store_true",
                      help="Cetak tiap trade yang dibangkitkan.")
  return parser.parse_args(argv)


def _fmt(value: Optional[Decimal], digits: int = 2, signed: bool = False) -> str:
  if value is None:
    return "-"
  spec = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
  return spec.format(float(value))


def print_trades(trades: list[GeneratedTrade]) -> None:
  print("\n-- Trade yang dibangkitkan --")
  for index, trade in enumerate(trades, start=1):
    res = trade.resolution
    r_txt = _fmt(res.r_multiple, signed=True) if res.r_multiple is not None else "-"
    closed_txt = res.closed_at.isoformat() if res.closed_at else "open"
    print(
        f"#{index} {trade.bar.bar_time.isoformat()} {trade.direction} "
        f"entry {_fmt(trade.entry)} sl {_fmt(trade.stop_loss)} tp {_fmt(trade.take_profit)} "
        f"-> {res.status} (R {r_txt}, {closed_txt})"
    )


def print_summary(summary: dict, symbol: str, timeframe: str, params: EntryParams,
                  skipped: dict, dry_run: bool) -> None:
  sl_mode = "swing" if params.use_swing else "atr"
  trig_txt = ", ".join(sorted(params.qualifying_triggers)) if params.qualifying_triggers else "(semua)"

  print("\n============ RINGKASAN BACKTEST ============")
  print(f"Symbol/Timeframe : {symbol} {timeframe}")
  print(f"Mode tulis       : {'DRY-RUN (tidak menulis DB)' if dry_run else 'DB write'}")
  print(f"Arah             : {params.direction_override}")
  print(f"SL mode          : {sl_mode} (sl-atr={_fmt(params.sl_atr)}, rr={_fmt(params.rr)})")
  print(f"Trigger filter   : {trig_txt}")
  print(f"Pyramiding        : {'diizinkan' if params.allow_overlap else 'tidak (1 posisi)'}")
  print("--------------------------------------------")
  print(f"Trade dibangkitkan      : {summary['generated']}")
  print(f"Menang / Kalah / Open   : {summary['wins']} / {summary['losses']} / {summary['opens']}")
  print(f"Win rate (closed)       : {_fmt(summary['win_rate'], 1)}%")
  print(f"Total R                 : {_fmt(summary['total_r'], signed=True)}")
  print(f"Average R (per closed)  : {_fmt(summary['avg_r'], signed=True)}")
  print(f"Expectancy (R/trade*)   : {_fmt(summary['expectancy'], signed=True)}")
  print(f"Max beruntun loss       : {summary['max_consecutive_losses']}")
  print("--------------------------------------------")
  print("Dilewati (skip): "
        f"no_trigger={skipped['no_trigger']} trigger_filter={skipped['trigger_filter']} "
        f"no_direction={skipped['no_direction']} bad_levels={skipped['bad_levels']} "
        f"overlap={skipped['overlap']}")
  print("* Expectancy membagi Total R dengan semua trade (open dihitung 0R).")
  print("============================================")


def persist_trades(conn: psycopg.Connection, symbol: str, timeframe: str,
                   trades: list[GeneratedTrade]) -> None:
  # Insert sebagai 'open' dulu, lalu resolusi — meniru alur live (create -> resolver).
  for trade in trades:
    journal_id = insert_backtest_trade(conn, symbol, timeframe, trade)
    if not trade.resolution.is_open:
      close_backtest_trade(conn, journal_id, trade.resolution)


def run(args: argparse.Namespace) -> int:
  if not args.db_url:
    print("ERROR: DATABASE_URL tidak di-set (atau pakai --db-url).", file=sys.stderr)
    return 2

  params = EntryParams(
      direction_override=args.direction,
      qualifying_triggers=({t.strip() for t in args.triggers.split(",") if t.strip()} or None),
      use_swing=args.sl_swing,
      sl_atr=Decimal(str(args.sl_atr)),
      rr=Decimal(str(args.rr)),
      allow_overlap=args.allow_overlap,
  )

  with psycopg.connect(args.db_url) as conn:
    bars = load_bars(conn, args.symbol, args.timeframe)
    if not bars:
      print(f"Tidak ada alert untuk {args.symbol}/{args.timeframe}. "
            "Cek symbol/timeframe atau history mungkin sudah dibersihkan (>7 hari).")
      return 1

    trades, skipped = generate_trades(bars, params)
    summary = build_summary(trades)

    if args.dry_run:
      # Dry-run: jangan sentuh DB sama sekali.
      if args.verbose:
        print_trades(trades)
      print_summary(summary, args.symbol, args.timeframe, params, skipped, dry_run=True)
      return 0

    # Idempotency: tolak kalau sudah ada baris backtest, kecuali --purge-backtest.
    existing = count_backtest_rows(conn, args.symbol, args.timeframe)
    if existing > 0 and not args.purge_backtest:
      print(f"ERROR: sudah ada {existing} baris mode='backtest' untuk "
            f"{args.symbol}/{args.timeframe}. Jalankan ulang dengan --purge-backtest "
            "untuk mengganti, atau --dry-run untuk simulasi tanpa menulis.",
            file=sys.stderr)
      return 3

    if args.purge_backtest:
      deleted = purge_backtest_rows(conn, args.symbol, args.timeframe)
      print(f"Purge: {deleted} baris backtest lama dihapus.")

    persist_trades(conn, args.symbol, args.timeframe, trades)
    conn.commit()
    print(f"Tersimpan: {summary['generated']} trade backtest "
          f"({summary['resolved']} resolved, {summary['opens']} open).")

    if args.verbose:
      print_trades(trades)
    print_summary(summary, args.symbol, args.timeframe, params, skipped, dry_run=False)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
  return run(parse_args(argv if argv is not None else sys.argv[1:]))


if __name__ == "__main__":
  raise SystemExit(main())
