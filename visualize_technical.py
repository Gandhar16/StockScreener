"""
visualize_technical.py
======================
Candlestick chart with:
  - Swing high/low pivot markers (triangles on actual candle extremes)
  - Trendline touch highlights: larger bright markers on the pivots a
    trendline actually passes through, plus a circle dot on the line itself
  - Horizontal S/R zones with price labels
  - Nearest support zone always shown (with distance % if outside ±15%)
  - Short-term support fallback (last 3 months) when no nearby support exists
  - Diagonal trendlines (LT solid, ST dashed)

Usage:
    python visualize_technical.py [TICKER] [PERIOD]
    python visualize_technical.py AAPL 1y
    python visualize_technical.py NVDA 2y
"""

import logging
import sys

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import yfinance as yf

from stock_scanner.engine.patterns import PatternFinder
from stock_scanner.engine.technical import MarketStructureEngine

logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

MIN_TL_TOUCHES = 3  # trendline must have at least this many pivot touches
MAX_SUP_ZONES = 3  # nearest support zones to display (below price)
MAX_RES_ZONES = 3  # nearest resistance zones to display (above price)
LEVEL_TOL = 0.025  # 2.5% — max distance from a key level to count as "at" it


# ── drawing helpers ───────────────────────────────────────────────────────────


def draw_candlesticks(ax, df: pd.DataFrame) -> None:
    bull, bear = "#26a69a", "#ef5350"
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, low, c = (
            float(row["Open"]),
            float(row["High"]),
            float(row["Low"]),
            float(row["Close"]),
        )
        col = bull if c >= o else bear
        ax.plot([i, i], [low, h], color=col, linewidth=0.8, zorder=2)
        body_lo, body_hi = min(o, c), max(o, c)
        ax.add_patch(
            mpatches.Rectangle(
                (i - 0.4, body_lo),
                0.8,
                max(body_hi - body_lo, 0.001 * c),
                facecolor=col,
                edgecolor=col,
                linewidth=0.4,
                zorder=3,
            )
        )


def draw_pivot_markers(
    ax, p_highs: list, p_lows: list, hl_high_idx: set | None = None, hl_low_idx: set | None = None
) -> None:
    """
    Circles placed exactly at the wick tip (High for swing highs, Low for
    swing lows).  Pivots that anchor a visible trendline get a larger,
    brighter circle with a white outline so the connection is obvious.
    """
    hl_high_idx = hl_high_idx or set()
    hl_low_idx = hl_low_idx or set()

    # ── swing highs — circle at the High wick tip ──
    reg_h = [p for p in p_highs if p["index"] not in hl_high_idx]
    lit_h = [p for p in p_highs if p["index"] in hl_high_idx]

    if reg_h:
        ax.scatter(
            [p["index"] for p in reg_h],
            [p["price"] for p in reg_h],
            marker="o",
            color="#ff6b6b",
            s=20,
            zorder=6,
            alpha=0.75,
            linewidths=0,
        )
    if lit_h:
        ax.scatter(
            [p["index"] for p in lit_h],
            [p["price"] for p in lit_h],
            marker="o",
            color="#ff1744",
            s=50,
            zorder=7,
            alpha=1.0,
            linewidths=1.2,
            edgecolors="#ffffff",
            label="Swing High (TL anchor)",
        )

    # ── swing lows — circle at the Low wick tip ──
    reg_l = [p for p in p_lows if p["index"] not in hl_low_idx]
    lit_l = [p for p in p_lows if p["index"] in hl_low_idx]

    if reg_l:
        ax.scatter(
            [p["index"] for p in reg_l],
            [p["price"] for p in reg_l],
            marker="o",
            color="#69f0ae",
            s=20,
            zorder=6,
            alpha=0.75,
            linewidths=0,
        )
    if lit_l:
        ax.scatter(
            [p["index"] for p in lit_l],
            [p["price"] for p in lit_l],
            marker="o",
            color="#00e676",
            s=50,
            zorder=7,
            alpha=1.0,
            linewidths=1.2,
            edgecolors="#ffffff",
            label="Swing Low (TL anchor)",
        )

    # legend entries for dim markers
    if reg_h:
        ax.scatter(
            [], [], marker="o", color="#ff6b6b", s=20, alpha=0.75, linewidths=0, label="Swing High"
        )
    if reg_l:
        ax.scatter(
            [], [], marker="o", color="#69f0ae", s=20, alpha=0.75, linewidths=0, label="Swing Low"
        )


def channel_intercept(df: pd.DataFrame, tl: dict, line_type: str) -> float:
    """
    Return the intercept of the parallel channel line.
    For a support channel: parallel line through the highest High between
    the first and last touch so the band captures all price action.
    For a resistance channel: through the lowest Low.
    """
    m, b = tl["slope"], tl["intercept"]
    start, end = tl["start_index"], tl["end_index"]
    n = len(df)
    best_offset = 0.0
    for k in range(start, min(end + 1, n)):
        line_val = m * k + b
        if line_type == "support":
            offset = float(df["High"].iloc[k]) - line_val
            if offset > best_offset:
                best_offset = offset
        else:
            offset = float(df["Low"].iloc[k]) - line_val  # negative
            if offset < best_offset:
                best_offset = offset
    return b + best_offset


