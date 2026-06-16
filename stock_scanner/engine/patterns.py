"""
patterns.py
===========
Detects common chart and candlestick patterns using pivot highs/lows
and raw OHLC candle data.

Chart patterns  (use pivot highs/lows):
  Double Top (M)              – bearish reversal
  Double Bottom (W)           – bullish reversal
  Head and Shoulders          – bearish reversal
  Inverse Head and Shoulders  – bullish reversal

Candlestick patterns (use recent raw bars):
  Morning Star                – bullish 3-candle
  Evening Star                – bearish 3-candle
  Bullish Engulfing           – bullish 2-candle
  Bearish Engulfing           – bearish 2-candle
  Hammer                      – bullish single candle
  Shooting Star               – bearish single candle
  Doji                        – indecision single candle

Each detected pattern is a dict:
  name          str   full name
  short         str   short label for chart (e.g. "M", "W", "EvenStar")
  type          str   "bullish" | "bearish" | "neutral"
  bar_indices   list  key bar positions involved in the pattern
  completed_bar int   bar index where the pattern is considered complete
  label_bar     int   where to place the chart annotation
  label_price   float y-position of the annotation
  label_above   bool  whether label goes above the bar
"""

from typing import List, Dict, Any
import pandas as pd


class PatternFinder:
    def __init__(self,
                 price_tolerance: float = 0.03,
                 min_pullback: float = 0.03,
                 recent_candle_bars: int = 60):
        """
        price_tolerance      : max % difference for two highs/lows to be
                               considered "at the same level" (default 3%)
        min_pullback         : min % move between the two tops/bottoms
                               (default 3% — filters micro-patterns)
        recent_candle_bars   : only scan this many trailing bars for
                               candlestick patterns (they aren't actionable
                               when old)
        """
        self.tol    = price_tolerance
        self.pull   = min_pullback
        self.recent = recent_candle_bars

    # ── public entry point ────────────────────────────────────────────────

    def find_all(self,
                 df: pd.DataFrame,
                 p_highs: List[Dict],
                 p_lows:  List[Dict]) -> List[Dict[str, Any]]:
        patterns: List[Dict[str, Any]] = []
        patterns += self._double_top(df, p_highs, p_lows)
        patterns += self._double_bottom(df, p_highs, p_lows)
        patterns += self._head_and_shoulders(df, p_highs, p_lows)
        patterns += self._inv_head_and_shoulders(df, p_highs, p_lows)
        patterns += self._morning_star(df)
        patterns += self._evening_star(df)
        patterns += self._bullish_engulfing(df)
        patterns += self._bearish_engulfing(df)
        patterns += self._hammer(df)
        patterns += self._shooting_star(df)
        patterns += self._doji(df)
        # sort by completion bar (most recent last)
        patterns.sort(key=lambda p: p["completed_bar"])
        return patterns

    # ── chart patterns ────────────────────────────────────────────────────

    def _double_top(self, df, p_highs, p_lows):
        results = []
        for i in range(len(p_highs) - 1):
            h1 = p_highs[i]
            h2 = p_highs[i + 1]
            # similar height
            if abs(h1["price"] - h2["price"]) / h1["price"] > self.tol:
                continue
            # h2 must not be a clear new high (otherwise it's not a "top")
            if h2["price"] > h1["price"] * (1 + self.tol):
                continue
            # find the deepest swing low between the two tops (neckline)
            between = [l for l in p_lows
                       if h1["index"] < l["index"] < h2["index"]]
            if not between:
                continue
            neck = min(between, key=lambda l: l["price"])
            pullback = (min(h1["price"], h2["price"]) - neck["price"]) / h1["price"]
            if pullback < self.pull:
                continue
            results.append({
                "name": "Double Top",
                "short": "M-Top",
                "type": "bearish",
                "bar_indices": [h1["index"], neck["index"], h2["index"]],
                "key_prices": {"H1": h1["price"], "neck": neck["price"],
                               "H2": h2["price"]},
                "completed_bar": h2["index"],
                "label_bar": h2["index"],
                "label_price": h2["price"],
                "label_above": True,
            })
        return results

    def _double_bottom(self, df, p_highs, p_lows):
        results = []
        for i in range(len(p_lows) - 1):
            l1 = p_lows[i]
            l2 = p_lows[i + 1]
            if abs(l1["price"] - l2["price"]) / l1["price"] > self.tol:
                continue
            if l2["price"] < l1["price"] * (1 - self.tol):
                continue
            between = [h for h in p_highs
                       if l1["index"] < h["index"] < l2["index"]]
            if not between:
                continue
            peak = max(between, key=lambda h: h["price"])
            pullback = (peak["price"] - max(l1["price"], l2["price"])) / l1["price"]
            if pullback < self.pull:
                continue
            results.append({
                "name": "Double Bottom",
                "short": "W-Bot",
                "type": "bullish",
                "bar_indices": [l1["index"], peak["index"], l2["index"]],
                "key_prices": {"L1": l1["price"], "peak": peak["price"],
                               "L2": l2["price"]},
                "completed_bar": l2["index"],
                "label_bar": l2["index"],
                "label_price": l2["price"],
                "label_above": False,
            })
        return results

    def _head_and_shoulders(self, df, p_highs, p_lows):
        results = []
        for i in range(len(p_highs) - 2):
            ls = p_highs[i]      # left shoulder
            hd = p_highs[i + 1]  # head
            rs = p_highs[i + 2]  # right shoulder
            # head must be highest
            if not (hd["price"] > ls["price"] and hd["price"] > rs["price"]):
                continue
            # shoulders at similar level
            if abs(ls["price"] - rs["price"]) / ls["price"] > self.tol * 1.5:
                continue
            # necklines: lowest lows between left-head and head-right
            lows_l = [l for l in p_lows
                      if ls["index"] < l["index"] < hd["index"]]
            lows_r = [l for l in p_lows
                      if hd["index"] < l["index"] < rs["index"]]
            if not lows_l or not lows_r:
                continue
            nk_l = min(lows_l, key=lambda l: l["price"])
            nk_r = min(lows_r, key=lambda l: l["price"])
            results.append({
                "name": "Head & Shoulders",
                "short": "H&S",
                "type": "bearish",
                "bar_indices": [ls["index"], nk_l["index"],
                                hd["index"], nk_r["index"], rs["index"]],
                "key_prices": {"LS": ls["price"], "Head": hd["price"],
                               "RS": rs["price"],
                               "neck": (nk_l["price"] + nk_r["price"]) / 2},
                "completed_bar": rs["index"],
                "label_bar": hd["index"],
                "label_price": hd["price"],
                "label_above": True,
            })
        return results

    def _inv_head_and_shoulders(self, df, p_highs, p_lows):
        results = []
        for i in range(len(p_lows) - 2):
            ls = p_lows[i]
            hd = p_lows[i + 1]
            rs = p_lows[i + 2]
            if not (hd["price"] < ls["price"] and hd["price"] < rs["price"]):
                continue
            if abs(ls["price"] - rs["price"]) / ls["price"] > self.tol * 1.5:
                continue
            highs_l = [h for h in p_highs
                       if ls["index"] < h["index"] < hd["index"]]
            highs_r = [h for h in p_highs
                       if hd["index"] < h["index"] < rs["index"]]
            if not highs_l or not highs_r:
                continue
            nk_l = max(highs_l, key=lambda h: h["price"])
            nk_r = max(highs_r, key=lambda h: h["price"])
            results.append({
                "name": "Inv Head & Shoulders",
                "short": "IH&S",
                "type": "bullish",
                "bar_indices": [ls["index"], nk_l["index"],
                                hd["index"], nk_r["index"], rs["index"]],
                "key_prices": {"LS": ls["price"], "Head": hd["price"],
                               "RS": rs["price"],
                               "neck": (nk_l["price"] + nk_r["price"]) / 2},
                "completed_bar": rs["index"],
                "label_bar": hd["index"],
                "label_price": hd["price"],
                "label_above": False,
            })
        return results

    # ── candlestick patterns ──────────────────────────────────────────────

    def _recent_range(self, df):
        """Return (start, end) index for the recent candle scan window."""
        n = len(df)
        return max(0, n - self.recent), n

    def _morning_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            o1, c1 = float(df["Open"].iloc[i-2]), float(df["Close"].iloc[i-2])
            o2, c2 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o3, c3 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            body1 = abs(c1 - o1)
            body2 = abs(c2 - o2)
            body3 = abs(c3 - o3)
            avg_body = (body1 + body3) / 2
            if avg_body == 0:
                continue
            # bar1 strongly bearish, bar2 small body (star), bar3 strongly bullish
            if c1 >= o1:
                continue
            if body2 > avg_body * 0.35:
                continue
            if c3 <= o3:
                continue
            # bar3 closes above midpoint of bar1
            if c3 < (o1 + c1) / 2:
                continue
            results.append({
                "name": "Morning Star",
                "short": "MornStar",
                "type": "bullish",
                "bar_indices": [i-2, i-1, i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": float(df["Low"].iloc[i-2:i+1].min()),
                "label_above": False,
            })
        return results

    def _evening_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 2, n):
            o1, c1 = float(df["Open"].iloc[i-2]), float(df["Close"].iloc[i-2])
            o2, c2 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o3, c3 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            body1 = abs(c1 - o1)
            body2 = abs(c2 - o2)
            body3 = abs(c3 - o3)
            avg_body = (body1 + body3) / 2
            if avg_body == 0:
                continue
            if c1 <= o1:
                continue
            if body2 > avg_body * 0.35:
                continue
            if c3 >= o3:
                continue
            if c3 > (o1 + c1) / 2:
                continue
            results.append({
                "name": "Evening Star",
                "short": "EveStar",
                "type": "bearish",
                "bar_indices": [i-2, i-1, i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": float(df["High"].iloc[i-2:i+1].max()),
                "label_above": True,
            })
        return results

    def _bullish_engulfing(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1, c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2, c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1 >= o1:      # bar1 must be bearish
                continue
            if c2 <= o2:      # bar2 must be bullish
                continue
            if o2 > c1 or c2 < o1:   # bar2 must engulf bar1
                continue
            results.append({
                "name": "Bullish Engulfing",
                "short": "BullEng",
                "type": "bullish",
                "bar_indices": [i-1, i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": float(df["Low"].iloc[i]),
                "label_above": False,
            })
        return results

    def _bearish_engulfing(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start + 1, n):
            o1, c1 = float(df["Open"].iloc[i-1]), float(df["Close"].iloc[i-1])
            o2, c2 = float(df["Open"].iloc[i]),   float(df["Close"].iloc[i])
            if c1 <= o1:
                continue
            if c2 >= o2:
                continue
            if o2 < c1 or c2 > o1:
                continue
            results.append({
                "name": "Bearish Engulfing",
                "short": "BearEng",
                "type": "bearish",
                "bar_indices": [i-1, i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": float(df["High"].iloc[i]),
                "label_above": True,
            })
        return results

    def _hammer(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o, h, l, c = (float(df["Open"].iloc[i]),  float(df["High"].iloc[i]),
                          float(df["Low"].iloc[i]),   float(df["Close"].iloc[i]))
            candle_range = h - l
            if candle_range == 0:
                continue
            body      = abs(c - o)
            lower_wick = min(o, c) - l
            upper_wick = h - max(o, c)
            if body == 0:
                continue
            # lower wick >= 2× body, body in upper third, tiny upper wick
            if lower_wick < 2 * body:
                continue
            if upper_wick > body * 0.5:
                continue
            results.append({
                "name": "Hammer",
                "short": "Hammer",
                "type": "bullish",
                "bar_indices": [i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": l,
                "label_above": False,
            })
        return results

    def _shooting_star(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o, h, l, c = (float(df["Open"].iloc[i]),  float(df["High"].iloc[i]),
                          float(df["Low"].iloc[i]),   float(df["Close"].iloc[i]))
            candle_range = h - l
            if candle_range == 0:
                continue
            body      = abs(c - o)
            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l
            if body == 0:
                continue
            if upper_wick < 2 * body:
                continue
            if lower_wick > body * 0.5:
                continue
            results.append({
                "name": "Shooting Star",
                "short": "ShootStar",
                "type": "bearish",
                "bar_indices": [i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": h,
                "label_above": True,
            })
        return results

    def _doji(self, df):
        results = []
        start, n = self._recent_range(df)
        for i in range(start, n):
            o, h, l, c = (float(df["Open"].iloc[i]),  float(df["High"].iloc[i]),
                          float(df["Low"].iloc[i]),   float(df["Close"].iloc[i]))
            candle_range = h - l
            if candle_range == 0:
                continue
            body = abs(c - o)
            # body <= 5% of candle range
            if body / candle_range > 0.05:
                continue
            results.append({
                "name": "Doji",
                "short": "Doji",
                "type": "neutral",
                "bar_indices": [i],
                "completed_bar": i,
                "label_bar": i,
                "label_price": h,
                "label_above": True,
            })
        return results
