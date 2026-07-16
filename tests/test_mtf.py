"""Tests for multi-timeframe confirmation (stock_scanner.engine.mtf)."""

import numpy as np
import pandas as pd

from stock_scanner.engine.mtf import (
    analyze_mtf,
    mtf_alignment,
    resample_weekly,
    weekly_state,
)


def _daily_df(close: np.ndarray) -> pd.DataFrame:
    n = len(close)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _uptrend(n=500):
    rng = np.random.default_rng(0)
    return 100 + 0.3 * np.arange(n) + rng.normal(0, 0.5, n)


def _downtrend(n=500):
    rng = np.random.default_rng(0)
    return 300 - 0.3 * np.arange(n) + rng.normal(0, 0.5, n)


class TestResampleWeekly:
    def test_ohlc_semantics(self):
        df = _daily_df(np.linspace(100, 110, 50))
        wk = resample_weekly(df)
        assert len(wk) < len(df)
        first_week = df.iloc[:5]
        assert wk["Open"].iloc[0] == first_week["Open"].iloc[0]
        assert wk["High"].iloc[0] == first_week["High"].max()
        assert wk["Low"].iloc[0] == first_week["Low"].min()
        assert wk["Volume"].iloc[0] == first_week["Volume"].sum()

    def test_close_is_last_of_week(self):
        df = _daily_df(np.linspace(100, 110, 50))
        wk = resample_weekly(df)
        assert wk["Close"].iloc[-1] == df["Close"].iloc[-1]


class TestWeeklyState:
    def test_uptrend_state(self):
        st = weekly_state(resample_weekly(_daily_df(_uptrend())))
        assert st is not None
        assert st["above_ema10w"] is True
        assert st["above_sma30w"] is True
        assert st["higher_highs_w"] is True
        assert st["rsi_w"] > 50

    def test_downtrend_state(self):
        st = weekly_state(resample_weekly(_daily_df(_downtrend())))
        assert st["above_ema10w"] is False
        assert st["above_sma30w"] is False
        assert st["rsi_w"] < 50

    def test_short_history_returns_none(self):
        st = weekly_state(resample_weekly(_daily_df(np.linspace(100, 105, 40))))
        assert st is None

    def test_medium_history_sma30w_none(self):
        # ~20 weeks: enough for state, not for the 30-week SMA
        st = weekly_state(resample_weekly(_daily_df(_uptrend(100))))
        assert st is not None
        assert st["sma30w"] is None
        assert st["above_sma30w"] is None


class TestMtfAlignment:
    def test_bull_setup_in_weekly_uptrend_aligned(self):
        res = analyze_mtf(_daily_df(_uptrend()), "bullish")
        assert res["mtf_aligned"] is True
        assert res["mtf_score"] >= 55

    def test_bull_setup_in_weekly_downtrend_not_aligned(self):
        res = analyze_mtf(_daily_df(_downtrend()), "bullish")
        assert res["mtf_aligned"] is False
        assert res["mtf_score"] < 55

    def test_bear_setup_in_weekly_downtrend_aligned(self):
        res = analyze_mtf(_daily_df(_downtrend()), "bearish")
        assert res["mtf_aligned"] is True

    def test_missing_weekly_is_pass_through(self):
        res = mtf_alignment("bullish", None)
        assert res["mtf_score"] is None
        assert res["mtf_aligned"] is None

    def test_short_history_pass_through(self):
        res = analyze_mtf(_daily_df(np.linspace(100, 104, 30)), "bullish")
        assert res["mtf_aligned"] is None

    def test_renormalization_without_sma30w(self):
        # 100 bars ≈ 20 weeks: SMA30w unavailable; a clean uptrend should
        # still align on the remaining components.
        res = analyze_mtf(_daily_df(_uptrend(100)), "bullish")
        assert res["mtf_aligned"] is True
        assert res["mtf_score"] >= 55

    def test_config_threshold_respected(self):
        res = analyze_mtf(_daily_df(_uptrend()), "bullish",
                          config={"aligned_threshold": 101})
        assert res["mtf_aligned"] is False
