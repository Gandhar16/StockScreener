"""
mtf.py
======
Multi-timeframe (weekly) confirmation for daily setups.

A daily breakout trading WITH the weekly trend has materially better odds
than one fighting it. This module resamples the daily OHLCV already in hand
(no second fetch), summarizes the weekly state, and scores how well a
proposed daily setup aligns with it.

All outputs degrade gracefully: with fewer than MIN_WEEKLY_BARS of history
the alignment is None (pass-through), never a fail — critical for young
NSE listings.
"""

import pandas as pd

from .indicators import ema, macd, rsi, sma

MIN_WEEKLY_BARS = 15

# Component weights for the alignment score (renormalized if a component
# is unavailable, e.g. SMA30w on < 30 weeks of history).
DEFAULT_WEIGHTS = {
    "above_ema10w": 30,
    "above_sma30w": 25,
    "macd_w": 25,
    "rsi_w": 20,
}
DEFAULT_ALIGNED_THRESHOLD = 55


def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly bars ending Friday."""
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
    }
    if "Volume" in df.columns:
        agg["Volume"] = "sum"
    weekly = df.resample("W-FRI").agg(agg).dropna(subset=["Close"])
    return weekly


def weekly_state(weekly_df: pd.DataFrame) -> dict | None:
    """
    Summarize the weekly timeframe at the latest bar.
    Returns None when history is too short to say anything (< MIN_WEEKLY_BARS).
    """
    n = len(weekly_df)
    if n < MIN_WEEKLY_BARS:
        return None

    close = weekly_df["Close"]
    px = float(close.iloc[-1])

    def _last(s: pd.Series) -> float | None:
        v = s.iloc[-1]
        return float(v) if not pd.isna(v) else None

    ema10w = _last(ema(close, 10))
    sma30w = _last(sma(close, 30))  # None if < 30 weeks

    macd_d = macd(close)
    hist = macd_d["hist"]
    macd_hist_w = _last(hist)
    macd_rising_w = None
    h = hist.dropna()
    if len(h) >= 2:
        macd_rising_w = bool(h.iloc[-1] > h.iloc[-2])

    rsi_w = _last(rsi(close))

    # Structure: is the market printing higher highs on the weekly?
    higher_highs_w = None
    if n >= 20:
        recent_hi = float(weekly_df["High"].iloc[-10:].max())
        prior_hi = float(weekly_df["High"].iloc[-20:-10].max())
        higher_highs_w = recent_hi > prior_hi

    return {
        "close": px,
        "ema10w": ema10w,
        "sma30w": sma30w,
        "above_ema10w": (px > ema10w) if ema10w is not None else None,
        "above_sma30w": (px > sma30w) if sma30w is not None else None,
        "macd_hist_w": macd_hist_w,
        "macd_rising_w": macd_rising_w,
        "rsi_w": rsi_w,
        "higher_highs_w": higher_highs_w,
        "bars": n,
    }


def mtf_alignment(direction: str, weekly: dict | None, config: dict | None = None) -> dict:
    """
    Score how well a daily setup aligns with the weekly trend.

    direction: "bullish" or "bearish" (the daily setup's direction)
    weekly:    output of weekly_state(), or None

    Returns {mtf_score: 0-100 or None, mtf_aligned: bool or None, mtf_reasons: [str]}.
    mtf_aligned is None (pass-through, not fail) when weekly data is missing.
    """
    cfg = config or {}
    weights = dict(DEFAULT_WEIGHTS, **cfg.get("weights", {}))
    threshold = cfg.get("aligned_threshold", DEFAULT_ALIGNED_THRESHOLD)

    if weekly is None:
        return {
            "mtf_score": None,
            "mtf_aligned": None,
            "mtf_reasons": ["insufficient weekly history"],
        }

    is_bull = direction == "bullish"
    reasons = []
    earned = 0.0
    available = 0.0

    # 1. Price vs 10-week EMA (short-intermediate weekly trend)
    if weekly.get("above_ema10w") is not None:
        w = weights["above_ema10w"]
        available += w
        good = weekly["above_ema10w"] if is_bull else not weekly["above_ema10w"]
        if good:
            earned += w
            reasons.append("price %s 10-week EMA" % ("above" if is_bull else "below"))
        else:
            reasons.append(
                "price %s 10-week EMA (against setup)" % ("below" if is_bull else "above")
            )

    # 2. Price vs 30-week SMA (Weinstein stage proxy); skipped + renormalized
    #    when < 30 weeks of history.
    if weekly.get("above_sma30w") is not None:
        w = weights["above_sma30w"]
        available += w
        good = weekly["above_sma30w"] if is_bull else not weekly["above_sma30w"]
        if good:
            earned += w
            reasons.append("price %s 30-week SMA" % ("above" if is_bull else "below"))
        else:
            reasons.append(
                "price %s 30-week SMA (against setup)" % ("below" if is_bull else "above")
            )

    # 3. Weekly MACD momentum: histogram on the right side OR curling that way
    hist_w = weekly.get("macd_hist_w")
    rising = weekly.get("macd_rising_w")
    if hist_w is not None:
        w = weights["macd_w"]
        available += w
        good = hist_w > 0 or rising is True if is_bull else hist_w < 0 or rising is False
        if good:
            earned += w
            reasons.append("weekly MACD supportive")
        else:
            reasons.append("weekly MACD against setup")

    # 4. Weekly RSI in a healthy zone (not exhausted, not broken)
    rsi_w = weekly.get("rsi_w")
    if rsi_w is not None:
        w = weights["rsi_w"]
        available += w
        good = (40 <= rsi_w <= 75) if is_bull else (25 <= rsi_w <= 60)
        if good:
            earned += w
            reasons.append(f"weekly RSI {rsi_w:.0f} healthy")
        else:
            reasons.append(f"weekly RSI {rsi_w:.0f} unfavorable")

    if available <= 0:
        return {
            "mtf_score": None,
            "mtf_aligned": None,
            "mtf_reasons": ["no weekly components computable"],
        }

    score = round(earned / available * 100)
    return {
        "mtf_score": score,
        "mtf_aligned": score >= threshold,
        "mtf_reasons": reasons,
    }


def analyze_mtf(df: pd.DataFrame, direction: str, config: dict | None = None) -> dict:
    """Convenience wrapper: daily OHLCV in, alignment dict out."""
    weekly = weekly_state(resample_weekly(df))
    return mtf_alignment(direction, weekly, config)
