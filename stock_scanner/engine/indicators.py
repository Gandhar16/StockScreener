"""
indicators.py
=============
Fast numpy/pandas technical indicators — no TA-Lib dependency.
All functions return scalar snapshots at the latest bar unless noted.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_g = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_l = loss.ewm(com=period - 1, min_periods=period).mean()
    rs    = avg_g / avg_l.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26,
         signal: int = 9) -> Dict[str, pd.Series]:
    ema_f   = close.ewm(span=fast,   min_periods=fast).mean()
    ema_s   = close.ewm(span=slow,   min_periods=slow).mean()
    line    = ema_f - ema_s
    sig_line = line.ewm(span=signal, min_periods=signal).mean()
    hist    = line - sig_line
    return {"line": line, "signal": sig_line, "hist": hist}


def sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(period, min_periods=period).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, prev_close = df["High"], df["Low"], df["Close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def compute_indicators(df: pd.DataFrame) -> Dict:
    """
    Compute all indicators once for a price DataFrame.
    Returns a flat dict of scalar values at the latest bar.
    """
    close = df["Close"]
    n     = len(close)
    px    = float(close.iloc[-1])

    rsi_s   = rsi(close)
    macd_d  = macd(close)
    ma50_s  = sma(close, 50)
    ma200_s = sma(close, 200)
    atr_s   = atr(df)

    def _f(s: pd.Series, default=0.0) -> float:
        v = s.iloc[-1]
        return float(v) if not pd.isna(v) else default

    rsi_v    = _f(rsi_s, 50.0)
    macd_l   = _f(macd_d["line"])
    macd_sg  = _f(macd_d["signal"])
    macd_hi  = _f(macd_d["hist"])
    ma50_v   = _f(ma50_s, 0.0) or None
    ma200_v  = _f(ma200_s, 0.0) or None
    atr_v    = _f(atr_s, px * 0.02)

    # Crossover: histogram flipped sign in last bar
    prev_hist = float(macd_d["hist"].iloc[-2]) if n > 1 else 0.0
    macd_bull_cross = prev_hist < 0 and macd_hi > 0
    macd_bear_cross = prev_hist > 0 and macd_hi < 0

    above_50  = (px > ma50_v)  if ma50_v  else None
    above_200 = (px > ma200_v) if ma200_v else None

    # Volume trend: is recent volume contracting? (good for coiling patterns)
    vol_recent = float(df["Volume"].iloc[-5:].mean())  if n >= 5  else float(df["Volume"].mean())
    vol_prior  = float(df["Volume"].iloc[-20:-5].mean()) if n >= 20 else float(df["Volume"].mean())
    vol_contracting = vol_recent < vol_prior * 0.90 if vol_prior > 0 else False

    return {
        "price":            px,
        "rsi":              rsi_v,
        "macd_line":        macd_l,
        "macd_signal":      macd_sg,
        "macd_hist":        macd_hi,
        "macd_bull_cross":  macd_bull_cross,
        "macd_bear_cross":  macd_bear_cross,
        "ma50":             ma50_v,
        "ma200":            ma200_v,
        "above_50":         above_50,
        "above_200":        above_200,
        "atr":              atr_v,
        "vol_contracting":  vol_contracting,
    }


# ── Historical pattern win rates (Bulkowski / academic research) ──────────────
# These are the base reliability rates before any contextual adjustments.
# Source: Bulkowski's "Encyclopedia of Chart Patterns" + backtesting literature.

PATTERN_WIN_RATES: Dict[str, int] = {
    # Confirmed chart patterns (structure + neckline break)
    "Head & Shoulders":       74,
    "Inv Head & Shoulders":   72,
    "Double Bottom":          65,
    "Double Top":             63,
    # Continuation / breakout patterns
    "Ascending Triangle":     72,
    "Descending Triangle":    70,
    "Bull Flag":              68,
    "Bear Flag":              67,
    "Falling Wedge":          63,
    "Rising Wedge":           60,
    "VCP":                    68,
    "Symmetrical Triangle":   58,
    # Forming (not yet confirmed — slightly discounted)
    "Forming Double Bottom":  58,
    "Forming Double Top":     56,
    "Forming IH&S":           62,
    "Forming H&S":            62,
    # Multi-bar candlesticks
    "Three White Soldiers":   66,
    "Three Black Crows":      64,
    "Morning Star":           65,
    "Evening Star":           63,
    "Bullish Engulfing":      63,
    "Bearish Engulfing":      62,
    "Piercing Line":          61,
    "Dark Cloud Cover":       60,
    # Single-bar candlesticks
    "Hammer":                 55,
    "Shooting Star":          53,
    "Tweezer Bottom":         55,
    "Tweezer Top":            55,
    "Bullish Harami":         53,
    "Bearish Harami":         52,
    "Doji":                   50,
}


def score_pattern(p: dict, indicators: dict) -> int:
    """
    Composite quality score for a completed pattern (0–100).

    Components
    ──────────
    Base reliability  0–20  (from historical win rates)
    Volume            0–20  (vol_ratio vs threshold)
    Level alignment   0–15  (at key S/R zone or trendline)
    Trend alignment   0–20  (vs 200-day MA)
    RSI confirmation  0–15  (overbought/oversold alignment)
    MACD confirmation 0–10  (histogram direction + crossover)
    ───────────────────────
    Total             0–100
    """
    name      = p.get("name", "")
    is_bull   = p.get("type", "") == "bullish"
    vol_r     = p.get("vol_ratio", 0) or 0
    at_lvl    = p.get("at_level")
    win_rate  = PATTERN_WIN_RATES.get(name, 55)

    above_200 = indicators.get("above_200")
    above_50  = indicators.get("above_50")
    rsi_v     = indicators.get("rsi", 50)
    macd_hi   = indicators.get("macd_hist", 0)
    bull_x    = indicators.get("macd_bull_cross", False)
    bear_x    = indicators.get("macd_bear_cross", False)

    # 1. Base reliability (0–20): scales from 50% → 0pts, 75% → 20pts
    base = max(0.0, (win_rate - 50) / 25 * 20)

    # 2. Volume (0–20)
    if   vol_r >= 2.5: vol_s = 20
    elif vol_r >= 2.0: vol_s = 17
    elif vol_r >= 1.5: vol_s = 13
    elif vol_r >= 1.2: vol_s = 9
    elif vol_r >= 1.0: vol_s = 5
    else:              vol_s = 0

    # 3. Level alignment (0–15)
    if   at_lvl in ("@Sup Zone", "@Res Zone"): lvl_s = 15
    elif at_lvl in ("@Sup TL",   "@Res TL"):   lvl_s = 10
    else:                                       lvl_s = 0

    # 4. Trend alignment (0–20)
    if above_200 is None:
        trend_s = 10
    elif is_bull and above_200:
        trend_s = 20   # BUY with price above 200MA — fully aligned
    elif is_bull and above_50:
        trend_s = 13   # recovering — above 50 but below 200
    elif is_bull:
        trend_s = 4    # BUY in downtrend — contrarian risk
    elif not is_bull and not above_200:
        trend_s = 20   # SELL with price below 200MA — fully aligned
    elif not is_bull and not above_50:
        trend_s = 13   # weakening trend
    else:
        trend_s = 4    # SELL in uptrend — contrarian risk

    # 5. RSI (0–15)
    if is_bull:
        if   30 <= rsi_v <= 50: rsi_s = 15  # recovering from oversold
        elif 50 <  rsi_v <= 60: rsi_s = 10  # trending up, not extended
        elif         rsi_v < 30: rsi_s = 12  # very oversold — bounce fuel
        elif 60 <  rsi_v <= 70: rsi_s = 6
        else:                    rsi_s = 0   # overbought > 70
    else:
        if   50 <= rsi_v <= 70: rsi_s = 15  # rolling over from overbought
        elif 40 <= rsi_v < 50:  rsi_s = 10  # trending down
        elif         rsi_v > 70: rsi_s = 12  # very overbought — short fuel
        elif 30 <= rsi_v < 40:  rsi_s = 6
        else:                    rsi_s = 0   # oversold < 30

    # 6. MACD (0–10)
    if is_bull:
        if   bull_x:      macd_s = 10  # fresh bullish cross
        elif macd_hi > 0: macd_s = 6   # bullish momentum
        else:             macd_s = 0
    else:
        if   bear_x:      macd_s = 10  # fresh bearish cross
        elif macd_hi < 0: macd_s = 6   # bearish momentum
        else:             macd_s = 0

    total = base + vol_s + lvl_s + trend_s + rsi_s + macd_s
    return min(100, max(0, round(total)))


def forming_confidence(p: dict, df: pd.DataFrame, indicators: dict) -> dict:
    """
    Estimate probability (0–92%) that a forming pattern will complete and break out.
    Returns a dict with confidence, trigger, expected_move_pct, bars_to_trigger.
    """
    name      = p.get("name", "")
    kp        = p.get("key_prices", {})
    ptype     = p.get("type", "neutral")
    is_bull   = ptype == "bullish"

    px        = indicators.get("price", float(df["Close"].iloc[-1]))
    atr_v     = indicators.get("atr",   px * 0.02)
    above_200 = indicators.get("above_200")
    above_50  = indicators.get("above_50")
    rsi_v     = indicators.get("rsi", 50)
    macd_hi   = indicators.get("macd_hist", 0)
    vol_cont  = indicators.get("vol_contracting", False)

    base = float(PATTERN_WIN_RATES.get(name, 55))
    adj  = 0.0

    # ── Trend alignment ──────────────────────────────────────────────────────
    if is_bull:
        if above_200:          adj += 8
        elif above_50:         adj += 3
        else:                  adj -= 15
    else:
        if not above_200:      adj += 8
        elif not above_50:     adj += 3
        else:                  adj -= 15

    # ── RSI position ─────────────────────────────────────────────────────────
    if is_bull:
        if   35 <= rsi_v <= 55: adj += 7   # neutral — fuel left
        elif rsi_v < 35:        adj += 5   # oversold — extra bounce fuel
        elif 55 < rsi_v <= 65:  adj += 2
        else:                   adj -= 8   # overbought — little room
    else:
        if   45 <= rsi_v <= 65: adj += 7
        elif rsi_v > 65:        adj += 5
        elif 35 <= rsi_v < 45:  adj += 2
        else:                   adj -= 8

    # ── MACD alignment ───────────────────────────────────────────────────────
    if   is_bull  and macd_hi > 0: adj += 5
    elif not is_bull and macd_hi < 0: adj += 5
    else:                          adj -= 3

    # ── Volume contraction (coiling = good for forming patterns) ─────────────
    if vol_cont: adj += 6

    # ── Completion trigger + proximity bonus ─────────────────────────────────
    resistance = kp.get("resistance") or kp.get("neckline")
    support    = kp.get("support")    or kp.get("neckline")

    trigger       = resistance if is_bull else support
    expected_move = 0.0
    bars_to_trig  = None

    if trigger and trigger > 0:
        dist = abs(trigger - px)
        bars_to_trig = max(1, round(dist / atr_v)) if atr_v > 0 else None

        # Height projection: pattern height / trigger price
        if is_bull and support:
            height = trigger - support
        elif not is_bull and resistance:
            height = resistance - trigger
        else:
            height = px * 0.07  # fallback ~7%
        expected_move = max(0.0, height / trigger)

        dist_pct = dist / px if px > 0 else 0.1
        if   dist_pct < 0.02: adj += 8   # within 2% — imminent breakout
        elif dist_pct < 0.05: adj += 4   # within 5%

    # ── Triangle apex proximity ───────────────────────────────────────────────
    bars_to_apex = p.get("bars_to_apex")
    if bars_to_apex is not None:
        if   bars_to_apex <= 5:  adj += 8
        elif bars_to_apex <= 15: adj += 4

    conf = max(10, min(92, round(base + adj)))
    return {
        "forming_confidence":  conf,
        "completion_trigger":  round(trigger, 4) if trigger else None,
        "expected_move_pct":   round(expected_move * 100, 1),
        "bars_to_trigger":     bars_to_trig,
    }