def draw_channel(
    ax,
    tl: dict,
    df: pd.DataFrame,
    color: str,
    linestyle: str = "-",
    label: str = "",
    line_type: str = "support",
) -> None:
    """
    Draw a price channel: base trendline (solid) + parallel channel line
    (dashed, same colour, lighter) + shaded band between them.
    Extended to the right edge of the chart so the projected level is visible.
    """
    m, b = tl["slope"], tl["intercept"]
    b_ch = channel_intercept(df, tl, line_type)
    n = len(df)
    x0 = tl["start_index"]
    x1 = n - 1  # extend to right edge

    xs = np.array([x0, x1])
    y_base = m * xs + b
    y_chan = m * xs + b_ch

    # shaded band
    x_fill = np.arange(x0, x1 + 1)
    ax.fill_between(x_fill, m * x_fill + b, m * x_fill + b_ch, alpha=0.07, color=color, zorder=1)

    # base line (solid)
    ax.plot(
        xs,
        y_base,
        color=color,
        linewidth=1.7,
        linestyle=linestyle,
        alpha=0.90,
        zorder=4,
        label=label if label else None,
    )

    # channel line (dashed, lighter)
    ax.plot(xs, y_chan, color=color, linewidth=1.0, linestyle="--", alpha=0.55, zorder=4)

    # price label for channel line at right edge
    ch_val_now = m * (n - 1) + b_ch
    ax.text(
        n + 0.5,
        ch_val_now,
        f"{ch_val_now:.2f}",
        color=color,
        fontsize=7,
        va="center",
        alpha=0.7,
        zorder=7,
    )


def draw_horizontal_zone(
    ax, zone: dict, color: str, chart_bars: int, label_suffix: str = ""
) -> None:
    """Shaded band + dashed centre line + price label on the right edge."""
    lo, hi = zone["price_range"]
    if lo == hi:
        hi = lo * 1.001
    ax.axhspan(lo, hi, alpha=0.18, color=color, zorder=1)
    center = zone["center_price"]
    ax.axhline(center, color=color, linewidth=0.8, linestyle="--", alpha=0.60, zorder=1)
    ax.text(
        chart_bars + 0.5,
        center,
        f"{center:.2f}{label_suffix}",
        color=color,
        fontsize=7,
        va="center",
        fontweight="bold",
        zorder=7,
    )


def annotate_at_levels(patterns, vis_sup_zones, vis_res_zones, sup_tls, res_tls, df):
    """
    Tag each pattern dict with the key S/R level it is touching (or None).
    Bullish patterns are checked against support; bearish against resistance.
    Matching levels: horizontal zones first, then trendline channels.
    """
    for p in patterns:
        idxs = p["bar_indices"]
        bar_lo = min(idxs)
        bar_hi = max(idxs)
        p_low = float(df["Low"].iloc[bar_lo : bar_hi + 1].min())
        p_high = float(df["High"].iloc[bar_lo : bar_hi + 1].max())

        at_level = None

        if p["type"] in ("bullish", "neutral"):
            for z in vis_sup_zones:
                if abs(p_low - z["center_price"]) / z["center_price"] <= LEVEL_TOL:
                    at_level = "@Sup Zone"
                    break
            if at_level is None:
                for tl in sup_tls:
                    tl_val = tl["slope"] * bar_hi + tl["intercept"]
                    if tl_val > 0 and abs(p_low - tl_val) / tl_val <= LEVEL_TOL:
                        at_level = "@Sup TL"
                        break

        if p["type"] in ("bearish", "neutral") and at_level is None:
            for z in vis_res_zones:
                if abs(p_high - z["center_price"]) / z["center_price"] <= LEVEL_TOL:
                    at_level = "@Res Zone"
                    break
            if at_level is None:
                for tl in res_tls:
                    tl_val = tl["slope"] * bar_hi + tl["intercept"]
                    if tl_val > 0 and abs(p_high - tl_val) / tl_val <= LEVEL_TOL:
                        at_level = "@Res TL"
                        break

        p["at_level"] = at_level


