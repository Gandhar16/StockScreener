"""
visualize_technical.py
======================
Downloads OHLC data for a ticker, runs MarketStructureEngine, then draws a
clean candlestick chart with filtered trendlines and S/R zones.

Filters applied (keeps chart readable):
  1. Proximity  – only show lines / zones within ±15 % of current price
  2. Min touches – trendlines need >= 3 pivot touches; zones need >= 2 pivots
  3. One best per role – 1 LT support TL, 1 LT resistance TL,
                         1 ST support TL, 1 ST resistance TL,
                         top-3 support zones, top-3 resistance zones

Usage:
    python visualize_technical.py [TICKER] [PERIOD]
    python visualize_technical.py AAPL 1y
    python visualize_technical.py NVDA 2y
"""

import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")          # headless – saves to PNG
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import yfinance as yf

from stock_scanner.engine.technical import MarketStructureEngine


# ── helpers ──────────────────────────────────────────────────────────────────

def draw_candlesticks(ax, df: pd.DataFrame) -> None:
    """Draw OHLC candlesticks on *ax*."""
    bull_color = "#26a69a"   # teal  – close >= open
    bear_color = "#ef5350"   # red   – close <  open

    xs = np.arange(len(df))
    for i, (_, row) in enumerate(df.iterrows()):
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        color = bull_color if c >= o else bear_color
        # Wick
        ax.plot([xs[i], xs[i]], [l, h], color=color, linewidth=0.8, zorder=2)
        # Body
        body_lo, body_hi = min(o, c), max(o, c)
        body_h = max(body_hi - body_lo, 0.001 * c)  # min 0.1 % height so Doji is visible
        rect = mpatches.Rectangle(
            (xs[i] - 0.4, body_lo), 0.8, body_h,
            facecolor=color, edgecolor=color, linewidth=0.4, zorder=3
        )
        ax.add_patch(rect)


def format_x_axis(ax, df: pd.DataFrame, max_ticks: int = 10) -> None:
    """Replace integer x-ticks with date strings."""
    n = len(df)
    tick_positions = np.linspace(0, n - 1, min(max_ticks, n), dtype=int)
    tick_labels = [df.index[i].strftime("%Y-%m-%d") for i in tick_positions]
    ax.set_xticks(tick_positions)
    ax.set_xticklabels(tick_labels, rotation=35, ha="right", fontsize=7)


def draw_horizontal_zone(ax, zone: dict, color: str, n: int) -> None:
    """Draw a horizontal S/R zone as a shaded band."""
    lo, hi = zone["price_range"]
    if lo == hi:
        hi = lo * 1.001   # give single-price zones a tiny visible band
    ax.axhspan(lo, hi, xmin=0, xmax=1, alpha=0.18, color=color, zorder=1)
    # Label: center price
    ax.axhline(zone["center_price"], color=color, linewidth=0.7,
               linestyle="--", alpha=0.55, zorder=1)


def draw_trendline(ax, tl: dict, df_len: int, color: str,
                   linestyle: str = "-", label: str = "",
                   y_lo: float = 0.0, y_hi: float = 1e9) -> None:
    """Draw a diagonal trendline from its first touch to the end of the chart.

    Clipped to [y_lo, y_hi] so steep lines don't shoot off-screen.  If the
    line exits the visible range before reaching the end of the chart it is
    drawn only up to that exit point.
    """
    m = tl["slope"]
    b = tl["intercept"]
    x0 = tl["start_index"]

    # Walk bar-by-bar and stop once the line leaves the visible price range
    x1 = x0
    for xi in range(x0, df_len):
        yi = m * xi + b
        if y_lo * 0.92 <= yi <= y_hi * 1.08:   # 8 % margin so nearly-off lines still show
            x1 = xi
        else:
            break

    y0 = m * x0 + b
    y1 = m * x1 + b

    ax.plot([x0, x1], [y0, y1],
            color=color, linewidth=1.5, linestyle=linestyle,
            alpha=0.85, zorder=4,
            label=label if label else None)


# ── filtering helpers ────────────────────────────────────────────────────────

PROXIMITY_PCT   = 0.15   # filter 1: keep items within ±15 % of current price
MIN_TL_TOUCHES  = 3      # filter 2: trendlines need at least this many touches
MIN_ZONE_PIVOTS = 2      # filter 2: zones need at least this many pivot points


def filter_zones(zones: list, current_price: float, max_keep: int) -> list:
    """Apply proximity + touch filters and keep top-N by strength score."""
    lo, hi = current_price * (1 - PROXIMITY_PCT), current_price * (1 + PROXIMITY_PCT)
    kept = [
        z for z in zones
        if lo <= z["center_price"] <= hi          # filter 1: proximity
        and z["touch_count"] >= MIN_ZONE_PIVOTS   # filter 2: min touches
    ]
    kept.sort(key=lambda z: z["strength_score"], reverse=True)
    return kept[:max_keep]


