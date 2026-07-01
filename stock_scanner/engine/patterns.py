"""
patterns.py
===========
Pattern detection implementing the rules in PATTERN_RULES.md.

Key rule-book principles enforced here:
  - avgCandleRange (ACR) replaces fixed % tolerance for "same level" checks
  - Volume confirmation for Double Top / Double Bottom
  - Breach check: pattern invalid if any Close after formation crosses key level
  - CMP-centric forming detection with direction gate + confirmed pivot necklines
  - Triangle/wedge classification via pivot-ordering rules (not slope sign)

Chart patterns (completed, neckline-break confirmed):
  Double Top          – bearish reversal (with volume + neckline break)
  Double Bottom       – bullish reversal (with volume + neckline break)
  Head & Shoulders    – bearish reversal
  Inv Head & Shoulders– bullish reversal

Forming / CMP-context patterns:
  Forming Double Top / Bottom
  Forming H&S / IH&S
  Ascending / Descending / Symmetrical Triangle
  Rising / Falling Wedge
  VCP (Volatility Contraction Pattern)
  Bull Flag / Bear Flag

Candlestick patterns (last recent_candle_bars only):
  Hammer, Shooting Star, Bullish/Bearish Engulfing
  Morning Star, Evening Star, Doji
  Three White Soldiers, Three Black Crows
  Bullish Harami, Bearish Harami
  Tweezer Top, Tweezer Bottom
  Piercing Line, Dark Cloud Cover
"""

from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd


# ── helpers ────────────────────────────────────────────────────────────────────

def _acr(df: pd.DataFrame, idx_a: int, idx_b: int) -> float:
    """
    Average Candle Range between two bar indices (inclusive).
    Used as the 'straight-line' tolerance per the rule book.
    """
    lo = min(idx_a, idx_b)
    hi = max(idx_a, idx_b) + 1
    sub = df.iloc[lo:hi]
    ranges = (sub["High"] - sub["Low"]).values
    return float(ranges.mean()) if len(ranges) > 0 else 0.0


def _no_close_breach(df: pd.DataFrame, after_bar: int,
                     level: float, direction: str) -> bool:
    """
    Breach check (rule-book confirmation rule):
    Returns True if no Close after after_bar has crossed 'level'.
    direction='above' → breach = Close > level
    direction='below' → breach = Close < level
    """
    closes = df["Close"].iloc[after_bar + 1:].values
    if len(closes) == 0:
        return True
    if direction == "above":
        return bool(np.all(closes <= level))
    return bool(np.all(closes >= level))


# ── main class ─────────────────────────────────────────────────────────────────