def compute_entry_signals(patterns: list, df: pd.DataFrame, indicators: dict | None = None) -> None:
    """
    Enrich each pattern dict (in-place) with:
      entry_price, stop_loss, vol_ratio, vol_confirmed, risk_pct, signal,
      pattern_score (0-100 composite quality),
      forming_confidence / completion_trigger / expected_move_pct (forming only)

    Signal codes:
      BUY / BUY?         — completed bullish (vol confirmed / not confirmed)
      SELL / SELL?        — completed bearish
      WATCH-LONG          — forming bullish
      WATCH-SHORT         — forming bearish
      WATCH               — neutral forming pattern
    """
    try:
        from stock_scanner.engine.indicators import forming_confidence, score_pattern

        _scoring_available = True
    except ImportError:
        _scoring_available = False
    vol_sma = df["Volume"].rolling(20).mean()

    CANDLESTICK_NAMES = {
        "Hammer",
        "Shooting Star",
        "Bullish Engulfing",
        "Bearish Engulfing",
        "Morning Star",
        "Evening Star",
        "Doji",
        "Three White Soldiers",
        "Three Black Crows",
        "Bullish Harami",
        "Bearish Harami",
        "Tweezer Top",
        "Tweezer Bottom",
        "Piercing Line",
        "Dark Cloud Cover",
    }

    for p in patterns:
        kp = p.get("key_prices", {})
        idxs = p["bar_indices"]
        ptype = p["type"]
        name = p["name"]
        forming = p.get("forming", False)
        is_candle = name in CANDLESTICK_NAMES

        # ── volume ratio at the pattern's last bar ──
        last_bar = max(idxs)
        pat_vol = float(df["Volume"].iloc[last_bar])
        bar_sma = float(vol_sma.iloc[last_bar])
        bar_sma = bar_sma if not pd.isna(bar_sma) and bar_sma > 0 else 1.0
        vol_ratio = pat_vol / bar_sma
        vol_thresh = 1.2 if is_candle else 1.5
        vol_confirmed = vol_ratio >= vol_thresh

        # ── entry / stop per pattern ──
        bar_lo = min(idxs)
        p_high = float(df["High"].iloc[bar_lo : last_bar + 1].max())
        p_low = float(df["Low"].iloc[bar_lo : last_bar + 1].min())
        entry_price = stop_loss = None

        if is_candle:
            if ptype == "bullish":
                entry_price = p_high * 1.001
                stop_loss = p_low * 0.999
            else:
                entry_price = p_low * 0.999
                stop_loss = p_high * 1.001

        elif name in ("Double Top", "Head & Shoulders"):
            neckline = kp.get("B") or kp.get("neck", 0)
            rs_or_c = max(kp.get("C", 0), kp.get("RS", 0), kp.get("A", 0))
            entry_price = neckline * 0.999
            stop_loss = rs_or_c * 1.005 if rs_or_c else p_high * 1.005

        elif name in ("Double Bottom", "Inv Head & Shoulders"):
            neckline = kp.get("B") or kp.get("neck", 0)
            rs_or_c = min(
                kp.get("C", float("inf")), kp.get("RS", float("inf")), kp.get("A", float("inf"))
            )
            entry_price = neckline * 1.001
            stop_loss = rs_or_c * 0.995 if rs_or_c < float("inf") else p_low * 0.995

        elif name == "Forming Double Top":
            entry_price = kp.get("neckline", 0) * 0.999
            stop_loss = kp.get("resistance", 0) * 1.005

        elif name == "Forming Double Bottom":
            entry_price = kp.get("neckline", 0) * 1.001
            stop_loss = kp.get("support", 0) * 0.995

        elif name == "Forming H&S":
            entry_price = kp.get("neckline", 0) * 0.999
            stop_loss = kp.get("RS_level", kp.get("head", 0)) * 1.005

        elif name == "Forming IH&S":
            entry_price = kp.get("neckline", 0) * 1.001
            stop_loss = kp.get("RS_level", kp.get("head", 0)) * 0.995

        elif name in ("Ascending Triangle", "VCP", "Falling Wedge"):
            entry_price = kp.get("resistance", 0) * 1.001
            stop_loss = kp.get("support", 0) * 0.995

        elif name == "Bull Flag":
            entry_price = kp.get("flag_high", 0) * 1.001
            stop_loss = kp.get("flag_low", 0) * 0.995

        elif name in ("Descending Triangle", "Rising Wedge"):
            entry_price = kp.get("support", 0) * 0.999
            stop_loss = kp.get("resistance", 0) * 1.005

        elif name == "Bear Flag":
            entry_price = kp.get("flag_low", 0) * 0.999
            stop_loss = kp.get("flag_high", 0) * 1.005

        elif name == "Symmetrical Triangle":
            entry_price = kp.get("resistance", 0) * 1.001
            stop_loss = kp.get("support", 0) * 0.995

        else:
            # fallback: use candle range
            if ptype == "bullish":
                entry_price = p_high * 1.001
                stop_loss = p_low * 0.999
            else:
                entry_price = p_low * 0.999
                stop_loss = p_high * 1.001

        risk_pct = (
            abs(entry_price - stop_loss) / entry_price * 100
            if entry_price and stop_loss and entry_price > 0
            else 0.0
        )

        # ── signal code ──
        if forming:
            signal = (
                "WATCH-LONG"
                if ptype == "bullish"
                else "WATCH-SHORT"
                if ptype == "bearish"
                else "WATCH"
            )
        else:
            if ptype == "bullish":
                signal = "BUY" if vol_confirmed else "BUY?"
            elif ptype == "bearish":
                signal = "SELL" if vol_confirmed else "SELL?"
            else:
                signal = "WATCH"

        p["entry_price"] = round(entry_price, 4) if entry_price else None
        p["stop_loss"] = round(stop_loss, 4) if stop_loss else None
        p["vol_ratio"] = round(vol_ratio, 2)
        p["vol_confirmed"] = vol_confirmed
        p["risk_pct"] = round(risk_pct, 2)
        p["signal"] = signal

        # ── quality scoring (requires indicators dict) ──
        if _scoring_available and indicators:
            if forming:
                fc = forming_confidence(p, df, indicators)
                p.update(fc)
                p["pattern_score"] = None  # not meaningful until confirmed
            else:
                p["pattern_score"] = score_pattern(p, indicators)


