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

import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import yfinance as yf

from stock_scanner.engine.technical import MarketStructureEngine


# ── constants ─────────────────────────────────────────────────────────────────

MIN_TL_TOUCHES   = 3   # trendline must have at least this many pivot touches
MAX_SUP_ZONES    = 3   # nearest support zones to display (below price)
MAX_RES_ZONES    = 3   # nearest resistance zones to display (above price)


# ── drawing helpers ───────────────────────────────────────────────────────────

def draw_candlesticks(ax, df: pd.DataFrame) -> None:
    bull, bear = "#26a69a", "#ef5350"
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        col = bull if c >= o else bear
        ax.plot([i, i], [l, h], color=col, linewidth=0.8, zorder=2)
        body_lo, body_hi = min(o, c), max(o, c)
        ax.add_patch(mpatches.Rectangle(
            (i - 0.4, body_lo), 0.8, max(body_hi - body_lo, 0.001 * c),
            facecolor=col, edgecolor=col, linewidth=0.4, zorder=3
        ))


def draw_pivot_markers(ax, p_highs: list, p_lows: list,
                       hl_high_idx: set = None,
                       hl_low_idx: set = None) -> None:
    """
    Circles placed exactly at the wick tip (High for swing highs, Low for
    swing lows).  Pivots that anchor a visible trendline get a larger,
    brighter circle with a white outline so the connection is obvious.
    """
    hl_high_idx = hl_high_idx or set()
    hl_low_idx  = hl_low_idx  or set()

    # ── swing highs — circle at the High wick tip ──
    reg_h = [p for p in p_highs if p["index"] not in hl_high_idx]
    lit_h = [p for p in p_highs if p["index"] in hl_high_idx]

    if reg_h:
        ax.scatter([p["index"] for p in reg_h],
                   [p["price"] for p in reg_h],
                   marker="o", color="#ff6b6b", s=20,
                   zorder=6, alpha=0.75, linewidths=0)
    if lit_h:
        ax.scatter([p["index"] for p in lit_h],
                   [p["price"] for p in lit_h],
                   marker="o", color="#ff1744", s=50,
                   zorder=7, alpha=1.0, linewidths=1.2,
                   edgecolors="#ffffff", label="Swing High (TL anchor)")

    # ── swing lows — circle at the Low wick tip ──
    reg_l = [p for p in p_lows if p["index"] not in hl_low_idx]
    lit_l = [p for p in p_lows if p["index"] in hl_low_idx]

    if reg_l:
        ax.scatter([p["index"] for p in reg_l],
                   [p["price"] for p in reg_l],
                   marker="o", color="#69f0ae", s=20,
                   zorder=6, alpha=0.75, linewidths=0)
    if lit_l:
        ax.scatter([p["index"] for p in lit_l],
                   [p["price"] for p in lit_l],
                   marker="o", color="#00e676", s=50,
                   zorder=7, alpha=1.0, linewidths=1.2,
                   edgecolors="#ffffff", label="Swing Low (TL anchor)")

    # legend entries for dim markers
    if reg_h:
        ax.scatter([], [], marker="o", color="#ff6b6b", s=20,
                   alpha=0.75, linewidths=0, label="Swing High")
    if reg_l:
        ax.scatter([], [], marker="o", color="#69f0ae", s=20,
                   alpha=0.75, linewidths=0, label="Swing Low")


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
            offset = float(df["Low"].iloc[k]) - line_val   # negative
            if offset < best_offset:
                best_offset = offset
    return b + best_offset


def draw_channel(ax, tl: dict, df: pd.DataFrame, color: str,
                 linestyle: str = "-", label: str = "",
                 line_type: str = "support") -> None:
    """
    Draw a price channel: base trendline (solid) + parallel channel line
    (dashed, same colour, lighter) + shaded band between them.
    Extended to the right edge of the chart so the projected level is visible.
    """
    m, b  = tl["slope"], tl["intercept"]
    b_ch  = channel_intercept(df, tl, line_type)
    n     = len(df)
    x0    = tl["start_index"]
    x1    = n - 1   # extend to right edge

    xs     = np.array([x0, x1])
    y_base = m * xs + b
    y_chan = m * xs + b_ch

    # shaded band
    x_fill = np.arange(x0, x1 + 1)
    ax.fill_between(x_fill, m * x_fill + b, m * x_fill + b_ch,
                    alpha=0.07, color=color, zorder=1)

    # base line (solid)
    ax.plot(xs, y_base, color=color, linewidth=1.7,
            linestyle=linestyle, alpha=0.90, zorder=4,
            label=label if label else None)

    # channel line (dashed, lighter)
    ax.plot(xs, y_chan, color=color, linewidth=1.0,
            linestyle="--", alpha=0.55, zorder=4)

    # price label for channel line at right edge
    ch_val_now = m * (n - 1) + b_ch
    ax.text(n + 0.5, ch_val_now, f"{ch_val_now:.2f}",
            color=color, fontsize=7, va="center", alpha=0.7, zorder=7)