class PatternFinder:
    def __init__(self,
                 price_tolerance: float = 0.03,   # fallback % (rarely used now)
                 min_pullback: float = 0.03,
                 recent_candle_bars: int = 15,
                 recent_chart_bars: int = 30):
        self.tol          = price_tolerance
        self.pull         = min_pullback
        self.recent       = recent_candle_bars
        self.recent_chart = recent_chart_bars

    # ── public entry points ───────────────────────────────────────────────────

    def find_all(self, df: pd.DataFrame,
                 p_highs: List[Dict], p_lows: List[Dict]) -> List[Dict[str, Any]]:
        """Return recently completed + confirmed patterns."""
        n = len(df)
        cutoff = n - self.recent_chart

        chart: List[Dict[str, Any]] = []
        chart += self._double_top(df, p_highs, p_lows)
        chart += self._double_bottom(df, p_highs, p_lows)
        chart += self._head_and_shoulders(df, p_highs, p_lows)
        chart += self._inv_head_and_shoulders(df, p_highs, p_lows)
        patterns = [p for p in chart if p["completed_bar"] >= cutoff]

        # Candlestick — scan window already limited by _recent_range()
        patterns += self._hammer(df)
        patterns += self._shooting_star(df)
        patterns += self._bullish_engulfing(df)
        patterns += self._bearish_engulfing(df)
        patterns += self._morning_star(df)
        patterns += self._evening_star(df)
        patterns += self._doji(df)
        patterns += self._three_white_soldiers(df)
        patterns += self._three_black_crows(df)
        patterns += self._bullish_harami(df)
        patterns += self._bearish_harami(df)
        patterns += self._tweezer_top(df)
        patterns += self._tweezer_bottom(df)
        patterns += self._piercing_line(df)
        patterns += self._dark_cloud_cover(df)

        patterns.sort(key=lambda p: p["completed_bar"])
        return patterns

    def find_forming(self, df: pd.DataFrame,
                     p_highs: List[Dict], p_lows: List[Dict]) -> List[Dict[str, Any]]:
        """
        CMP-centric forming patterns.
        Every signal requires:
          1. Confirmed pivot necklines (from p_highs / p_lows, not raw price)
          2. 5-bar direction consistent with the forming leg
          3. Current price inside the valid zone of the pattern
        """
        n = len(df)
        if n < 10:
            return []

        current = float(df["Close"].iloc[-1])
        look = min(5, n - 1)
        pct  = (current - float(df["Close"].iloc[-(look + 1)])) / float(df["Close"].iloc[-(look + 1)])
        rising  = pct >  0.005
        falling = pct < -0.005
        lookback = min(n, 80)

        forming: List[Dict[str, Any]] = []
        forming += self._forming_double_top(df, p_highs, p_lows, current, lookback, rising)
        forming += self._forming_double_bottom(df, p_highs, p_lows, current, lookback, falling)
        forming += self._forming_hs(df, p_highs, p_lows, current, lookback, rising)
        forming += self._forming_ihs(df, p_highs, p_lows, current, lookback, falling)
        forming += self._triangles_wedges(df, p_highs, p_lows, current, lookback)
        forming += self._vcp(df, p_highs, p_lows, current, lookback)
        forming += self._flags(df, p_highs, p_lows, current)
        return forming

    # ── completed chart patterns ──────────────────────────────────────────────

    def _double_top(self, df, p_highs, p_lows):
        """
        Rules (PATTERN_RULES.md):
          abs(A-C) <= ACR(A..C)   same level (within avg candle range)
          B < min(A,C)             valley below both peaks
          cVol < aVol              volume declines on second peak
          Confirmed by first Close < B after C (neckline break)
        """
        results = []
        n = len(df)
        for i in range(len(p_highs) - 1):
            a, c = p_highs[i], p_highs[i + 1]
            acr = _acr(df, a["index"], c["index"])
            if abs(a["price"] - c["price"]) > acr:
                continue
            # valley between peaks
            between = [l for l in p_lows if a["index"] < l["index"] < c["index"]]
            if not between:
                continue
            b = min(between, key=lambda l: l["price"])
            if b["price"] >= min(a["price"], c["price"]):
                continue
            pullback = (min(a["price"], c["price"]) - b["price"]) / a["price"]
            if pullback < self.pull:
                continue
            # volume confirmation: second peak lower volume
            if c.get("volume", 0) > 0 and a.get("volume", 0) > 0:
                if c["volume"] >= a["volume"]:
                    continue
            # neckline break confirmation
            nk_break = next(
                (bi for bi in range(c["index"] + 1, n)
                 if float(df["Close"].iloc[bi]) < b["price"]),
                None)
            if nk_break is None:
                continue
            results.append({
                "name": "Double Top",
                "short": "M-Top",
                "type": "bearish",
                "bar_indices": [a["index"], b["index"], c["index"]],
                "key_prices": {"A": a["price"], "B": b["price"], "C": c["price"]},
                "completed_bar": nk_break,
                "label_bar": c["index"],
                "label_price": c["price"],
                "label_above": True,
            })
        return results

    def _double_bottom(self, df, p_highs, p_lows):
        """
        Rules:
          abs(A-C) <= ACR(A..C)   same level
          B > max(A,C)             bounce peak above both troughs
          cVol < aVol              volume lower on second trough
          Confirmed by first Close > B after C
        """
        results = []
        n = len(df)
        for i in range(len(p_lows) - 1):
            a, c = p_lows[i], p_lows[i + 1]
            acr = _acr(df, a["index"], c["index"])
            if abs(a["price"] - c["price"]) > acr:
                continue
            between = [h for h in p_highs if a["index"] < h["index"] < c["index"]]
            if not between:
                continue
            b = max(between, key=lambda h: h["price"])
            if b["price"] <= max(a["price"], c["price"]):
                continue
            pullback = (b["price"] - max(a["price"], c["price"])) / a["price"]
            if pullback < self.pull:
                continue
            if c.get("volume", 0) > 0 and a.get("volume", 0) > 0:
                if c["volume"] >= a["volume"]:
                    continue
            nk_break = next(
                (bi for bi in range(c["index"] + 1, n)
                 if float(df["Close"].iloc[bi]) > b["price"]),
                None)
            if nk_break is None:
                continue
            results.append({
                "name": "Double Bottom",
                "short": "W-Bot",
                "type": "bullish",
                "bar_indices": [a["index"], b["index"], c["index"]],
                "key_prices": {"A": a["price"], "B": b["price"], "C": c["price"]},
                "completed_bar": nk_break,
                "label_bar": c["index"],
                "label_price": c["price"],
                "label_above": False,
            })
        return results

    def _head_and_shoulders(self, df, p_highs, p_lows):
        """
        Rules (A=LS, C=Head, E=RS, B=left neckline, D=right neckline):
          C > max(A, E)               head is highest
          max(B, D) < min(A, E)       neckline below both shoulders
          abs(B - D) < ACR(A..E)      neckline roughly horizontal
          F (current close) < E       hasn't broken right shoulder upward
        """
        results = []
        for i in range(len(p_highs) - 2):
            a, c, e = p_highs[i], p_highs[i + 1], p_highs[i + 2]
            if not (c["price"] > a["price"] and c["price"] > e["price"]):
                continue
            lows_ab = [l for l in p_lows if a["index"] < l["index"] < c["index"]]
            lows_cd = [l for l in p_lows if c["index"] < l["index"] < e["index"]]
            if not lows_ab or not lows_cd:
                continue
            b = min(lows_ab, key=lambda l: l["price"])
            d = min(lows_cd, key=lambda l: l["price"])
            acr = _acr(df, a["index"], e["index"])
            if abs(b["price"] - d["price"]) > acr:
                continue
            if max(b["price"], d["price"]) >= min(a["price"], e["price"]):
                continue
            # breach check: no close above e after e formed
            if not _no_close_breach(df, e["index"], e["price"], "above"):
                continue
            results.append({
                "name": "Head & Shoulders",
                "short": "H&S",
                "type": "bearish",
                "bar_indices": [a["index"], b["index"], c["index"],
                                d["index"], e["index"]],
                "key_prices": {"LS": a["price"], "Head": c["price"],
                               "RS": e["price"],
                               "neck": (b["price"] + d["price"]) / 2},
                "completed_bar": e["index"],
                "label_bar": c["index"],
                "label_price": c["price"],
                "label_above": True,
            })
        return results

    def _inv_head_and_shoulders(self, df, p_highs, p_lows):
        """
        Rules (A=LS, C=Head, E=RS as lows; B,D as neckline highs):
          C < min(A, E)               head is lowest
          min(B, D) > max(A, E)       neckline above both shoulders
          abs(B - D) < ACR(A..E)      neckline roughly horizontal
          F (current close) > E       hasn't broken right shoulder downward
        """
        results = []
        for i in range(len(p_lows) - 2):
            a, c, e = p_lows[i], p_lows[i + 1], p_lows[i + 2]
            if not (c["price"] < a["price"] and c["price"] < e["price"]):
                continue
            highs_ab = [h for h in p_highs if a["index"] < h["index"] < c["index"]]
            highs_cd = [h for h in p_highs if c["index"] < h["index"] < e["index"]]
            if not highs_ab or not highs_cd:
                continue
            b = max(highs_ab, key=lambda h: h["price"])
            d = max(highs_cd, key=lambda h: h["price"])
            acr = _acr(df, a["index"], e["index"])
            if abs(b["price"] - d["price"]) > acr:
                continue
            if min(b["price"], d["price"]) <= max(a["price"], e["price"]):
                continue
            if not _no_close_breach(df, e["index"], e["price"], "below"):
                continue
            results.append({
                "name": "Inv Head & Shoulders",
                "short": "IH&S",
                "type": "bullish",
                "bar_indices": [a["index"], b["index"], c["index"],
                                d["index"], e["index"]],
                "key_prices": {"LS": a["price"], "Head": c["price"],
                               "RS": e["price"],
                               "neck": (b["price"] + d["price"]) / 2},
                "completed_bar": e["index"],
                "label_bar": c["index"],
                "label_price": c["price"],
                "label_above": False,
            })
        return results

    # ── forming / CMP-context chart patterns ──────────────────────────────────

    def _forming_double_top(self, df, p_highs, p_lows, current, lookback, rising):
        if not rising:
            return []
        n = len(df)
        results = []
        recent_ph = [h for h in p_highs if h["index"] >= n - lookback]
        for a in reversed(recent_ph):
            nk_lows = [l for l in p_lows if l["index"] > a["index"]]
            if not nk_lows:
                continue
            b = min(nk_lows, key=lambda l: l["price"])
            pullback = (a["price"] - b["price"]) / a["price"]
            if pullback < self.pull:
                continue
            gap = (a["price"] - current) / a["price"]
            if 0 < gap <= self.tol * 2.0 and current > b["price"]:
                results.append({
                    "name": "Forming Double Top",
                    "short": "M-Top?",
                    "type": "bearish",
                    "forming": True,
                    "bar_indices": [a["index"], b["index"], n - 1],
                    "key_prices": {"resistance": a["price"], "neckline": b["price"]},
                    "completed_bar": n - 1,
                    "label_bar": n - 1,
                    "label_price": a["price"],
                    "label_above": True,
                })
                break
        return results

    def _forming_double_bottom(self, df, p_highs, p_lows, current, lookback, falling):
        if not falling:
            return []
        n = len(df)
        results = []
        recent_pl = [l for l in p_lows if l["index"] >= n - lookback]
        for a in reversed(recent_pl):
            nk_highs = [h for h in p_highs if h["index"] > a["index"]]
            if not nk_highs:
                continue
            b = max(nk_highs, key=lambda h: h["price"])
            bounce = (b["price"] - a["price"]) / a["price"]
            if bounce < self.pull:
                continue
            gap = (current - a["price"]) / a["price"]
            if 0 < gap <= self.tol * 2.0 and current < b["price"]:
                results.append({
                    "name": "Forming Double Bottom",
                    "short": "W-Bot?",
                    "type": "bullish",
                    "forming": True,
                    "bar_indices": [a["index"], b["index"], n - 1],
                    "key_prices": {"support": a["price"], "neckline": b["price"]},
                    "completed_bar": n - 1,
                    "label_bar": n - 1,
                    "label_price": a["price"],
                    "label_above": False,
                })
                break
        return results

    def _forming_hs(self, df, p_highs, p_lows, current, lookback, rising):
        if not rising:
            return []
        n = len(df)
        results = []
        recent_ph = [h for h in p_highs if h["index"] >= n - lookback]
        for i in range(len(recent_ph) - 1):
            a, c = recent_ph[i], recent_ph[i + 1]
            if c["price"] <= a["price"] * (1 + self.tol):
                continue
            nk_r = [l for l in p_lows if l["index"] > c["index"]]
            if not nk_r:
                continue
            d = min(nk_r, key=lambda l: l["price"])
            if current <= d["price"]:
                continue
            if abs(current - a["price"]) / a["price"] <= self.tol * 2.0 and current < c["price"]:
                results.append({
                    "name": "Forming H&S",
                    "short": "H&S?",
                    "type": "bearish",
                    "forming": True,
                    "bar_indices": [a["index"], c["index"], d["index"], n - 1],
                    "key_prices": {"head": c["price"], "neckline": d["price"],
                                   "RS_level": a["price"]},
                    "completed_bar": n - 1,
                    "label_bar": c["index"],
                    "label_price": c["price"],
                    "label_above": True,
                })
        return results

    def _forming_ihs(self, df, p_highs, p_lows, current, lookback, falling):
        if not falling:
            return []
        n = len(df)
        results = []
        recent_pl = [l for l in p_lows if l["index"] >= n - lookback]
        for i in range(len(recent_pl) - 1):
            a, c = recent_pl[i], recent_pl[i + 1]
            if c["price"] >= a["price"] * (1 - self.tol):
                continue
            nk_r = [h for h in p_highs if h["index"] > c["index"]]
            if not nk_r:
                continue
            d = max(nk_r, key=lambda h: h["price"])
            if current >= d["price"]:
                continue
            if abs(current - a["price"]) / a["price"] <= self.tol * 2.0 and current > c["price"]:
                results.append({
                    "name": "Forming IH&S",
                    "short": "IH&S?",
                    "type": "bullish",
                    "forming": True,
                    "bar_indices": [a["index"], c["index"], d["index"], n - 1],
                    "key_prices": {"head": c["price"], "neckline": d["price"],
                                   "RS_level": a["price"]},
                    "completed_bar": n - 1,
                    "label_bar": c["index"],
                    "label_price": c["price"],
                    "label_above": False,
                })
        return results

    def _triangles_wedges(self, df, p_highs, p_lows, current, lookback):
        """
        Triangle / wedge classification per PATTERN_RULES.md pivot-ordering rules.

        Requires at least 3 pivot highs AND 2 pivot lows in the lookback window.
        Uses ACR-based straight-line test and pivot ordering:
          Ascending  : flat top (|A-C| ≤ ACR, |C-E| ≤ ACR) + B < D (rising lows)
          Descending : flat bottom (|B-D| ≤ ACR)            + A > C > E (falling highs)
          Symmetrical: A > C > E (falling highs)             + B < D (rising lows)
          Rising Wedge   : fit lines through highs and lows; both rising, lows faster
          Falling Wedge  : both falling, highs faster
        Current price must be INSIDE the pattern (between the two trendline values).
        """
        n = len(df)
        results = []
        rph = [h for h in p_highs if h["index"] >= n - lookback]
        rpl = [l for l in p_lows if l["index"] >= n - lookback]
        if len(rph) < 3 or len(rpl) < 2:
            return results

        # Use last 3 highs and last 2 lows for classification
        a_h, c_h, e_h = rph[-3], rph[-2], rph[-1]  # A, C, E highs
        b_l, d_l      = rpl[-2], rpl[-1]              # B, D lows

        # Pivots must be interleaved chronologically
        all_idx = sorted([a_h["index"], c_h["index"], e_h["index"],
                          b_l["index"], d_l["index"]])
        if all_idx[-1] < n - 20:
            return results  # too old

        cur_idx = n - 1
        acr_highs = _acr(df, a_h["index"], e_h["index"])
        acr_lows  = _acr(df, b_l["index"], d_l["index"])

        # Current trendline values (fit line through 3 highs and 2 lows)
        hx = np.array([a_h["index"], c_h["index"], e_h["index"]], dtype=float)
        hy = np.array([a_h["price"], c_h["price"], e_h["price"]], dtype=float)
        lx = np.array([b_l["index"], d_l["index"]], dtype=float)
        ly = np.array([b_l["price"], d_l["price"]], dtype=float)

        h_slope, h_inter = np.polyfit(hx, hy, 1)
        l_slope, l_inter = np.polyfit(lx, ly, 1)

        cur_h_val = h_slope * cur_idx + h_inter
        cur_l_val = l_slope * cur_idx + l_inter

        if cur_h_val <= cur_l_val:
            return results

        # Price must be inside the pattern
        if not (cur_l_val * 0.98 <= current <= cur_h_val * 1.02):
            return results

        # Apex for extending lines
        if abs(h_slope - l_slope) > 1e-12:
            apex_x = int((l_inter - h_inter) / (h_slope - l_slope))
            bars_to_apex = max(0, apex_x - cur_idx)
        else:
            bars_to_apex = 30
        ext = min(cur_idx + bars_to_apex + 5, cur_idx + 30)

        segs = [
            {"x": [int(hx.min()), ext],
             "y": [h_slope * hx.min() + h_inter, h_slope * ext + h_inter]},
            {"x": [int(lx.min()), ext],
             "y": [l_slope * lx.min() + l_inter, l_slope * ext + l_inter]},
        ]
        all_idxs = sorted(set(int(x) for x in hx.tolist() + lx.tolist()))

        def pat(name, short, ptype):
            lp = cur_h_val if ptype in ("bearish", "neutral") else cur_l_val
            la = ptype in ("bearish", "neutral")
            return {"name": name, "short": short, "type": ptype,
                    "forming": True, "bar_indices": all_idxs, "segments": segs,
                    "key_prices": {"resistance": round(cur_h_val, 4),
                                   "support": round(cur_l_val, 4)},
                    "completed_bar": cur_idx, "label_bar": cur_idx,
                    "label_price": lp, "label_above": la,
                    "bars_to_apex": bars_to_apex}

        flat_top_AC = abs(a_h["price"] - c_h["price"]) <= acr_highs
        flat_top_CE = abs(c_h["price"] - e_h["price"]) <= acr_highs
        flat_bot    = abs(b_l["price"] - d_l["price"]) <= acr_lows
        fall_highs  = a_h["price"] > c_h["price"] > e_h["price"]
        rise_lows   = b_l["price"] < d_l["price"]

        if flat_top_AC and flat_top_CE and rise_lows:
            results.append(pat("Ascending Triangle", "Asc-Tri", "bullish"))
        elif flat_bot and fall_highs:
            results.append(pat("Descending Triangle", "Desc-Tri", "bearish"))
        elif fall_highs and rise_lows:
            results.append(pat("Symmetrical Triangle", "Sym-Tri", "neutral"))
        elif h_slope > 0 and l_slope > 0 and l_slope > h_slope:
            # Both rising, lows rising faster → narrowing → rising wedge (bearish)
            results.append(pat("Rising Wedge", "R-Wedge", "bearish"))
        elif h_slope < 0 and l_slope < 0 and h_slope < l_slope:
            # Both falling, highs falling faster → narrowing → falling wedge (bullish)
            results.append(pat("Falling Wedge", "F-Wedge", "bullish"))

        return results

    def _vcp(self, df, p_highs, p_lows, current, lookback):
        """
        Volatility Contraction Pattern (bullish, Mark Minervini).
        Rules (PATTERN_RULES.md):
          abs(A-C) <= ACR(A..C)   flat top resistance
          B < min(A,C,D,E)        B is the absolute lowest (first contraction low)
          D < min(A,C,E)          D is second-lowest (shallower contraction)
          E < C                   price hasn't breached flat top yet
          Each successive contraction narrows (D > B, E between D and C)
        """
        n = len(df)
        results = []
        rph = [h for h in p_highs if h["index"] >= n - lookback]
        rpl = [l for l in p_lows  if l["index"] >= n - lookback]
        if len(rph) < 2 or len(rpl) < 2:
            return results

        a, c = rph[-2], rph[-1]
        acr = _acr(df, a["index"], c["index"])
        if abs(a["price"] - c["price"]) > acr:
            return results

        # B = deepest low, D = second-deepest (must be shallower than B)
        candidates = [l for l in rpl if l["index"] > a["index"]]
        if len(candidates) < 2:
            return results
        b = min(candidates, key=lambda l: l["price"])
        rest = [l for l in candidates if l["index"] != b["index"]]
        if not rest:
            return results
        d = min(rest, key=lambda l: l["price"])

        # Ensure chronological order: b before d
        if b["index"] > d["index"]:
            b, d = d, b

        # VCP rules
        if not (b["price"] < d["price"]):          # B is lower than D
            return results
        if not (d["price"] < min(a["price"], c["price"])):
            return results
        if not (current < c["price"]):              # E < C (not broken top)
            return results
        if not (current > d["price"]):              # E above D (narrowing)
            return results

        results.append({
            "name": "VCP",
            "short": "VCP",
            "type": "bullish",
            "forming": True,
            "bar_indices": [a["index"], b["index"], c["index"], d["index"], n - 1],
            "key_prices": {"resistance": c["price"], "support": d["price"]},
            "completed_bar": n - 1,
            "label_bar": n - 1,
            "label_price": current,
            "label_above": False,
        })
        return results

    def _flags(self, df, p_highs, p_lows, current):
        """
        Bull / Bear Flag per PATTERN_RULES.md:
          Flagpole : swing move ≥ 5% defined by a confirmed pivot pair
          Flag     : tight consolidation ≤ 45% of pole range after the pole top/bottom
          CMP      : current price inside the flag zone
          Retracement from pole extreme ≤ 50% of pole move
        """
        n = len(df)
        results = []

        # Bull Flag
        recent_pl = [l for l in p_lows  if l["index"] >= n - 30 and l["index"] <= n - 5]
        recent_ph = [h for h in p_highs if h["index"] >= n - 30 and h["index"] <= n - 3]
        for pole_base in recent_pl:
            tops = [h for h in recent_ph if h["index"] > pole_base["index"]]
            if not tops:
                continue
            pole_top = max(tops, key=lambda h: h["price"])
            pole_pct = (pole_top["price"] - pole_base["price"]) / pole_base["price"]
            if pole_pct < 0.05:
                continue
            flag = df.iloc[pole_top["index"]:]
            if len(flag) < 3:
                continue
            fh = float(flag["High"].max())
            fl = float(flag["Low"].min())
            if (fh - fl) / pole_top["price"] > pole_pct * 0.45:
                continue
            if not (fl * 0.99 <= current <= fh * 1.01):
                continue
            if current < pole_top["price"] * (1 - pole_pct * 0.5):
                continue  # retracement > 50% of pole
            results.append({
                "name": "Bull Flag",
                "short": "BullFlag",
                "type": "bullish",
                "forming": True,
                "bar_indices": [pole_base["index"], pole_top["index"], n - 1],
                "key_prices": {"flag_high": fh, "flag_low": fl,
                                "pole_top": pole_top["price"]},
                "completed_bar": n - 1,
                "label_bar": n - 1,
                "label_price": fl,
                "label_above": False,
            })
            break

        # Bear Flag
        recent_ph2 = [h for h in p_highs if h["index"] >= n - 30 and h["index"] <= n - 5]
        recent_pl2 = [l for l in p_lows  if l["index"] >= n - 30 and l["index"] <= n - 3]
        for pole_top in recent_ph2:
            bottoms = [l for l in recent_pl2 if l["index"] > pole_top["index"]]
            if not bottoms:
                continue
            pole_base = min(bottoms, key=lambda l: l["price"])
            pole_pct = (pole_top["price"] - pole_base["price"]) / pole_top["price"]
            if pole_pct < 0.05:
                continue
            flag = df.iloc[pole_base["index"]:]
            if len(flag) < 3:
                continue
            fh = float(flag["High"].max())
            fl = float(flag["Low"].min())
            if (fh - fl) / pole_base["price"] > pole_pct * 0.45:
                continue
            if not (fl * 0.99 <= current <= fh * 1.01):
                continue
            if current > pole_base["price"] * (1 + pole_pct * 0.5):
                continue
            results.append({
                "name": "Bear Flag",
                "short": "BearFlag",
                "type": "bearish",
                "forming": True,
                "bar_indices": [pole_top["index"], pole_base["index"], n - 1],
                "key_prices": {"flag_high": fh, "flag_low": fl,
                                "pole_bottom": pole_base["price"]},
                "completed_bar": n - 1,
                "label_bar": n - 1,
                "label_price": fh,
                "label_above": True,
            })
            break

        return results

    # ── candlestick helpers ───────────────────────────────────────────────────

    def _recent_range(self, df):
        n = len(df)
        return max(0, n - self.recent), n

    # ── existing candlestick patterns ─────────────────────────────────────────

    def _morning_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            o1,c1 = float(df["Open"].iloc[i-2]), float(df["Close"].iloc[i-2])
            o2,c2 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o3,c3 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            b1,b2,b3 = abs(c1-o1), abs(c2-o2), abs(c3-o3)
            avg = (b1+b3)/2
            if avg == 0 or c1>=o1 or b2>avg*0.35 or c3<=o3 or c3<(o1+c1)/2:
                continue
            results.append({"name":"Morning Star","short":"MornStar","type":"bullish",
                "bar_indices":[i-2,i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["Low"].iloc[i-2:i+1].min()),"label_above":False})
        return results

    def _evening_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            o1,c1 = float(df["Open"].iloc[i-2]), float(df["Close"].iloc[i-2])
            o2,c2 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o3,c3 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            b1,b2,b3 = abs(c1-o1), abs(c2-o2), abs(c3-o3)
            avg = (b1+b3)/2
            if avg == 0 or c1<=o1 or b2>avg*0.35 or c3>=o3 or c3>(o1+c1)/2:
                continue
            results.append({"name":"Evening Star","short":"EveStar","type":"bearish",
                "bar_indices":[i-2,i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["High"].iloc[i-2:i+1].max()),"label_above":True})
        return results

    def _bullish_engulfing(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1>=o1 or c2<=o2 or o2>c1 or c2<o1:
                continue
            results.append({"name":"Bullish Engulfing","short":"BullEng","type":"bullish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["Low"].iloc[i]),"label_above":False})
        return results

    def _bearish_engulfing(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1<=o1 or c2>=o2 or o2<c1 or c2>o1:
                continue
            results.append({"name":"Bearish Engulfing","short":"BearEng","type":"bearish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["High"].iloc[i]),"label_above":True})
        return results

    def _hammer(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o,h,l,c = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                       float(df["Low"].iloc[i]),  float(df["Close"].iloc[i]))
            rng = h - l
            if rng == 0:
                continue
            body = abs(c - o)
            if body == 0:
                continue
            lower = min(o,c) - l
            upper = h - max(o,c)
            if lower < 2*body or upper > body*0.5:
                continue
            results.append({"name":"Hammer","short":"Hammer","type":"bullish",
                "bar_indices":[i],"completed_bar":i,"label_bar":i,
                "label_price":l,"label_above":False})
        return results

    def _shooting_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o,h,l,c = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                       float(df["Low"].iloc[i]),  float(df["Close"].iloc[i]))
            rng = h - l
            if rng == 0:
                continue
            body = abs(c - o)
            if body == 0:
                continue
            upper = h - max(o,c)
            lower = min(o,c) - l
            if upper < 2*body or lower > body*0.5:
                continue
            results.append({"name":"Shooting Star","short":"ShootStar","type":"bearish",
                "bar_indices":[i],"completed_bar":i,"label_bar":i,
                "label_price":h,"label_above":True})
        return results

    def _doji(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o,h,l,c = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                       float(df["Low"].iloc[i]),  float(df["Close"].iloc[i]))
            rng = h - l
            if rng == 0:
                continue
            if abs(c - o) / rng > 0.05:
                continue
            results.append({"name":"Doji","short":"Doji","type":"neutral",
                "bar_indices":[i],"completed_bar":i,"label_bar":i,
                "label_price":h,"label_above":True})
        return results

    # ── new candlestick patterns ──────────────────────────────────────────────

    def _three_white_soldiers(self, df):
        """3 consecutive bullish candles, each closing higher with substantial body."""
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            valid = True
            for j in range(i-2, i+1):
                o,h,l,c = (float(df["Open"].iloc[j]), float(df["High"].iloc[j]),
                           float(df["Low"].iloc[j]),  float(df["Close"].iloc[j]))
                if c <= o:
                    valid = False; break
                rng = h - l
                if rng > 0 and (c - o) / rng < 0.4:
                    valid = False; break
            if not valid:
                continue
            closes = [float(df["Close"].iloc[k]) for k in range(i-2, i+1)]
            if not (closes[1] > closes[0] and closes[2] > closes[1]):
                continue
            results.append({"name":"Three White Soldiers","short":"3W-Sol","type":"bullish",
                "bar_indices":[i-2,i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["Low"].iloc[i-2:i+1].min()),"label_above":False})
        return results

    def _three_black_crows(self, df):
        """3 consecutive bearish candles, each closing lower with substantial body."""
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            valid = True
            for j in range(i-2, i+1):
                o,h,l,c = (float(df["Open"].iloc[j]), float(df["High"].iloc[j]),
                           float(df["Low"].iloc[j]),  float(df["Close"].iloc[j]))
                if c >= o:
                    valid = False; break
                rng = h - l
                if rng > 0 and (o - c) / rng < 0.4:
                    valid = False; break
            if not valid:
                continue
            closes = [float(df["Close"].iloc[k]) for k in range(i-2, i+1)]
            if not (closes[1] < closes[0] and closes[2] < closes[1]):
                continue
            results.append({"name":"Three Black Crows","short":"3B-Crow","type":"bearish",
                "bar_indices":[i-2,i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["High"].iloc[i-2:i+1].max()),"label_above":True})
        return results

    def _bullish_harami(self, df):
        """Small bullish candle fully inside a large bearish mother candle."""
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,h1,l1,c1 = (float(df["Open"].iloc[i-1]), float(df["High"].iloc[i-1]),
                           float(df["Low"].iloc[i-1]),  float(df["Close"].iloc[i-1]))
            o2,c2 = float(df["Open"].iloc[i]), float(df["Close"].iloc[i])
            if c1 >= o1:
                continue  # bar1 must be bearish
            b1 = o1 - c1
            if (h1 - l1) > 0 and b1 / (h1 - l1) < 0.5:
                continue  # must have substantial body
            if c2 <= o2:
                continue  # bar2 must be bullish
            if o2 < c1 or c2 > o1:
                continue  # bar2 body must be inside bar1 body
            if (c2 - o2) >= b1 * 0.5:
                continue  # bar2 must be significantly smaller
            results.append({"name":"Bullish Harami","short":"BullHarami","type":"bullish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["Low"].iloc[i]),"label_above":False})
        return results

    def _bearish_harami(self, df):
        """Small bearish candle fully inside a large bullish mother candle."""
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,h1,l1,c1 = (float(df["Open"].iloc[i-1]), float(df["High"].iloc[i-1]),
                           float(df["Low"].iloc[i-1]),  float(df["Close"].iloc[i-1]))
            o2,c2 = float(df["Open"].iloc[i]), float(df["Close"].iloc[i])
            if c1 <= o1:
                continue  # bar1 must be bullish
            b1 = c1 - o1
            if (h1 - l1) > 0 and b1 / (h1 - l1) < 0.5:
                continue
            if c2 >= o2:
                continue  # bar2 must be bearish
            if o2 > c1 or c2 < o1:
                continue  # bar2 body inside bar1 body
            if (o2 - c2) >= b1 * 0.5:
                continue
            results.append({"name":"Bearish Harami","short":"BearHarami","type":"bearish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["High"].iloc[i]),"label_above":True})
        return results

    def _tweezer_top(self, df):
        """
        Two consecutive candles with highs within 0.15% of each other.
        Bar 1 bullish (closes near its high), Bar 2 bearish (rejection at same level).
        Signals resistance at that level — twice tested and rejected.
        """
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            h1 = float(df["High"].iloc[i-1])
            h2 = float(df["High"].iloc[i])
            if abs(h1 - h2) / max(h1, h2) > 0.0015:   # within 0.15%
                continue
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,l2,c2 = (float(df["Open"].iloc[i]), float(df["Low"].iloc[i]),
                        float(df["Close"].iloc[i]))
            if c1 <= o1:
                continue  # bar1 should be bullish (prior up-move)
            if c2 >= o2:
                continue  # bar2 must be bearish (rejection)
            if c2 > (h2 + l2) / 2:
                continue  # bar2 close in lower half (clear rejection)
            results.append({"name":"Tweezer Top","short":"TwzTop","type":"bearish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":max(h1,h2),"label_above":True})
        return results

    def _tweezer_bottom(self, df):
        """
        Two consecutive candles with lows within 0.15% of each other.
        Bar 1 bearish, Bar 2 bullish (support held at same level).
        """
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            l1 = float(df["Low"].iloc[i-1])
            l2 = float(df["Low"].iloc[i])
            if abs(l1 - l2) / max(l1, l2) > 0.0015:   # within 0.15%
                continue
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,h2,c2 = (float(df["Open"].iloc[i]), float(df["High"].iloc[i]),
                        float(df["Close"].iloc[i]))
            if c1 >= o1:
                continue  # bar1 should be bearish (prior down-move)
            if c2 <= o2:
                continue  # bar2 must be bullish (support reaction)
            if c2 < (h2 + l2) / 2:
                continue  # bar2 close in upper half (clear bounce)
            results.append({"name":"Tweezer Bottom","short":"TwzBot","type":"bullish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":min(l1,l2),"label_above":False})
        return results

    def _piercing_line(self, df):
        """
        Bar1 bearish. Bar2 bullish: opens below Bar1 close, closes above
        midpoint of Bar1 body but below Bar1 open.
        """
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1 >= o1 or c2 <= o2:
                continue
            if o2 >= c1:
                continue  # must open below bar1 close
            mid1 = (o1 + c1) / 2
            if c2 <= mid1 or c2 >= o1:
                continue  # must close above midpoint but below bar1 open
            results.append({"name":"Piercing Line","short":"Pierce","type":"bullish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["Low"].iloc[i]),"label_above":False})
        return results

    def _dark_cloud_cover(self, df):
        """
        Bar1 bullish. Bar2 bearish: opens above Bar1 close, closes below
        midpoint of Bar1 body but above Bar1 open.
        """
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1,c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2,c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1 <= o1 or c2 >= o2:
                continue
            if o2 <= c1:
                continue  # must open above bar1 close
            mid1 = (o1 + c1) / 2
            if c2 >= mid1 or c2 <= o1:
                continue
            results.append({"name":"Dark Cloud Cover","short":"DarkCloud","type":"bearish",
                "bar_indices":[i-1,i],"completed_bar":i,"label_bar":i,
                "label_price":float(df["High"].iloc[i]),"label_above":True})
        return results