def draw_patterns(ax, patterns: list, df: pd.DataFrame, price_range: float) -> None:
    """Annotate detected patterns on the price chart."""
    offset = price_range * 0.018
    seen_bars = {}  # deduplicate labels at the same bar (keep most important)

    for p in patterns:
        bar = p["label_bar"]
        forming = p.get("forming", False)
        at_level = p.get("at_level")  # e.g. "@Sup Zone", "@Res TL", or None
        color = (
            "#00e676"
            if p["type"] == "bullish"
            else "#ef5350"
            if p["type"] == "bearish"
            else "#ffeb3b"
        )

        # draw lines — triangles/wedges use custom segments, others connect bar_indices
        idxs = p["bar_indices"]
        lw = 1.6 if at_level else (1.4 if forming else 1.1)
        alp = 0.90 if at_level else (0.65 if forming else 0.75)

        if "segments" in p:
            # two separate trendlines (upper + lower) extending to apex
            for seg in p["segments"]:
                ax.plot(
                    seg["x"],
                    seg["y"],
                    color=color,
                    linewidth=lw,
                    linestyle="--",
                    alpha=alp,
                    zorder=5,
                )
        elif len(idxs) >= 2:
            if p["type"] == "bearish":
                ys = [float(df["High"].iloc[x]) for x in idxs]
            else:
                ys = [float(df["Low"].iloc[x]) for x in idxs]
            ls = "--" if forming else ":"
            ax.plot(idxs, ys, color=color, linewidth=lw, linestyle=ls, alpha=alp, zorder=5)

        # priority: at-level > regular; chart > candle; completed > forming
        if at_level:
            priority = 0 if len(idxs) >= 3 else 1
        elif forming:
            priority = 4
        else:
            priority = 2 if len(idxs) >= 3 else 3

        if bar not in seen_bars or seen_bars[bar][0] > priority:
            sig = p.get("signal", "")
            sig_icon = (
                "^"
                if "LONG" in sig or sig in ("BUY", "BUY?")
                else "v"
                if "SHORT" in sig or sig in ("SELL", "SELL?")
                else "~"
            )
            sig_str = f"{sig_icon} {sig}" if sig else ""
            if at_level:
                label = (
                    f"{p['short']}\n{at_level}\n{sig_str}"
                    if sig_str
                    else f"{p['short']}\n{at_level}"
                )
            elif sig_str:
                label = f"{p['short']}\n{sig_str}"
            else:
                label = p["short"]
            seen_bars[bar] = (
                priority,
                label,
                color,
                p["label_price"],
                p["label_above"],
                forming,
                at_level,
            )

    for bar, (_, label, color, price, above, forming, at_level) in seen_bars.items():
        y = price + offset if above else price - offset
        va = "bottom" if above else "top"
        fs = 7.5 if at_level else 6.5
        edge_lw = 2.2 if at_level else (1.4 if forming else 0.8)
        alpha = 0.92 if at_level else (0.70 if forming else 0.85)
        ls = "--" if (forming and not at_level) else "-"
        ax.annotate(
            label,
            xy=(bar, y),
            xycoords="data",
            color=color,
            fontsize=fs,
            fontweight="bold",
            va=va,
            ha="center",
            zorder=9,
            bbox={
                "boxstyle": "round,pad=0.3",
                "facecolor": "#131722",
                "edgecolor": color,
                "alpha": alpha,
                "linewidth": edge_lw,
                "linestyle": ls,
            },
        )


def draw_volume(ax, df: pd.DataFrame) -> None:
    """Volume bars coloured green/red to match candle direction."""
    bull, bear = "#26a69a", "#ef5350"
    vol_max = float(df["Volume"].max())
    for i, (_, row) in enumerate(df.iterrows()):
        col = bull if float(row["Close"]) >= float(row["Open"]) else bear
        ax.bar(i, float(row["Volume"]), width=0.8, color=col, alpha=0.7, zorder=2)
    # 20-bar SMA of volume
    vol_sma = df["Volume"].rolling(20).mean()
    ax.plot(
        range(len(df)),
        vol_sma.values,
        color="#ffeb3b",
        linewidth=0.9,
        alpha=0.8,
        zorder=3,
        label="Vol SMA 20",
    )
    ax.set_ylim(0, vol_max * 1.15)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K")
    )
    ax.set_ylabel("Volume", color="#b2b5be", fontsize=8)
    ax.tick_params(colors="#b2b5be", labelsize=7)
    ax.set_facecolor("#131722")
    ax.grid(color="#2a2e39", linewidth=0.4, axis="y", zorder=0)
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")


def format_x_axis(ax, df: pd.DataFrame, max_ticks: int = 10) -> None:
    n = len(df)
    positions = np.linspace(0, n - 1, min(max_ticks, n), dtype=int)
    ax.set_xticks(positions)
    ax.set_xticklabels(
        [df.index[i].strftime("%Y-%m-%d") for i in positions], rotation=35, ha="right", fontsize=7
    )


# ── filtering helpers ─────────────────────────────────────────────────────────


