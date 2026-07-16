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


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, min_periods=period).mean()


def bollinger(close: pd.Series, period: int = 20,
              num_std: float = 2.0) -> Dict[str, pd.Series]:
    mid   = close.rolling(period, min_periods=period).mean()
    std   = close.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    bandwidth = (upper - lower) / mid.replace(0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0, np.nan)
    return {"mid": mid, "upper": upper, "lower": lower,
            "bandwidth": bandwidth, "percent_b": percent_b}


def bollinger_squeeze(bandwidth: pd.Series, lookback: int = 120) -> Optional[bool]:
    """True when current bandwidth sits in the lowest decile of the lookback
    window — volatility compression that often precedes an expansion move."""
    bw = bandwidth.dropna()
    if len(bw) < lookback // 2:
        return None
    window = bw.iloc[-lookback:]
    return bool(bw.iloc[-1] <= window.quantile(0.10))


def adx(df: pd.DataFrame, period: int = 14) -> Dict[str, pd.Series]:
    """ADX with +DI/−DI using Wilder smoothing (ewm alpha=1/period)."""
    high, low, close = df["High"], df["Low"], df["Close"]
    up   = high.diff()
    down = -low.diff()
    plus_dm  = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
    tr = pd.concat(
        [high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    alpha = 1.0 / period
    atr_w = tr.ewm(alpha=alpha, min_periods=period).mean()
    plus_di  = 100 * plus_dm.ewm(alpha=alpha, min_periods=period).mean() / atr_w.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=alpha, min_periods=period).mean() / atr_w.replace(0, np.nan)
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_s = dx.ewm(alpha=alpha, min_periods=period).mean()
    return {"adx": adx_s, "plus_di": plus_di, "minus_di": minus_di}


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3,
               smooth: int = 3) -> Dict[str, pd.Series]:
    low_k  = df["Low"].rolling(k, min_periods=k).min()
    high_k = df["High"].rolling(k, min_periods=k).max()
    raw_k  = 100 * (df["Close"] - low_k) / (high_k - low_k).replace(0, np.nan)
    k_s = raw_k.rolling(smooth, min_periods=smooth).mean()
    d_s = k_s.rolling(d, min_periods=d).mean()
    return {"k": k_s, "d": d_s}


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def obv_trend(obv_s: pd.Series, lookback: int = 20) -> Optional[str]:
    """Classify OBV as rising / falling / flat via normalized linreg slope."""
    seg = obv_s.dropna().iloc[-lookback:]
    if len(seg) < lookback:
        return None
    x = np.arange(len(seg), dtype=float)
    slope = np.polyfit(x, seg.values.astype(float), 1)[0]
    scale = seg.abs().mean() or 1.0
    norm = slope * lookback / scale
    if norm > 0.02:
        return "rising"
    if norm < -0.02:
        return "falling"
    return "flat"


def rvol(volume: pd.Series, lookback: int = 20) -> Optional[float]:
    """Relative volume: latest bar vs prior lookback average."""
    if len(volume) < lookback + 1:
        return None
    prior = float(volume.iloc[-(lookback + 1):-1].mean())
    if prior <= 0:
        return None
    return float(volume.iloc[-1]) / prior


def pct_from_52w_high(close: pd.Series) -> Optional[float]:
    """Percent below the 52-week (252-bar) high; 0.0 = at the high."""
    window = close.iloc[-252:] if len(close) >= 60 else None
    if window is None:
        return None
    hi = float(window.max())
    if hi <= 0:
        return None
    return (hi - float(close.iloc[-1])) / hi * 100.0


