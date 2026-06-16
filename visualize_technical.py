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

PROXIMITY_PCT    = 0.15    # ±15 % of current price for normal filter
MIN_TL_TOUCHES   = 3       # trendline must have at least this many pivot touches
MIN_ZONE_PIVOTS  = 2       # zone must have at least this many pivot touches
ST_FALLBACK_BARS = 63      # ~3 months of trading days for short-term fallback


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


def draw_trendline(ax, tl: dict, df_len: int, color: str,
                   linestyle: str = "-", label: str = "",
                   y_lo: float = 0.0, y_hi: float = 1e9) -> None:
    """
    Draw the trendline and place a white-outlined circle at every touch point
    so it's visually clear which candles anchor the line.
    """
    m, b = tl["slope"], tl["intercept"]
    x0   = tl["start_index"]

    # clip line to visible price range
    x1 = x0
    for xi in range(x0, df_len):
        yi = m * xi + b
        if y_lo * 0.92 <= yi <= y_hi * 1.08:
            x1 = xi
        else:
            break

    ax.plot([x0, x1], [m * x0 + b, m * x1 + b],
            color=color, linewidth=1.7, linestyle=linestyle,
            alpha=0.88, zorder=4, label=label if label else None)

    # circle dots at each touch point on the line
    for xi in tl.get("touch_index_list", []):
        if 0 <= xi < df_len:
            yi = m * xi + b
            if y_lo * 0.92 <= yi <= y_hi * 1.08:
                ax.scatter([xi], [yi], s=50, color=color, marker="o",
                           zorder=8, linewidths=1.2, edgecolors="#ffffff",
                           alpha=0.95)


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


def format_x_axis(ax, df: pd.DataFrame, max_ticks: int = 10) -> None:
    n         = len(df)
    positions = np.linspace(0, n - 1, min(max_ticks, n), dtype=int)
    ax.set_xticks(positions)
    ax.set_xticklabels(
        [df.index[i].strftime("%Y-%m-%d") for i in positions],
        rotation=35, ha="right", fontsize=7
    )


# ── filtering helpers ─────────────────────────────────────────────────────────

def filter_zones(zones: list, current_price: float, max_keep: int) -> list:
    lo = current_price * (1 - PROXIMITY_PCT)
    hi = current_price * (1 + PROXIMITY_PCT)
    kept = [z for z in zones
            if lo <= z["center_price"] <= hi
            and z["touch_count"] >= MIN_ZONE_PIVOTS]
    kept.sort(key=lambda z: z["strength_score"], reverse=True)
    return kept[:max_keep]


def filter_trendlines(trendlines: list, current_price: float) -> list:
    lo = current_price * (1 - PROXIMITY_PCT)
    hi = current_price * (1 + PROXIMITY_PCT)
    kept = [tl for tl in trendlines
            if lo <= tl["current_value"] <= hi
            and tl["touch_count"] >= MIN_TL_TOUCHES]
    kept.sort(key=lambda tl: tl["strength_score"], reverse=True)
    return kept[:1]