def draw_horizontal_zone(ax, zone: dict, color: str, chart_bars: int,
                          label_suffix: str = "") -> None:
    """Shaded band + dashed centre line + price label on the right edge."""
    lo, hi = zone["price_range"]
    if lo == hi:
        hi = lo * 1.001
    ax.axhspan(lo, hi, alpha=0.18, color=color, zorder=1)
    center = zone["center_price"]
    ax.axhline(center, color=color, linewidth=0.8, linestyle="--",
               alpha=0.60, zorder=1)
    ax.text(chart_bars + 0.5, center,
            f"{center:.2f}{label_suffix}",
            color=color, fontsize=7, va="center",
            fontweight="bold", zorder=7)


def draw_volume(ax, df: pd.DataFrame) -> None:
    """Volume bars coloured green/red to match candle direction."""
    bull, bear = "#26a69a", "#ef5350"
    vol_max = float(df["Volume"].max())
    for i, (_, row) in enumerate(df.iterrows()):
        col = bull if float(row["Close"]) >= float(row["Open"]) else bear
        ax.bar(i, float(row["Volume"]), width=0.8,
               color=col, alpha=0.7, zorder=2)
    # 20-bar SMA of volume
    vol_sma = df["Volume"].rolling(20).mean()
    ax.plot(range(len(df)), vol_sma.values,
            color="#ffeb3b", linewidth=0.9, alpha=0.8, zorder=3, label="Vol SMA 20")
    ax.set_ylim(0, vol_max * 1.15)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1e3:.0f}K"))
    ax.set_ylabel("Volume", color="#b2b5be", fontsize=8)
    ax.tick_params(colors="#b2b5be", labelsize=7)
    ax.set_facecolor("#131722")
    ax.grid(color="#2a2e39", linewidth=0.4, axis="y", zorder=0)
    for spine in ax.spines.values():
        spine.set_color("#2a2e39")


def format_x_axis(ax, df: pd.DataFrame, max_ticks: int = 10) -> None:
    n         = len(df)
    positions = np.linspace(0, n - 1, min(max_ticks, n), dtype=int)
    ax.set_xticks(positions)
    ax.set_xticklabels(
        [df.index[i].strftime("%Y-%m-%d") for i in positions],
        rotation=35, ha="right", fontsize=7
    )


# ── filtering helpers ─────────────────────────────────────────────────────────

def select_zones(zones: list, current_price: float,
                 side: str, max_keep: int) -> list:
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