def ema_stack(close: pd.Series) -> Dict:
    """20/50/200 EMA alignment + normalized 20-bar slope of the 50 EMA."""
    e20, e50, e200 = ema(close, 20), ema(close, 50), ema(close, 200)

    def _last(s):
        v = s.iloc[-1] if len(s) else np.nan
        return float(v) if not pd.isna(v) else None

    v20, v50, v200 = _last(e20), _last(e50), _last(e200)
    px = float(close.iloc[-1])
    stacked_bull = (v20 is not None and v50 is not None and v200 is not None
                    and px > v20 > v50 > v200)
    stacked_bear = (v20 is not None and v50 is not None and v200 is not None
                    and px < v20 < v50 < v200)
    slope = None
    seg = e50.dropna().iloc[-20:]
    if len(seg) == 20:
        x = np.arange(20, dtype=float)
        raw = np.polyfit(x, seg.values.astype(float), 1)[0]
        slope = raw * 20 / (float(seg.mean()) or 1.0)  # ≈ pct change over 20 bars
    return {"ema20": v20, "ema50": v50, "ema200": v200,
            "stacked_bull": stacked_bull, "stacked_bear": stacked_bear,
            "ema50_slope": slope}


def rsi_divergence(close: pd.Series, rsi_s: pd.Series,
                   lookback: int = 60, order: int = 5) -> Optional[str]:
    """
    Detect classic RSI divergence over the lookback window.
    'bearish': price makes a higher high while RSI makes a lower high.
    'bullish': price makes a lower low while RSI makes a higher low.
    Returns None when there is no divergence or not enough data.
    """
    c = close.dropna().iloc[-lookback:]
    r = rsi_s.reindex(c.index)
    if len(c) < lookback // 2:
        return None

    vals = c.values.astype(float)
    highs, lows = [], []
    for i in range(order, len(vals) - order):
        seg = vals[i - order:i + order + 1]
        if vals[i] == seg.max() and (seg == vals[i]).sum() == 1:
            highs.append(i)
        if vals[i] == seg.min() and (seg == vals[i]).sum() == 1:
            lows.append(i)

    if len(highs) >= 2:
        i1, i2 = highs[-2], highs[-1]
        if vals[i2] > vals[i1] and float(r.iloc[i2]) < float(r.iloc[i1]) - 1e-9:
            return "bearish"
    if len(lows) >= 2:
        i1, i2 = lows[-2], lows[-1]
        if vals[i2] < vals[i1] and float(r.iloc[i2]) > float(r.iloc[i1]) + 1e-9:
            return "bullish"
    return None


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

    # ── Extended indicator set (all additive; None when history too short) ────
    def _opt(s: pd.Series) -> Optional[float]:
        if len(s) == 0:
            return None
        v = s.iloc[-1]
        return float(v) if not pd.isna(v) else None

    bb    = bollinger(close)
    adx_d = adx(df)
    st    = stochastic(df)
    obv_s = obv(close, df["Volume"])
    stack = ema_stack(close)

    adx_v = _opt(adx_d["adx"])
    if adx_v is None:
        trend_strength = None
    elif adx_v >= 25:
        trend_strength = "strong"
    elif adx_v >= 20:
        trend_strength = "moderate"
    else:
        trend_strength = "weak"

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
        # ── additive keys (V3 trader upgrade) ──
        "bb_percent_b":       _opt(bb["percent_b"]),
        "bb_squeeze":         bollinger_squeeze(bb["bandwidth"]),
        "adx":                adx_v,
        "plus_di":            _opt(adx_d["plus_di"]),
        "minus_di":           _opt(adx_d["minus_di"]),
        "trend_strength":     trend_strength,
        "stoch_k":            _opt(st["k"]),
        "stoch_d":            _opt(st["d"]),
        "obv_trend":          obv_trend(obv_s),
        "rvol":               rvol(df["Volume"]),
        "pct_from_52w_high":  pct_from_52w_high(close),
        "ema20":              stack["ema20"],
        "ema50":              stack["ema50"],
        "ema200":             stack["ema200"],
        "ema_stack_bull":     stack["stacked_bull"],
        "ema_stack_bear":     stack["stacked_bear"],
        "ema50_slope":        stack["ema50_slope"],
        "rsi_divergence":     rsi_divergence(close, rsi_s),
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
