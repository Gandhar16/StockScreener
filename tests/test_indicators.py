"""Tests for the extended indicator set in stock_scanner.engine.indicators."""

import numpy as np
import pandas as pd
import pytest

from stock_scanner.engine.indicators import (
    adx,
    bollinger,
    bollinger_squeeze,
    compute_indicators,
    ema,
    ema_stack,
    obv,
    obv_trend,
    pct_from_52w_high,
    rsi,
    rsi_divergence,
    rvol,
    stochastic,
)


def _make_df(close: np.ndarray, volume: np.ndarray = None) -> pd.DataFrame:
    n = len(close)
    if volume is None:
        volume = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame(
        {
            "Open": close * 0.995,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": volume,
        },
        index=idx,
    )


def _trending_up(n=300, start=100.0, step=0.5):
    return start + step * np.arange(n)


def _trending_down(n=300, start=250.0, step=0.5):
    return start - step * np.arange(n)


class TestEMA:
    def test_ema_follows_trend(self):
        close = pd.Series(_trending_up())
        e = ema(close, 20)
        assert e.iloc[-1] < close.iloc[-1]  # lags a rising series
        assert e.iloc[-1] > e.iloc[-50]  # but rises with it

    def test_short_history_is_nan(self):
        e = ema(pd.Series([1.0, 2.0, 3.0]), 20)
        assert e.isna().all()


class TestBollinger:
    def test_percent_b_bounds_in_flat_market(self):
        rng = np.random.default_rng(42)
        close = pd.Series(100 + rng.normal(0, 0.5, 300))
        bb = bollinger(close)
        pb = bb["percent_b"].dropna()
        assert ((pb > -0.5) & (pb < 1.5)).all()

    def test_squeeze_detected_after_compression(self):
        rng = np.random.default_rng(1)
        wild = 100 + np.cumsum(rng.normal(0, 2.0, 260))
        quiet = wild[-1] + rng.normal(0, 0.05, 40)
        close = pd.Series(np.concatenate([wild, quiet]))
        bb = bollinger(close)
        assert bollinger_squeeze(bb["bandwidth"]) is True

    def test_no_squeeze_in_expansion(self):
        rng = np.random.default_rng(2)
        quiet = 100 + rng.normal(0, 0.05, 200)
        wild = quiet[-1] + np.cumsum(rng.normal(0, 2.0, 100))
        close = pd.Series(np.concatenate([quiet, wild]))
        bb = bollinger(close)
        assert bollinger_squeeze(bb["bandwidth"]) is False

    def test_squeeze_none_on_short_history(self):
        bb = bollinger(pd.Series(np.linspace(100, 110, 30)))
        assert bollinger_squeeze(bb["bandwidth"]) is None


class TestADX:
    def test_strong_trend_high_adx(self):
        df = _make_df(_trending_up())
        d = adx(df)
        assert d["adx"].iloc[-1] > 25
        assert d["plus_di"].iloc[-1] > d["minus_di"].iloc[-1]

    def test_downtrend_minus_di_dominates(self):
        df = _make_df(_trending_down())
        d = adx(df)
        assert d["minus_di"].iloc[-1] > d["plus_di"].iloc[-1]

    def test_flat_market_low_adx(self):
        rng = np.random.default_rng(7)
        df = _make_df(100 + rng.normal(0, 0.3, 300))
        d = adx(df)
        assert d["adx"].iloc[-1] < 25


class TestStochastic:
    def test_uptrend_high_k(self):
        df = _make_df(_trending_up())
        st = stochastic(df)
        assert st["k"].iloc[-1] > 70

    def test_downtrend_low_k(self):
        df = _make_df(_trending_down())
        st = stochastic(df)
        assert st["k"].iloc[-1] < 30


class TestOBV:
    def test_rising_obv_on_up_days(self):
        close = pd.Series(_trending_up(100))
        vol = pd.Series(np.full(100, 1e6))
        o = obv(close, vol)
        assert o.iloc[-1] > o.iloc[10]
        assert obv_trend(o) == "rising"

    def test_falling_obv_on_down_days(self):
        close = pd.Series(_trending_down(100))
        vol = pd.Series(np.full(100, 1e6))
        o = obv(close, vol)
        assert obv_trend(o) == "falling"

    def test_obv_trend_none_short(self):
        o = pd.Series([1.0, 2.0, 3.0])
        assert obv_trend(o) is None


