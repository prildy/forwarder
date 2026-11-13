"""Unit test untuk strategy.py — aturan entry mekanis murni (tanpa DB/jaringan)."""
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

import backtest
import strategy
from strategy import EntryParams, PayloadBar, Proposal, bar_from_payload, propose


def _params(**overrides) -> EntryParams:
  base = dict(direction_override="auto", qualifying_triggers=None, use_swing=False,
              sl_atr=Decimal("1.5"), rr=Decimal("2.0"), allow_overlap=False)
  base.update(overrides)
  return EntryParams(**base)


def _bar(**overrides) -> PayloadBar:
  base = dict(close=Decimal("100"), atr=Decimal("2"), triggers=["reentry"],
              structure_trend="bullish", swing_high=Decimal("105"),
              swing_low=Decimal("97"))
  base.update(overrides)
  return PayloadBar(**base)


def test_backtest_reexports_strategy_symbols():
  assert backtest.EntryParams is strategy.EntryParams
  assert backtest.resolve_direction is strategy.resolve_direction
  assert backtest.compute_levels is strategy.compute_levels


def test_propose_no_trigger():
  assert propose(_bar(triggers=[]), _params()) == (None, "no_trigger")


def test_propose_trigger_filter():
  params = _params(qualifying_triggers={"extreme"})
  assert propose(_bar(triggers=["reentry"]), params) == (None, "trigger_filter")


def test_propose_trigger_filter_passes_on_intersection():
  params = _params(qualifying_triggers={"extreme", "reentry"})
  proposal, reason = propose(_bar(), params)
  assert reason is None and proposal is not None


def test_propose_no_direction():
  assert propose(_bar(structure_trend="neutral"), _params()) == (None, "no_direction")
  assert propose(_bar(structure_trend=None), _params()) == (None, "no_direction")


def test_propose_bad_levels_missing_atr_or_close():
  assert propose(_bar(atr=None), _params()) == (None, "bad_levels")
  assert propose(_bar(atr=Decimal("0")), _params()) == (None, "bad_levels")
  assert propose(_bar(close=None), _params()) == (None, "bad_levels")


def test_propose_guard_order_trigger_before_direction():
  # Tanpa trigger DAN tanpa arah → alasan pertama (no_trigger) yang menang.
  bar = _bar(triggers=[], structure_trend=None, atr=None)
  assert propose(bar, _params()) == (None, "no_trigger")


def test_propose_guard_order_filter_before_direction():
  bar = _bar(triggers=["reentry"], structure_trend=None)
  params = _params(qualifying_triggers={"extreme"})
  assert propose(bar, params) == (None, "trigger_filter")


def test_propose_guard_order_direction_before_levels():
  bar = _bar(structure_trend=None, atr=None)
  assert propose(bar, _params()) == (None, "no_direction")


def test_propose_long_atr():
  proposal, reason = propose(_bar(), _params())
  assert reason is None
  assert proposal == Proposal("long", Decimal("100"), Decimal("97.0"), Decimal("106.0"))


def test_propose_short_atr():
  proposal, reason = propose(_bar(structure_trend="Bearish"), _params())
  assert reason is None
  assert proposal == Proposal("short", Decimal("100"), Decimal("103.0"), Decimal("94.0"))


def test_propose_direction_override_forces_direction():
  proposal, _ = propose(_bar(structure_trend="bullish"), _params(direction_override="short"))
  assert proposal.direction == "short"


def test_propose_swing_long():
  proposal, reason = propose(_bar(), _params(use_swing=True))
  assert reason is None
  assert proposal == Proposal("long", Decimal("100"), Decimal("97"), Decimal("106.0"))


def test_propose_swing_short():
  proposal, reason = propose(_bar(structure_trend="bearish"), _params(use_swing=True))
  assert reason is None
  assert proposal == Proposal("short", Decimal("100"), Decimal("105"), Decimal("90.0"))


def test_propose_swing_bad_levels():
  # long: swing_low >= entry → tak valid; short: swing_high <= entry → tak valid.
  assert propose(_bar(swing_low=Decimal("100")), _params(use_swing=True)) == (None, "bad_levels")
  assert propose(_bar(swing_low=None), _params(use_swing=True)) == (None, "bad_levels")
  bear = _bar(structure_trend="bearish", swing_high=Decimal("99"))
  assert propose(bear, _params(use_swing=True)) == (None, "bad_levels")


def test_proposal_is_frozen():
  proposal, _ = propose(_bar(), _params())
  with pytest.raises(FrozenInstanceError):
    proposal.entry = Decimal("1")


def test_bar_from_payload_full():
  payload = {
      "candle": {"close": 2650.55, "atr": 1.25},
      "triggers": ["reentry", "extreme"],
      "smc": {"structure_trend": "bullish", "swing_high": 2660.1, "swing_low": 2640},
  }
  bar = bar_from_payload(payload)
  assert bar.close == Decimal("2650.55")
  assert bar.atr == Decimal("1.25")
  assert bar.triggers == ["reentry", "extreme"]
  assert bar.structure_trend == "bullish"
  assert bar.swing_high == Decimal("2660.1")
  assert bar.swing_low == Decimal("2640")


def test_bar_from_payload_sparse():
  bar = bar_from_payload({})
  assert bar.close is None and bar.atr is None
  assert bar.triggers == []
  assert bar.structure_trend is None
  assert bar.swing_high is None and bar.swing_low is None


def test_bar_from_payload_partial_and_wrong_types():
  bar = bar_from_payload({"candle": {"close": "100.5", "atr": None}, "triggers": "x",
                          "smc": None})
  assert bar.close == Decimal("100.5")
  assert bar.atr is None
  assert bar.triggers == []
  assert bar.structure_trend is None


def test_bar_from_payload_feeds_propose():
  payload = {"candle": {"close": 100, "atr": 2}, "triggers": ["t"],
             "smc": {"structure_trend": "bullish"}}
  proposal, reason = propose(bar_from_payload(payload), _params())
  assert reason is None
  assert proposal.direction == "long"