def select_zones(zones: list, current_price: float, side: str, max_keep: int) -> list:
    """
    Return up to max_keep zones on the requested side of current price.
    side='support'    → zones below current price, sorted nearest first
    side='resistance' → zones above current price, sorted nearest first
    No proximity cutoff — distance is shown on the label instead.
    """
    if side == "support":
        candidates = [z for z in zones if z["center_price"] < current_price]
        candidates.sort(key=lambda z: z["center_price"], reverse=True)  # nearest first
    else:
        candidates = [z for z in zones if z["center_price"] > current_price]
        candidates.sort(key=lambda z: z["center_price"])  # nearest first
    return candidates[:max_keep]


def select_trendlines(trendlines: list, current_price: float, side: str, max_keep: int = 1) -> list:
    """
    Return up to max_keep trendlines on the correct side of current price.
    Support trendlines must have current_value < current_price.
    Resistance trendlines must have current_value > current_price.
    No proximity cutoff — distance is shown on the label instead.
    """
    if side == "support":
        candidates = [
            tl
            for tl in trendlines
            if tl["current_value"] < current_price and tl["touch_count"] >= MIN_TL_TOUCHES
        ]
        candidates.sort(key=lambda tl: tl["current_value"], reverse=True)  # nearest first
    else:
        candidates = [
            tl
            for tl in trendlines
            if tl["current_value"] > current_price and tl["touch_count"] >= MIN_TL_TOUCHES
        ]
        candidates.sort(key=lambda tl: tl["current_value"])  # nearest first
    return candidates[:max_keep]


# ── fibonacci helpers ─────────────────────────────────────────────────────────


def find_fib_pivots(df: pd.DataFrame, p_highs: list, p_lows: list, current_price: float):
    """
    Correct bullish Fibonacci anchor logic for an upside move:

      Time order:  swing_low (base) → swing_high (peak) → current price (pullback)

      Step 1 — swing_high: most recent pivot high ABOVE current price.
               This is the peak price pulled back FROM.

      Step 2 — swing_low: most recent pivot low that is BELOW current price
               AND came BEFORE swing_high in time.
               This is the base of the rally that created swing_high.

    Retracement levels sit between swing_low and swing_high, showing
    how deep the current pullback is.
    Extension targets (T1/T2/T3) project above swing_high.
    """
    n = len(df)
    lookback_start = max(0, n - 120)

    recent_lows = [p for p in p_lows if p["index"] >= lookback_start]
    recent_highs = [p for p in p_highs if p["index"] >= lookback_start]

    if not recent_lows or not recent_highs:
        return None

    # Step 1 — swing_high: most recent pivot high above current price
    # (the peak that current price has pulled back from)
    highs_above = [p for p in recent_highs if p["price"] > current_price * 1.001]
    if not highs_above:
        return None
    swing_high_p = max(highs_above, key=lambda p: p["index"])

    # Step 2 — swing_low: most recent pivot low that is below current price
    # AND came before swing_high (i.e. the base of the rally that led to swing_high)
    lows_before_high = [
        p
        for p in recent_lows
        if p["price"] < current_price * 0.999 and p["index"] < swing_high_p["index"]
    ]
    if not lows_before_high:
        return None
    swing_low_p = max(lows_before_high, key=lambda p: p["index"])

    # Sanity: the move must be at least 3% to be meaningful
    move_pct = (swing_high_p["price"] - swing_low_p["price"]) / swing_low_p["price"]
    if move_pct < 0.03:
        return None

    return {
        "swing_low": swing_low_p["price"],
        "swing_low_idx": swing_low_p["index"],
        "swing_high": swing_high_p["price"],
        "swing_high_idx": swing_high_p["index"],
    }


def find_fib_pivots_bearish(df: pd.DataFrame, p_highs: list, p_lows: list, current_price: float):
    """
    Bearish Fibonacci anchor — mirror of find_fib_pivots for downside moves.

      Time order:  swing_high (peak, first) → swing_low (trough, second) → current price (bounce)

      Step 1 — swing_low : most recent pivot low BELOW current price (the recent trough).
      Step 2 — swing_high: most recent pivot high ABOVE current price that came BEFORE
               swing_low (the peak where the drop originated).

    Retracement levels between swing_low and swing_high act as RESISTANCE during the bounce.
    Extension targets (T2/T3) project BELOW swing_low as short targets.
    """
    n = len(df)
    lookback_start = max(0, n - 120)

    recent_lows = [p for p in p_lows if p["index"] >= lookback_start]
    recent_highs = [p for p in p_highs if p["index"] >= lookback_start]

    if not recent_lows or not recent_highs:
        return None

    # Step 1 — most recent pivot low below price (the trough of the downswing)
    lows_below = [p for p in recent_lows if p["price"] < current_price * 0.999]
    if not lows_below:
        return None
    swing_low_p = max(lows_below, key=lambda p: p["index"])

    # Step 2 — most recent pivot high above price AND before swing_low
    highs_before_low = [
        p
        for p in recent_highs
        if p["price"] > current_price * 1.001 and p["index"] < swing_low_p["index"]
    ]
    if not highs_before_low:
        return None
    swing_high_p = max(highs_before_low, key=lambda p: p["index"])

    move_pct = (swing_high_p["price"] - swing_low_p["price"]) / swing_low_p["price"]
    if move_pct < 0.03:
        return None

    return {
        "swing_low": swing_low_p["price"],
        "swing_low_idx": swing_low_p["index"],
        "swing_high": swing_high_p["price"],
        "swing_high_idx": swing_high_p["index"],
    }


