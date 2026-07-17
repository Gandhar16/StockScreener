"""Tests for stock_scanner.engine.trade_quality."""

import pytest

from stock_scanner.engine.trade_quality import (
    choose_stop,
    passes_rr_gate,
    position_size,
    risk_reward,
    setup_score,
)


class TestChooseStop:
    def test_pattern_tighter_wins(self):
        # pattern stop 4% away, ATR stop 6% away → pattern chosen
        res = choose_stop(entry=100.0, pattern_stop=96.0, atr=3.0, direction="bullish")
        assert res["stop"] == 96.0
        assert res["stop_source"] == "pattern"
        assert res["stop_pct"] == pytest.approx(0.04)

    def test_atr_tighter_wins(self):
        # pattern stop 8% away, ATR stop 5% away → ATR chosen
        res = choose_stop(entry=100.0, pattern_stop=92.0, atr=2.5, direction="bullish")
        assert res["stop"] == 95.0
        assert res["stop_source"] == "atr"

    def test_noise_guard_skips_too_tight(self):
        # ATR stop only 1% away (< 2% noise floor) → falls to pattern stop
        res = choose_stop(entry=100.0, pattern_stop=95.0, atr=0.5, direction="bullish")
        assert res["stop"] == 95.0
        assert res["stop_source"] == "pattern"

    def test_all_inside_noise_widened(self):
        res = choose_stop(entry=100.0, pattern_stop=99.5, atr=0.4, direction="bullish")
        assert res["stop"] == pytest.approx(98.0)
        assert "noise_guard" in res["stop_source"]

    def test_clamped_at_max(self):
        res = choose_stop(entry=100.0, pattern_stop=80.0, atr=None, direction="bullish")
        assert res["stop"] == pytest.approx(90.0)
        assert "clamped" in res["stop_source"]

    def test_bearish_direction(self):
        res = choose_stop(entry=100.0, pattern_stop=104.0, atr=3.0, direction="bearish")
        assert res["stop"] == 104.0
        assert res["stop"] > 100.0

    def test_invalid_pattern_stop_ignored(self):
        # bullish stop above entry is nonsense → ATR used
        res = choose_stop(entry=100.0, pattern_stop=105.0, atr=2.0, direction="bullish")
        assert res["stop_source"] == "atr"

    def test_nothing_available(self):
        res = choose_stop(entry=100.0, pattern_stop=None, atr=None)
        assert res["stop"] is None


class TestRiskReward:
    def test_basic_long(self):
        assert risk_reward(100.0, 95.0, 115.0) == pytest.approx(3.0)

    def test_basic_short(self):
        assert risk_reward(100.0, 105.0, 90.0, "bearish") == pytest.approx(2.0)

    def test_degenerate_none(self):
        assert risk_reward(100.0, 105.0, 110.0) is None  # long with stop above entry
        assert risk_reward(100.0, None, 110.0) is None

    def test_gate(self):
        assert passes_rr_gate(2.5, 2.0) is True
        assert passes_rr_gate(1.5, 2.0) is False
        assert passes_rr_gate(None) is None


class TestPositionSize:
    def test_fixed_fractional(self):
        # $100k, 1% risk = $1000; stop $10 away → 100 shares ($10k < 15% cap)
        res = position_size(100_000, 0.01, 100.0, 90.0)
        assert res["shares"] == 100
        assert res["capital_at_risk"] == pytest.approx(1000.0)
        assert res["capped"] is False

    def test_notional_cap(self):
        # tight stop would size 1000 shares = $100k > 15% cap → capped to 150
        res = position_size(100_000, 0.01, 100.0, 99.0)
        assert res["capped"] is True
        assert res["position_value"] <= 15_000

    def test_zero_on_bad_inputs(self):
        assert position_size(0, 0.01, 100.0, 95.0)["shares"] == 0
        assert position_size(100_000, 0.01, 100.0, None)["shares"] == 0
        assert position_size(100_000, 0.01, 100.0, 100.0)["shares"] == 0


class TestSetupScore:
    def test_all_components_strong(self):
        res = setup_score(
            pattern_score=85,
            mtf={"mtf_score": 90, "mtf_aligned": True},
            rs={"rs_mansfield": 15.0},
            indicators={"rvol": 2.2, "obv_trend": "rising"},
            rr=3.0,
        )
        assert res["setup_score"] >= 80
        assert res["setup_grade"] == "A+"
        assert res["missing"] == []

    def test_weak_setup_low_grade(self):
        res = setup_score(
            pattern_score=30,
            mtf={"mtf_score": 20, "mtf_aligned": False},
            rs={"rs_mansfield": -18.0},
            indicators={"rvol": 0.6, "obv_trend": "falling"},
            rr=1.1,
        )
        assert res["setup_score"] < 45
        assert res["setup_grade"] == "D"

    def test_missing_components_renormalized(self):
        res = setup_score(pattern_score=80, rr=2.5)
        assert res["setup_score"] is not None
        assert "mtf" in res["missing"]
        assert "rs" in res["missing"]
        # score reflects only pattern + rr, both strong
        assert res["setup_score"] >= 70

    def test_all_missing_is_none(self):
        res = setup_score(pattern_score=None)
        assert res["setup_score"] is None
        assert res["setup_grade"] is None

    def test_rs_mapping(self):
        strong = setup_score(pattern_score=50, rs={"rs_mansfield": 20.0})
        weak = setup_score(pattern_score=50, rs={"rs_mansfield": -20.0})
        assert strong["setup_score"] > weak["setup_score"]

    def test_custom_weights(self):
        res = setup_score(
            pattern_score=100,
            rr=1.0,
            config={"weights": {"pattern": 0.9, "rr": 0.1}},
        )
        assert res["setup_score"] == 90