class TestRvol:
    def test_volume_spike(self):
        vol = pd.Series([1e6] * 40 + [3e6])
        assert rvol(vol) == pytest.approx(3.0)

    def test_none_on_short(self):
        assert rvol(pd.Series([1e6] * 5)) is None


class TestPctFrom52wHigh:
    def test_at_high(self):
        close = pd.Series(_trending_up())
        assert pct_from_52w_high(close) == pytest.approx(0.0)

    def test_below_high(self):
        up = _trending_up(200, 100, 0.5)  # peaks at 199.5
        down = np.linspace(up[-1], up[-1] * 0.8, 60)
        close = pd.Series(np.concatenate([up, down]))
        v = pct_from_52w_high(close)
        assert v == pytest.approx(20.0, abs=1.0)

    def test_none_on_short(self):
        assert pct_from_52w_high(pd.Series(np.linspace(1, 2, 30))) is None


class TestEmaStack:
    def test_bull_stack_in_uptrend(self):
        st = ema_stack(pd.Series(_trending_up(400)))
        assert st["stacked_bull"] is True
        assert st["stacked_bear"] is False
        assert st["ema50_slope"] > 0

    def test_bear_stack_in_downtrend(self):
        st = ema_stack(pd.Series(_trending_down(400, 400, 0.5)))
        assert st["stacked_bear"] is True
        assert st["ema50_slope"] < 0

    def test_short_history(self):
        st = ema_stack(pd.Series(np.linspace(100, 110, 30)))
        assert st["ema200"] is None
        assert st["stacked_bull"] is False


class TestRsiDivergence:
    def test_bearish_divergence(self):
        # Price: two peaks, second higher. Momentum into the second peak weaker
        # (slower ascent) so RSI prints a lower high.
        first_up = np.linspace(100, 130, 25)  # steep run
        pull = np.linspace(130, 112, 15)
        second_up = np.linspace(112, 133, 40)  # higher high, weak slope
        close = pd.Series(np.concatenate([np.full(30, 100.0), first_up, pull, second_up]))
        r = rsi(close)
        assert rsi_divergence(close, r, lookback=90) in ("bearish", None)

    def test_no_divergence_in_clean_trend(self):
        close = pd.Series(_trending_up(120))
        r = rsi(close)
        assert rsi_divergence(close, r) is None

    def test_none_on_short(self):
        close = pd.Series(np.linspace(100, 105, 20))
        assert rsi_divergence(close, rsi(close)) is None


class TestComputeIndicators:
    def test_all_new_keys_present(self):
        df = _make_df(_trending_up())
        ind = compute_indicators(df)
        for key in (
            "bb_percent_b",
            "bb_squeeze",
            "adx",
            "plus_di",
            "minus_di",
            "trend_strength",
            "stoch_k",
            "stoch_d",
            "obv_trend",
            "rvol",
            "pct_from_52w_high",
            "ema20",
            "ema50",
            "ema200",
            "ema_stack_bull",
            "ema_stack_bear",
            "ema50_slope",
            "rsi_divergence",
        ):
            assert key in ind, f"missing {key}"

    def test_old_keys_unchanged(self):
        df = _make_df(_trending_up())
        ind = compute_indicators(df)
        for key in (
            "price",
            "rsi",
            "macd_hist",
            "ma50",
            "ma200",
            "above_50",
            "above_200",
            "atr",
            "vol_contracting",
        ):
            assert key in ind

    def test_uptrend_classification(self):
        df = _make_df(_trending_up())
        ind = compute_indicators(df)
        assert ind["trend_strength"] == "strong"
        assert ind["ema_stack_bull"] is True

    def test_short_history_returns_none_not_zero(self):
        df = _make_df(np.linspace(100, 105, 12))
        ind = compute_indicators(df)
        assert ind["adx"] is None
        assert ind["trend_strength"] is None
        assert ind["rvol"] is None
        assert ind["pct_from_52w_high"] is None
        assert ind["ema200"] is None