def draw_fib_levels(
    ax,
    swing_low: float,
    swing_high: float,
    swing_low_idx: int,
    swing_high_idx: int,
    n: int,
    current_price: float,
    direction: str = "bullish",
) -> None:
    """
    Draw Fibonacci levels for either a bullish or bearish setup.

    Bullish (direction='bullish'):
      Anchor: swing_low (base of rally) → swing_high (peak).
      Retracement levels between them = SUPPORT during pullback (amber/gold, dashed).
      Extensions ABOVE swing_high = upside targets T2/T3 (purple, bold dashed).

    Bearish (direction='bearish'):
      Anchor: swing_high (peak of drop) → swing_low (trough).
      Retracement levels between them = RESISTANCE during bounce (red/orange, dotted).
      Extensions BELOW swing_low = downside targets T2/T3 (crimson, bold dotted).
    """
    move = swing_high - swing_low
    if move <= 0:
        return

    # Shared retracement price levels (same math, different meaning per direction)
    RETRACE_RATIOS = [
        (0.000, "0.0"),
        (0.236, "0.236"),
        (0.382, "0.382"),
        (0.500, "0.500"),
        (0.618, "0.618 ★"),
        (0.786, "0.786"),
        (1.000, "1.0"),
    ]

    if direction == "bullish":
        # Levels measured DOWN from swing_high (support when price pulls back)
        # Color: red at top → green at bottom (high to low)
        RETRACE_COLORS = [
            "#ef5350",
            "#ffd54f",
            "#ffb300",
            "#ff9800",
            "#ff6d00",
            "#bf360c",
            "#69f0ae",
        ]
        ls = "--"
        zone_color = "#ffd54f"
        prefix = "▲"

        for (ratio, label), color in zip(RETRACE_RATIOS, RETRACE_COLORS, strict=True):
            price = swing_high - ratio * move
            ax.axhline(price, color=color, linewidth=0.75, linestyle=ls, alpha=0.45, zorder=2)
            ax.text(
                n + 0.5,
                price,
                f"{prefix} {label}  {price:.2f}",
                color=color,
                fontsize=5.5,
                va="center",
                alpha=0.72,
                zorder=7,
            )

        # Upside extensions above swing_high
        for ratio, color, label in [(1.272, "#ce93d8", "1.272 T2"), (1.618, "#9c27b0", "1.618 T3")]:
            price = swing_low + ratio * move
            ax.axhline(price, color=color, linewidth=1.1, linestyle=ls, alpha=0.85, zorder=2)
            ax.text(
                n + 0.5,
                price,
                f"{prefix} {label}  {price:.2f}",
                color=color,
                fontsize=6.5,
                va="center",
                alpha=0.95,
                zorder=7,
                fontweight="bold",
            )

        ax.axhspan(swing_low, swing_high, alpha=0.03, color=zone_color, zorder=1)

    else:  # bearish
        # Levels measured UP from swing_low (resistance when price bounces)
        # Color: green at bottom → red at top (low to high)
        RETRACE_COLORS = [
            "#69f0ae",
            "#bf360c",
            "#ff6d00",
            "#ff9800",
            "#ffb300",
            "#ffd54f",
            "#ef5350",
        ]
        ls = ":"
        zone_color = "#ef5350"
        prefix = "▼"

        for (ratio, label), color in zip(RETRACE_RATIOS, RETRACE_COLORS, strict=True):
            price = swing_low + ratio * move
            ax.axhline(price, color=color, linewidth=0.75, linestyle=ls, alpha=0.45, zorder=2)
            ax.text(
                n + 0.5,
                price,
                f"{prefix} {label}  {price:.2f}",
                color=color,
                fontsize=5.5,
                va="center",
                alpha=0.72,
                zorder=7,
            )

        # Downside extensions below swing_low
        for ratio, color, label in [(1.272, "#ef9a9a", "1.272 T2"), (1.618, "#b71c1c", "1.618 T3")]:
            price = swing_high - ratio * move
            ax.axhline(price, color=color, linewidth=1.1, linestyle=ls, alpha=0.85, zorder=2)
            ax.text(
                n + 0.5,
                price,
                f"{prefix} {label}  {price:.2f}",
                color=color,
                fontsize=6.5,
                va="center",
                alpha=0.95,
                zorder=7,
                fontweight="bold",
            )

        ax.axhspan(swing_low, swing_high, alpha=0.03, color=zone_color, zorder=1)


# ── chart builder (callable from generate_calls) ──────────────────────────────