def nearest_support_zone(zones: list, current_price: float):
    """Return the single closest support zone below current price."""
    below = [z for z in zones
             if z["center_price"] < current_price
             and z["touch_count"] >= MIN_ZONE_PIVOTS]
    if not below:
        return None
    return max(below, key=lambda z: z["center_price"])


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

    vis_sup_zones = filter_zones(result["support_zones"],    current_price, 3)
    vis_res_zones = filter_zones(result["resistance_zones"], current_price, 3)
    vis_lt_sup    = filter_trendlines(result["long_term_support_trendlines"],    current_price)
    vis_lt_res    = filter_trendlines(result["long_term_resistance_trendlines"], current_price)
    vis_st_sup    = filter_trendlines(result["short_term_support_trendlines"],   current_price)
    vis_st_res    = filter_trendlines(result["short_term_resistance_trendlines"],current_price)

    # ── Support fallbacks ─────────────────────────────────────────────────
    st_sup_zones_fallback = []   # short-term timeframe zones
    nearest_sup_zone      = None # nearest zone regardless of distance

    if not vis_sup_zones:
        # Step 1: try 3-month data
        short_bars = min(ST_FALLBACK_BARS, n)
        df_short   = df.iloc[-short_bars:].copy()
        print(f"  No nearby support – re-running on last {short_bars} bars ...")
        result_short             = engine.analyze_structure(df_short)
        _, p_lows_st             = engine._find_pivots(df_short)
        st_sup_zones_fallback    = filter_zones(result_short["support_zones"], current_price, 3)

        # Re-index ST pivots so they align on the full chart
        offset_st   = n - short_bars
        p_lows_st   = [{**p, "index": p["index"] + offset_st} for p in p_lows_st]
        existing_l  = {x["index"] for x in p_lows}
        p_lows      = p_lows + [p for p in p_lows_st if p["index"] not in existing_l]

        # Step 2: if still nothing, show nearest support with distance label
        if not st_sup_zones_fallback:
            nearest_sup_zone = nearest_support_zone(result["support_zones"], current_price)
            if nearest_sup_zone:
                dist = (nearest_sup_zone["center_price"] - current_price) / current_price * 100
                print(f"  Nearest support zone: {nearest_sup_zone['center_price']:.2f}  ({dist:.1f}%)")

    # ── Collect trendline touch indices for highlighted markers ───────────
    hl_low_idx  = set()
    hl_high_idx = set()
    for tl in vis_lt_sup + vis_st_sup:
        hl_low_idx.update(tl.get("touch_index_list", []))
    for tl in vis_lt_res + vis_st_res:
        hl_high_idx.update(tl.get("touch_index_list", []))

    print(f"  Context : {result['context']}")
    print(f"  Visible -> sup zones={len(vis_sup_zones)} "
          f"ST fallback={len(st_sup_zones_fallback)} "
          f"nearest={'yes' if nearest_sup_zone else 'no'} | "
          f"res zones={len(vis_res_zones)} | "
          f"TL: LT sup={len(vis_lt_sup)} LT res={len(vis_lt_res)} "
          f"ST sup={len(vis_st_sup)} ST res={len(vis_st_res)}")
    print(f"  Pivots  -> highs={len(p_highs)} lows={len(p_lows)} | "
          f"TL-anchored highs={len(hl_high_idx)} lows={len(hl_low_idx)}")

    # ── Build chart ───────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(20, 10))
    fig.patch.set_facecolor("#131722")
    ax.set_facecolor("#131722")
    for spine in ax.spines.values():
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

    # 3. Support zones (proximity-filtered, green)
    for zone in vis_sup_zones:
        draw_horizontal_zone(ax, zone, "#00e676", n)

    # 4. Short-term support zones (lighter green + [ST] tag)
    for zone in st_sup_zones_fallback:
        draw_horizontal_zone(ax, zone, "#b9f6ca", n, "  [ST]")

    # 5. Nearest support zone (always shown, dashed if far away)
    if nearest_sup_zone:
        dist_pct = (nearest_sup_zone["center_price"] - current_price) / current_price * 100
        draw_horizontal_zone(ax, nearest_sup_zone, "#69f0ae", n,
                             f"  ({dist_pct:.1f}%)")

    # 6. Resistance zones (red)
    for zone in vis_res_zones:
        draw_horizontal_zone(ax, zone, "#ff5252", n)

    # 7. LT trendlines (solid) — includes circle dots at touch points
    for tl in vis_lt_sup:
        draw_trendline(ax, tl, n, "#00e676", "-",
                       f"LT Support TL  ({tl['touch_count']} touches)",
                       price_lo, price_hi)
    for tl in vis_lt_res:
        draw_trendline(ax, tl, n, "#ff5252", "-",
                       f"LT Resistance TL  ({tl['touch_count']} touches)",
                       price_lo, price_hi)

    # 8. ST trendlines (dashed) — includes circle dots at touch points
    for tl in vis_st_sup:
        draw_trendline(ax, tl, n, "#69f0ae", "--",
                       f"ST Support TL  ({tl['touch_count']} touches)",
                       price_lo, price_hi)
    for tl in vis_st_res:
        draw_trendline(ax, tl, n, "#ff8a80", "--",
                       f"ST Resistance TL  ({tl['touch_count']} touches)",
                       price_lo, price_hi)

    # 9. Current price
    ax.axhline(current_price, color="#ffeb3b", linewidth=0.9,
               linestyle=":", alpha=0.8, label=f"Price  {current_price:.2f}")

    # 10. Axis
    price_pad = price_range * 0.04
    ax.set_xlim(-1, n + 7)
    ax.set_ylim(price_lo - price_pad, price_hi + price_pad)
    format_x_axis(ax, df)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))

    # 11. Legend
    zone_patches = []
    if vis_sup_zones:
        zone_patches.append(mpatches.Patch(color="#00e676", alpha=0.45,
            label=f"Support zone  (x{len(vis_sup_zones)})"))
    if st_sup_zones_fallback:
        zone_patches.append(mpatches.Patch(color="#b9f6ca", alpha=0.45,
            label=f"ST Support zone [3m]  (x{len(st_sup_zones_fallback)})"))
    if nearest_sup_zone:
        dist_pct = (nearest_sup_zone["center_price"] - current_price) / current_price * 100
        zone_patches.append(mpatches.Patch(color="#69f0ae", alpha=0.45,
            label=f"Nearest support  ({dist_pct:.1f}%)"))
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
    ax.set_xlabel("Date", color="#b2b5be")
    ax.set_ylabel("Price (USD)", color="#b2b5be")

    out_file = f"reports/{ticker}_technical_{period}.png"
    plt.tight_layout()
    plt.savefig(out_file, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"  Chart saved -> {out_file}")


if __name__ == "__main__":
    main()
