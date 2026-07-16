"""
trade_quality.py
================
Trade-quality gates a professional applies before taking any setup:

- Stop selection: the tighter of the pattern's structural stop and an
  ATR-based stop, guarded against being inside market noise (< 2% by
  default) and clamped at a max risk per share (10%).
- Explicit risk:reward computation and tiered gating.
- Fixed-fractional position sizing: risk a fixed % of capital per trade,
  sized off the actual stop distance, with a notional cap per position.
- Composite "trade setup score": how a trader triages a watchlist —
  pattern quality, weekly-trend alignment, relative strength, volume
  confirmation, and risk:reward, weighted and renormalized when a
  component is unavailable.
"""

from typing import Dict, Optional

import pandas as pd

DEFAULT_SETUP_WEIGHTS = {
    "pattern": 0.35,
    "mtf":     0.20,
    "rs":      0.15,
    "volume":  0.15,
    "rr":      0.15,
}

SETUP_GRADES = [(80, "A+"), (70, "A"), (58, "B"), (45, "C")]


def choose_stop(entry: float, pattern_stop: Optional[float], atr: Optional[float],
                direction: str = "bullish", atr_mult: float = 2.0,
                min_stop_pct: float = 0.02, max_stop_pct: float = 0.10) -> Dict:
    """
    Pick the working stop: the tighter of the structural (pattern) stop and
    an ATR stop — but never inside min_stop_pct of entry (noise guard), and
    never wider than max_stop_pct (risk guard).

    Returns {stop, stop_source, stop_pct} (stop_pct as a fraction of entry).
    """
    if entry is None or entry <= 0:
        return {"stop": None, "stop_source": None, "stop_pct": None}

    is_bull = direction == "bullish"
    candidates = []

    if pattern_stop is not None and pattern_stop > 0:
        valid = pattern_stop < entry if is_bull else pattern_stop > entry
        if valid:
            candidates.append((abs(entry - pattern_stop) / entry, pattern_stop, "pattern"))

    if atr is not None and atr > 0:
        atr_stop = entry - atr_mult * atr if is_bull else entry + atr_mult * atr
        if atr_stop > 0:
            candidates.append((abs(entry - atr_stop) / entry, atr_stop, "atr"))

    if not candidates:
        return {"stop": None, "stop_source": None, "stop_pct": None}

    # Tightest stop that still respects the noise guard; if all are inside
    # the noise band, widen to exactly min_stop_pct.
    candidates.sort(key=lambda c: c[0])
    dist_pct, stop, source = next(
        (c for c in candidates if c[0] >= min_stop_pct), candidates[-1]
    )
    if dist_pct < min_stop_pct:
        dist_pct = min_stop_pct
        stop = entry * (1 - min_stop_pct) if is_bull else entry * (1 + min_stop_pct)
        source = f"{source}+noise_guard"
    if dist_pct > max_stop_pct:
        dist_pct = max_stop_pct
        stop = entry * (1 - max_stop_pct) if is_bull else entry * (1 + max_stop_pct)
        source = f"{source}+clamped"

    return {"stop": round(stop, 4), "stop_source": source,
            "stop_pct": round(dist_pct, 4)}


def risk_reward(entry: float, stop: Optional[float], target: Optional[float],
                direction: str = "bullish") -> Optional[float]:
    """Reward-per-unit-risk. None when inputs are missing or degenerate."""
    if not entry or stop is None or target is None:
        return None
    if direction == "bullish":
        risk, reward = entry - stop, target - entry
    else:
        risk, reward = stop - entry, entry - target
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 2)


def passes_rr_gate(rr: Optional[float], min_rr: float = 2.0) -> Optional[bool]:
    """None (pass-through) when R:R could not be computed."""
    if rr is None:
        return None
    return rr >= min_rr