def save_chart(
    ticker: str,
    period: str,
    df: pd.DataFrame,
    result: dict,
    patterns: list,
    p_highs: list,
    p_lows: list,
) -> str:
    """
    Build and save the technical chart for *ticker*.
    Patterns must already have at_level and signal fields set.
    Returns the output file path.
    """
    import os

    os.makedirs("reports", exist_ok=True)

    current_price = float(df["Close"].iloc[-1])
    n = len(df)
    price_lo = float(df["Low"].min())
    price_hi = float(df["High"].max())
    price_range = price_hi - price_lo

    vis_sup_zones = select_zones(
        result.get("support_zones", []), current_price, "support", MAX_SUP_ZONES
    )
    vis_res_zones = select_zones(
        result.get("resistance_zones", []), current_price, "resistance", MAX_RES_ZONES
    )
    vis_lt_sup = select_trendlines(
        result.get("long_term_support_trendlines", []), current_price, "support"
    )
    vis_lt_res = select_trendlines(
        result.get("long_term_resistance_trendlines", []), current_price, "resistance"
    )
    vis_st_sup = select_trendlines(
        result.get("short_term_support_trendlines", []), current_price, "support"
    )
    vis_st_res = select_trendlines(
        result.get("short_term_resistance_trendlines", []), current_price, "resistance"
    )

    hl_low_idx = set()
    hl_high_idx = set()
    for tl in vis_lt_sup + vis_st_sup:
        hl_low_idx.update(tl.get("touch_index_list", []))
    for tl in vis_lt_res + vis_st_res:
        hl_high_idx.update(tl.get("touch_index_list", []))

    def dist_label(price):
        pct = (price - current_price) / current_price * 100
        return f"  ({pct:+.1f}%)"

    fig, (ax, ax_vol) = plt.subplots(
        2,
        1,
        figsize=(20, 12),
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04},
        sharex=True,
        layout="constrained",
    )
    fig.patch.set_facecolor("#131722")
    for a in (ax, ax_vol):
        a.set_facecolor("#131722")
        for spine in a.spines.values():
            spine.set_color("#2a2e39")
    ax.tick_params(colors="#b2b5be", labelsize=7)
    ax.yaxis.label.set_color("#b2b5be")
    ax.xaxis.label.set_color("#b2b5be")
    ax.grid(color="#2a2e39", linewidth=0.5, zorder=0)

    draw_candlesticks(ax, df)
    draw_pivot_markers(ax, p_highs, p_lows, hl_high_idx=hl_high_idx, hl_low_idx=hl_low_idx)

    for zone in vis_sup_zones:
        draw_horizontal_zone(ax, zone, "#00e676", n, dist_label(zone["center_price"]))
    for zone in vis_res_zones:
        draw_horizontal_zone(ax, zone, "#ff5252", n, dist_label(zone["center_price"]))

    for tl in vis_lt_sup:
        draw_channel(
            ax,
            tl,
            df,
            "#00e676",
            "-",
            f"LT Sup  {tl['current_value']:.2f} ({tl['touch_count']} touches)"
            f"{dist_label(tl['current_value'])}",
            line_type="support",
        )
    for tl in vis_lt_res:
        draw_channel(
            ax,
            tl,
            df,
            "#ff5252",
            "-",
            f"LT Res  {tl['current_value']:.2f} ({tl['touch_count']} touches)"
            f"{dist_label(tl['current_value'])}",
            line_type="resistance",
        )
    for tl in vis_st_sup:
        draw_channel(
            ax,
            tl,
            df,
            "#69f0ae",
            "--",
            f"ST Sup  {tl['current_value']:.2f} ({tl['touch_count']} touches)"
            f"{dist_label(tl['current_value'])}",
            line_type="support",
        )
    for tl in vis_st_res:
        draw_channel(
            ax,
            tl,
            df,
            "#ff8a80",
            "--",
            f"ST Res  {tl['current_value']:.2f} ({tl['touch_count']} touches)"
            f"{dist_label(tl['current_value'])}",
            line_type="resistance",
        )

    draw_patterns(ax, patterns, df, price_range)

    # Bullish Fibonacci: swing_low (first) → swing_high (second) → pullback
    # Shows support levels + upside extension targets
    fib_bull = find_fib_pivots(df, p_highs, p_lows, current_price)
    if fib_bull:
        draw_fib_levels(ax, **fib_bull, n=n, current_price=current_price, direction="bullish")
        bull_move = fib_bull["swing_high"] - fib_bull["swing_low"]
        t3_up = fib_bull["swing_low"] + 1.618 * bull_move
        if t3_up > price_hi:
            price_hi = t3_up
            price_range = price_hi - price_lo

    # Bearish Fibonacci: swing_high (first) → swing_low (second) → bounce
    # Shows resistance levels + downside extension targets
    fib_bear = find_fib_pivots_bearish(df, p_highs, p_lows, current_price)
    if fib_bear:
        draw_fib_levels(ax, **fib_bear, n=n, current_price=current_price, direction="bearish")
        bear_move = fib_bear["swing_high"] - fib_bear["swing_low"]
        t3_dn = fib_bear["swing_high"] - 1.618 * bear_move
        if t3_dn < price_lo:
            price_lo = t3_dn
            price_range = price_hi - price_lo

    ax.axhline(
        current_price,
        color="#ffeb3b",
        linewidth=0.9,
        linestyle=":",
        alpha=0.8,
        label=f"Price  {current_price:.2f}",
    )

    draw_volume(ax_vol, df)

    price_pad = price_range * 0.04
    ax.set_xlim(-1, n + 7)
    ax.set_ylim(price_lo - price_pad * 3, price_hi + price_pad * 3)
    ax_vol.set_xlim(-1, n + 7)
    format_x_axis(ax_vol, df)
    ax.xaxis.set_visible(False)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))

    zone_patches = []
    if vis_sup_zones:
        zone_patches.append(
            mpatches.Patch(
                color="#00e676", alpha=0.45, label=f"Support zone  (x{len(vis_sup_zones)})"
            )
        )
    if vis_res_zones:
        zone_patches.append(
            mpatches.Patch(
                color="#ff5252", alpha=0.45, label=f"Resistance zone  (x{len(vis_res_zones)})"
            )
        )

    handles, labels_leg = ax.get_legend_handles_labels()
    ax.legend(
        handles=handles + zone_patches,
        labels=labels_leg + [p.get_label() for p in zone_patches],
        loc="upper left",
        facecolor="#1e222d",
        edgecolor="#2a2e39",
        labelcolor="#b2b5be",
        fontsize=8,
        framealpha=0.9,
        markerscale=0.9,
    )

    ax.set_title(
        f"{ticker}  —  Market Structure  |  {result.get('context', '')}  |  {period}",
        color="#d1d4dc",
        fontsize=11,
        pad=10,
    )
    ax.set_ylabel("Price", color="#b2b5be")

    out_file = f"reports/{ticker}_technical_{period}.png"
    plt.savefig(out_file, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close()
    return out_file


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    period = sys.argv[2] if len(sys.argv) > 2 else "1y"

    logger.info(f"  Downloading {ticker} ({period}) ...")
    raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        logger.warning("No data returned.")
        return
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
    logger.info(f"  {len(df)} bars  |  {df['Low'].min():.2f} - {df['High'].max():.2f}")

    engine = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
    pattern_finder = PatternFinder(
        price_tolerance=0.03, min_pullback=0.03, recent_candle_bars=15, recent_chart_bars=30
    )
    current_price = float(df["Close"].iloc[-1])

    logger.info("  Running full-period analysis ...")
    result = engine.analyze_structure(df)
    p_highs, p_lows = engine._find_pivots(df)
    patterns = pattern_finder.find_all(df, p_highs, p_lows)
    patterns += pattern_finder.find_forming(df, p_highs, p_lows)

    vis_sup_zones = select_zones(result["support_zones"], current_price, "support", MAX_SUP_ZONES)
    vis_res_zones = select_zones(
        result["resistance_zones"], current_price, "resistance", MAX_RES_ZONES
    )
    vis_lt_sup = select_trendlines(result["long_term_support_trendlines"], current_price, "support")
    vis_lt_res = select_trendlines(
        result["long_term_resistance_trendlines"], current_price, "resistance"
    )
    vis_st_sup = select_trendlines(
        result["short_term_support_trendlines"], current_price, "support"
    )
    vis_st_res = select_trendlines(
        result["short_term_resistance_trendlines"], current_price, "resistance"
    )

    annotate_at_levels(
        patterns, vis_sup_zones, vis_res_zones, vis_lt_sup + vis_st_sup, vis_lt_res + vis_st_res, df
    )
    compute_entry_signals(patterns, df)

    hl_low_idx = set()
    hl_high_idx = set()
    for tl in vis_lt_sup + vis_st_sup:
        hl_low_idx.update(tl.get("touch_index_list", []))
    for tl in vis_lt_res + vis_st_res:
        hl_high_idx.update(tl.get("touch_index_list", []))

    logger.debug(f"  Context : {result['context']}")
    logger.debug(
        f"  Visible -> sup zones={len(vis_sup_zones)} res zones={len(vis_res_zones)} | "
        f"TL: LT sup={len(vis_lt_sup)} LT res={len(vis_lt_res)} "
        f"ST sup={len(vis_st_sup)} ST res={len(vis_st_res)}"
    )
    logger.debug(
        f"  Pivots  -> highs={len(p_highs)} lows={len(p_lows)} | "
        f"TL-anchored highs={len(hl_high_idx)} lows={len(hl_low_idx)}"
    )
    if patterns:
        logger.debug(
            f"\n  {'Pattern':<28s} {'Type':<8s}  {'Signal':<12s} {'Entry':>10s}  {'Stop':>10s}  {'Risk%':>6s}  {'VolR':>5s} {'Date'}"
        )
        logger.debug("  " + "-" * 100)
        for p in patterns:
            bar_date = df.index[p["completed_bar"]].date()
            state_tag = " [F]" if p.get("forming") else "    "
            level_tag = f"  ** {p['at_level']} **" if p.get("at_level") else ""
            sig = p.get("signal", "")
            entry = f"{p['entry_price']:.2f}" if p.get("entry_price") else "   --"
            stop = f"{p['stop_loss']:.2f}" if p.get("stop_loss") else "   --"
            risk = f"{p['risk_pct']:.1f}%" if p.get("risk_pct") else "  --"
            vol_r = f"{p.get('vol_ratio', 0):.2f}x"
            vol_ok = " [V]" if p.get("vol_confirmed") else ""
            logger.debug(
                f"  {p['name']:<28s} [{p['type']:<8s}]{state_tag} {sig:<12s} {entry:>10s}  {stop:>10s}  {risk:>6s}  {vol_r}{vol_ok}  {bar_date}{level_tag}"
            )

    out = save_chart(ticker, period, df, result, patterns, p_highs, p_lows)
    logger.debug(f"  Chart saved -> {out}")


if __name__ == "__main__":
    main()