def filter_trendlines(trendlines: list, current_price: float) -> list:
    """Apply proximity + touch filters, return best single line (or empty)."""
    lo, hi = current_price * (1 - PROXIMITY_PCT), current_price * (1 + PROXIMITY_PCT)
    kept = [
        tl for tl in trendlines
        if lo <= tl["current_value"] <= hi         # filter 1: proximity
        and tl["touch_count"] >= MIN_TL_TOUCHES    # filter 2: min touches
    ]
    kept.sort(key=lambda tl: tl["strength_score"], reverse=True)
    return kept[:1]   # filter 3: single best per role


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    period = sys.argv[2] if len(sys.argv) > 2 else "1y"

    print(f"  Downloading {ticker}  ({period}) …")
    raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)

    if raw.empty:
        print("No data returned – check the ticker symbol.")
        return

    # yfinance may return MultiIndex columns; flatten them
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
    print(f"  {len(df)} bars  |  price range  {df['Low'].min():.2f} – {df['High'].max():.2f}")

    # ── Run market-structure engine ───────────────────────────────────────
    print("  Running MarketStructureEngine …")
    engine = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
    result = engine.analyze_structure(df)

    context           = result["context"]
    support_zones     = result["support_zones"]
    resistance_zones  = result["resistance_zones"]
    lt_sup_tl         = result["long_term_support_trendlines"]
    lt_res_tl         = result["long_term_resistance_trendlines"]
    st_sup_tl         = result["short_term_support_trendlines"]
    st_res_tl         = result["short_term_resistance_trendlines"]

    current_price = float(df["Close"].iloc[-1])

    # ── Apply filters ─────────────────────────────────────────────────────
    # Filter 1 (proximity) + Filter 2 (min touches) + Filter 3 (single best)
    vis_sup_zones = filter_zones(support_zones,    current_price, max_keep=3)
    vis_res_zones = filter_zones(resistance_zones, current_price, max_keep=3)
    vis_lt_sup    = filter_trendlines(lt_sup_tl,  current_price)   # 0 or 1 line
    vis_lt_res    = filter_trendlines(lt_res_tl,  current_price)
    vis_st_sup    = filter_trendlines(st_sup_tl,  current_price)
    vis_st_res    = filter_trendlines(st_res_tl,  current_price)

    print(f"  Context : {context}")
    print(f"  Raw  -> support zones: {len(support_zones)}  resistance zones: {len(resistance_zones)}")
    print(f"          LT sup TL: {len(lt_sup_tl)}  LT res TL: {len(lt_res_tl)}")
    print(f"          ST sup TL: {len(st_sup_tl)}  ST res TL: {len(st_res_tl)}")
    print(f"  After filters:")
    print(f"    Support zones shown    : {len(vis_sup_zones)}")
    print(f"    Resistance zones shown : {len(vis_res_zones)}")
    print(f"    LT support TL shown    : {len(vis_lt_sup)}")
    print(f"    LT resistance TL shown : {len(vis_lt_res)}")
    print(f"    ST support TL shown    : {len(vis_st_sup)}")
    print(f"    ST resistance TL shown : {len(vis_st_res)}")

    # ── Plot ─────────────────────────────────────────────────────────────
    n = len(df)
    price_lo = float(df["Low"].min())
    price_hi = float(df["High"].max())

    fig, ax = plt.subplots(figsize=(18, 9))
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

    # 2. Support zones (top-3, filtered)
    for zone in vis_sup_zones:
        draw_horizontal_zone(ax, zone, "#00e676", n)

    # 3. Resistance zones (top-3, filtered)
    for zone in vis_res_zones:
        draw_horizontal_zone(ax, zone, "#ff5252", n)

    # 4. Best LT trendlines (solid, 1 per side)
    for tl in vis_lt_sup:
        draw_trendline(ax, tl, n, "#00e676", linestyle="-",
                       label=f"LT Support TL  (touches: {tl['touch_count']})",
                       y_lo=price_lo, y_hi=price_hi)

    for tl in vis_lt_res:
        draw_trendline(ax, tl, n, "#ff5252", linestyle="-",
                       label=f"LT Resistance TL  (touches: {tl['touch_count']})",
                       y_lo=price_lo, y_hi=price_hi)

    # 5. Best ST trendlines (dashed, 1 per side)
    for tl in vis_st_sup:
        draw_trendline(ax, tl, n, "#69f0ae", linestyle="--",
                       label=f"ST Support TL  (touches: {tl['touch_count']})",
                       y_lo=price_lo, y_hi=price_hi)

    for tl in vis_st_res:
        draw_trendline(ax, tl, n, "#ff8a80", linestyle="--",
                       label=f"ST Resistance TL  (touches: {tl['touch_count']})",
                       y_lo=price_lo, y_hi=price_hi)

    # 6. Current price marker
    ax.axhline(current_price, color="#ffeb3b", linewidth=0.9,
               linestyle=":", alpha=0.8, label=f"Price  {current_price:.2f}")

    # 7. Axis formatting
    ax.set_xlim(-1, n)
    price_pad = (price_hi - price_lo) * 0.04
    ax.set_ylim(price_lo - price_pad, price_hi + price_pad)
    format_x_axis(ax, df)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))

    # 8. Legend + title  (zone patches added manually since axhspan has no label)
    sup_patch = mpatches.Patch(color="#00e676", alpha=0.45,
                               label=f"Support zone  (x{len(vis_sup_zones)})")
    res_patch = mpatches.Patch(color="#ff5252", alpha=0.45,
                               label=f"Resistance zone  (x{len(vis_res_zones)})")
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + [sup_patch, res_patch],
              labels=labels + [sup_patch.get_label(), res_patch.get_label()],
              loc="upper left", facecolor="#1e222d", edgecolor="#2a2e39",
              labelcolor="#b2b5be", fontsize=8, framealpha=0.9)

    ax.set_title(
        f"{ticker}  –  Market Structure  |  {context}  |  {period}",
        color="#d1d4dc", fontsize=11, pad=10
    )
    ax.set_xlabel("Date", color="#b2b5be")
    ax.set_ylabel("Price (USD)", color="#b2b5be")

    out_file = f"reports/{ticker}_technical_{period}.png"
    plt.tight_layout()
    plt.savefig(out_file, dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close()
    print(f"\n  Chart saved -> {out_file}")


if __name__ == "__main__":
    main()