def position_size(capital: float, risk_pct: float, entry: float,
                  stop: Optional[float],
                  max_position_pct: float = 0.15) -> Dict:
    """
    Fixed-fractional sizing: shares = (capital * risk_pct) / per-share risk,
    capped so the position notional never exceeds max_position_pct of capital.

    Returns {shares, position_value, capital_at_risk, capped}.
    """
    empty = {"shares": 0, "position_value": 0.0, "capital_at_risk": 0.0,
             "capped": False}
    if capital <= 0 or entry is None or entry <= 0 or stop is None:
        return empty
    per_share_risk = abs(entry - stop)
    if per_share_risk <= 0:
        return empty

    shares = int((capital * risk_pct) / per_share_risk)
    capped = False
    max_notional = capital * max_position_pct
    if shares * entry > max_notional:
        shares = int(max_notional / entry)
        capped = True
    if shares <= 0:
        return {**empty, "capped": capped}

    return {
        "shares": shares,
        "position_value": round(shares * entry, 2),
        "capital_at_risk": round(shares * per_share_risk, 2),
        "capped": capped,
    }


def _volume_component(indicators: Dict, pattern: Optional[Dict] = None) -> Optional[float]:
    """0-100 volume-confirmation score from rvol, OBV trend and the pattern's
    own volume confirmation. None when nothing is measurable."""
    parts = []

    rvol_v = indicators.get("rvol")
    if rvol_v is not None:
        if rvol_v >= 2.0:
            parts.append(100)
        elif rvol_v >= 1.5:
            parts.append(80)
        elif rvol_v >= 1.0:
            parts.append(55)
        else:
            parts.append(25)

    obv_t = indicators.get("obv_trend")
    if obv_t is not None:
        parts.append({"rising": 100, "flat": 50, "falling": 0}.get(obv_t, 50))

    vol_r = (pattern or {}).get("vol_ratio")
    if vol_r:
        parts.append(min(100, vol_r / 2.5 * 100))

    if not parts:
        return None
    return sum(parts) / len(parts)


def _rr_component(rr: Optional[float]) -> Optional[float]:
    if rr is None:
        return None
    if rr >= 3.0:
        return 100.0
    if rr <= 1.0:
        return 0.0
    return (rr - 1.0) / 2.0 * 100.0  # linear 1:1→0, 3:1→100


def setup_score(pattern_score: Optional[float],
                mtf: Optional[Dict] = None,
                rs: Optional[Dict] = None,
                indicators: Optional[Dict] = None,
                rr: Optional[float] = None,
                pattern: Optional[Dict] = None,
                config: Optional[Dict] = None) -> Dict:
    """
    Composite 0-100 trade setup score.

    Components (weights renormalized over what is available):
      pattern  — existing score_pattern() 0-100
      mtf      — mtf_alignment()["mtf_score"]
      rs       — Mansfield RS mapped to 0-100 (−20→0, 0→50, +20→100)
      volume   — rvol + OBV trend + pattern volume ratio
      rr       — risk:reward mapped to 0-100 (1:1→0, 3:1→100)

    Returns {setup_score, setup_grade, components, missing}.
    """
    weights = dict(DEFAULT_SETUP_WEIGHTS, **((config or {}).get("weights", {})))
    indicators = indicators or {}

    rs_m = (rs or {}).get("rs_mansfield")
    rs_component = None
    if rs_m is not None:
        rs_component = max(0.0, min(100.0, (rs_m + 20.0) / 40.0 * 100.0))

    components = {
        "pattern": float(pattern_score) if pattern_score is not None else None,
        "mtf":     (mtf or {}).get("mtf_score"),
        "rs":      rs_component,
        "volume":  _volume_component(indicators, pattern),
        "rr":      _rr_component(rr),
    }

    earned, available = 0.0, 0.0
    missing = []
    for name, value in components.items():
        w = weights.get(name, 0.0)
        if value is None:
            missing.append(name)
            continue
        earned += value * w
        available += w

    if available <= 0:
        return {"setup_score": None, "setup_grade": None,
                "components": components, "missing": missing}

    score = round(earned / available)
    grade = "D"
    for threshold, label in SETUP_GRADES:
        if score >= threshold:
            grade = label
            break

    return {"setup_score": score, "setup_grade": grade,
            "components": components, "missing": missing}