def select_trendlines(trendlines: list, current_price: float,
                      side: str, max_keep: int = 1) -> list:
    """
    Return up to max_keep trendlines on the correct side of current price.
    Support trendlines must have current_value < current_price.
    Resistance trendlines must have current_value > current_price.
    No proximity cutoff — distance is shown on the label instead.
    """
    if side == "support":
        candidates = [tl for tl in trendlines
                      if tl["current_value"] < current_price
                      and tl["touch_count"] >= MIN_TL_TOUCHES]
        candidates.sort(key=lambda tl: tl["current_value"], reverse=True)  # nearest first
    else:
        candidates = [tl for tl in trendlines
                      if tl["current_value"] > current_price
                      and tl["touch_count"] >= MIN_TL_TOUCHES]
        candidates.sort(key=lambda tl: tl["current_value"])  # nearest first
    return candidates[:max_keep]


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    period = sys.argv[2] if len(sys.argv) > 2 else "1y"

    print(f"  Downloading {ticker} ({period}) ...")
    raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        print("No data returned.")
        return
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
    print(f"  {len(df)} bars  |  {df['Low'].min():.2f} - {df['High'].max():.2f}")

    engine        = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
    current_price = float(df["Close"].iloc[-1])
    n             = len(df)
    price_lo      = float(df["Low"].min())
    price_hi      = float(df["High"].max())
    price_range   = price_hi - price_lo

    # ── Full-period analysis ──────────────────────────────────────────────
    print("  Running full-period analysis ...")
    result           = engine.analyze_structure(df)
    p_highs, p_lows  = engine._find_pivots(df)

    vis_sup_zones = select_zones(result["support_zones"],    current_price, "support",    MAX_SUP_ZONES)
    vis_res_zones = select_zones(result["resistance_zones"], current_price, "resistance", MAX_RES_ZONES)
    vis_lt_sup    = select_trendlines(result["long_term_support_trendlines"],    current_price, "support")
    vis_lt_res    = select_trendlines(result["long_term_resistance_trendlines"], current_price, "resistance")
    vis_st_sup    = select_trendlines(result["short_term_support_trendlines"],   current_price, "support")
    vis_st_res    = select_trendlines(result["short_term_resistance_trendlines"],current_price, "resistance")

    # ── Collect trendline touch indices for highlighted markers ───────────
    hl_low_idx  = set()
    hl_high_idx = set()
    for tl in vis_lt_sup + vis_st_sup:
        hl_low_idx.update(tl.get("touch_index_list", []))
    for tl in vis_lt_res + vis_st_res:
        hl_high_idx.update(tl.get("touch_index_list", []))

    def dist_label(price):
        pct = (price - current_price) / current_price * 100
        return f"  ({pct:+.1f}%)"

    print(f"  Context : {result['context']}")
    print(f"  Visible -> sup zones={len(vis_sup_zones)} res zones={len(vis_res_zones)} | "
          f"TL: LT sup={len(vis_lt_sup)} LT res={len(vis_lt_res)} "
          f"ST sup={len(vis_st_sup)} ST res={len(vis_st_res)}")
    print(f"  Pivots  -> highs={len(p_highs)} lows={len(p_lows)} | "
          f"TL-anchored highs={len(hl_high_idx)} lows={len(hl_low_idx)}")

    # ── Build chart ───────────────────────────────────────────────────────
    fig, (ax, ax_vol) = plt.subplots(
        2, 1, figsize=(20, 12),
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0.04},
        sharex=True, layout="constrained"
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

    # 1. Candlesticks
    draw_candlesticks(ax, df)

    # 2. Pivot markers — dim for all, bright+large for TL anchors
    draw_pivot_markers(ax, p_highs, p_lows,
                       hl_high_idx=hl_high_idx, hl_low_idx=hl_low_idx)

    # 3. Support zones — nearest below price, always shown with distance %
    for zone in vis_sup_zones:
        draw_horizontal_zone(ax, zone, "#00e676", n, dist_label(zone["center_price"]))

    # 4. Resistance zones — nearest above price, always shown with distance %
    for zone in vis_res_zones:
        draw_horizontal_zone(ax, zone, "#ff5252", n, dist_label(zone["center_price"]))

    # 5. LT channels (solid base + dashed parallel + shaded band)
    for tl in vis_lt_sup:
        draw_channel(ax, tl, df, "#00e676", "-",
                     f"LT Sup channel  {tl['current_value']:.2f}"
                     f"  ({tl['touch_count']} touches)"
                     f"{dist_label(tl['current_value'])}",
                     line_type="support")
    for tl in vis_lt_res:
        draw_channel(ax, tl, df, "#ff5252", "-",
                     f"LT Res channel  {tl['current_value']:.2f}"
                     f"  ({tl['touch_count']} touches)"
                     f"{dist_label(tl['current_value'])}",
                     line_type="resistance")

    # 6. ST channels (dashed base)
    for tl in vis_st_sup:
        draw_channel(ax, tl, df, "#69f0ae", "--",
                     f"ST Sup channel  {tl['current_value']:.2f}"
                     f"  ({tl['touch_count']} touches)"
                     f"{dist_label(tl['current_value'])}",
                     line_type="support")
    for tl in vis_st_res:
        draw_channel(ax, tl, df, "#ff8a80", "--",
                     f"ST Res channel  {tl['current_value']:.2f}"
                     f"  ({tl['touch_count']} touches)"
                     f"{dist_label(tl['current_value'])}",
                     line_type="resistance")

    # 7. Current price line
    ax.axhline(current_price, color="#ffeb3b", linewidth=0.9,
               linestyle=":", alpha=0.8, label=f"Price  {current_price:.2f}")

    # 8. Volume panel
    draw_volume(ax_vol, df)

    # 9. Axes
    price_pad = price_range * 0.04
    ax.set_xlim(-1, n + 7)
    ax.set_ylim(price_lo - price_pad, price_hi + price_pad)
    ax_vol.set_xlim(-1, n + 7)
    format_x_axis(ax_vol, df)          # x labels on bottom panel only
    ax.xaxis.set_visible(False)        # hide x labels on price panel
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))

    # 10. Legend (price panel)
    zone_patches = []
    if vis_sup_zones:
        zone_patches.append(mpatches.Patch(color="#00e676", alpha=0.45,
            label=f"Support zone  (x{len(vis_sup_zones)})"))
    if vis_res_zones:
        zone_patches.append(mpatches.Patch(color="#ff5252", alpha=0.45,
            label=f"Resistance zone  (x{len(vis_res_zones)})"))

    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + zone_patches,
              labels=labels + [p.get_label() for p in zone_patches],
              loc="upper left", facecolor="#1e222d", edgecolor="#2a2e39",
              labelcolor="#b2b5be", fontsize=8, framealpha=0.9,
              markerscale=0.9)

    ax.set_title(
        f"{ticker}  -  Market Structure  |  {result['context']}  |  {period}",
        color="#d1d4dc", fontsize=11, pad=10
    )
    ax.set_ylabel("Price (USD)", color="#b2b5be")

    out_file = f"reports/{ticker}_technical_{period}.png"
    plt.savefig(out_file, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Chart saved -> {out_file}")


if __name__ == "__main__":
    main()