def enrich_trade_signal(sig: Dict, df: pd.DataFrame, ticker: str,
                        indicators: Dict,
                        bench_close: Optional[pd.Series] = None,
                        fetch_benchmark: bool = True,
                        config: Optional[Dict] = None) -> Dict:
    """
    Enrich a best-signal dict (in place) with the full trader-grade context:

      - ATR-vs-pattern stop selection (original kept as `pattern_stop`,
        `stop_loss` and `risk_reward` recomputed off the chosen stop)
      - weekly multi-timeframe alignment (`mtf_score`, `mtf_aligned`)
      - Mansfield relative strength vs benchmark (`rs_mansfield`, `rs_trend`,
        `rs_pass`)
      - composite `setup_score` / `setup_grade`
      - fixed-fractional `position_shares` / `position_value` / `capital_at_risk`

    All additions are additive keys; every data gap degrades to None.
    Returns the same dict for convenience.
    """
    from .mtf import analyze_mtf
    from .relative_strength import (benchmark_for, fetch_benchmark_history,
                                    mansfield_rs, rs_gate)

    cfg = config or {}
    direction = "bullish" if sig.get("type") == "bullish" or \
        sig.get("signal") in ("BUY", "BUY?", "WATCH-LONG") else "bearish"

    entry = sig.get("entry_price")
    target = sig.get("t1") or sig.get("swing_target")

    # 1. Stop selection (pattern vs ATR, noise-guarded, clamped)
    gates = cfg.get("gates", {})
    stop_res = choose_stop(
        entry, sig.get("stop_loss"), indicators.get("atr"), direction,
        atr_mult=gates.get("atr_stop_mult", 2.0),
        min_stop_pct=gates.get("min_stop_pct", 0.02),
        max_stop_pct=gates.get("max_stop_pct", 0.10),
    )
    if stop_res["stop"] is not None:
        sig["pattern_stop"] = sig.get("stop_loss")
        sig["stop_loss"] = stop_res["stop"]
        sig["stop_source"] = stop_res["stop_source"]
        sig["stop_pct"] = stop_res["stop_pct"]
        rr = risk_reward(entry, stop_res["stop"], target, direction)
        if rr is not None:
            sig["risk_reward"] = rr

    # 2. Weekly multi-timeframe alignment
    try:
        mtf_res = analyze_mtf(df, direction, cfg.get("mtf"))
    except Exception:
        mtf_res = {"mtf_score": None, "mtf_aligned": None, "mtf_reasons": []}
    sig["mtf_score"] = mtf_res.get("mtf_score")
    sig["mtf_aligned"] = mtf_res.get("mtf_aligned")
    sig["mtf_reasons"] = mtf_res.get("mtf_reasons")

    # 3. Relative strength vs benchmark
    rs = {"rs_mansfield": None, "rs_trend": None,
          "rs_line_slope_20d": None, "rs_new_high": None}
    try:
        if bench_close is None and fetch_benchmark:
            bench_close = fetch_benchmark_history(
                benchmark_for(ticker, cfg.get("rs", {}).get("benchmark_map")),
                period=cfg.get("history_period", "2y"),
            )
        if bench_close is not None:
            rs = mansfield_rs(df["Close"], bench_close)
    except Exception:
        pass
    gate = rs_gate(direction, rs,
                   soft_floor=cfg.get("rs", {}).get("soft_floor", -5.0),
                   hard_floor=cfg.get("rs", {}).get("hard_floor", -20.0))
    sig["rs_mansfield"] = rs.get("rs_mansfield")
    sig["rs_trend"] = rs.get("rs_trend")
    sig["rs_new_high"] = rs.get("rs_new_high")
    sig["rs_pass"] = gate.get("rs_pass")
    sig["rs_reason"] = gate.get("rs_reason")

    # 4. Composite setup score
    ss = setup_score(sig.get("pattern_score"), mtf_res, rs, indicators,
                     sig.get("risk_reward"), sig, cfg.get("setup_score"))
    sig["setup_score"] = ss["setup_score"]
    sig["setup_grade"] = ss["setup_grade"]
    sig["setup_components"] = ss["components"]

    # 5. Position sizing off the final stop
    ps = position_size(
        gates.get("account_size", 100_000.0),
        gates.get("risk_per_trade_pct", 0.01),
        entry, sig.get("stop_loss"),
        max_position_pct=gates.get("max_position_pct", 0.15),
    )
    sig["position_shares"] = ps["shares"]
    sig["position_value"] = ps["position_value"]
    sig["capital_at_risk"] = ps["capital_at_risk"]

    # Extra context a trader glances at
    sig["rvol"] = indicators.get("rvol")
    sig["trend_strength"] = indicators.get("trend_strength")
    sig["rsi_divergence"] = indicators.get("rsi_divergence")
    return sig
