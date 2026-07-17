"""
relative_strength.py
====================
Relative strength vs a market benchmark — the classic "trade leaders, not
laggards" filter.

- Mansfield RS: RS line (stock/benchmark) normalized by its own 252-bar
  moving average, so it is comparable across tickers and can gate inline.
- IBD-style RS percentile (1-99): computed as a post-pass over a scan
  universe, per benchmark group (US names ranked vs US, NSE vs NSE).

Missing benchmark data always degrades to pass-through (None), never a fail.
"""


import numpy as np
import pandas as pd

# Suffix → benchmark index. Anything unmatched falls back to ^GSPC.
DEFAULT_BENCHMARK_MAP = {
    ".NS": "^NSEI",   # NSE India → NIFTY 50
    ".BO": "^BSESN",  # BSE India → SENSEX
}
DEFAULT_BENCHMARK = "^GSPC"  # S&P 500

_benchmark_cache: dict[str, pd.Series] = {}


def benchmark_for(ticker: str, benchmark_map: dict[str, str] | None = None) -> str:
    """Map a ticker to its benchmark index symbol by suffix."""
    bmap = benchmark_map or DEFAULT_BENCHMARK_MAP
    for suffix, bench in bmap.items():
        if ticker.upper().endswith(suffix.upper()):
            return bench
    return DEFAULT_BENCHMARK


def fetch_benchmark_history(symbol: str, period: str = "2y") -> pd.Series | None:
    """
    Download (and cache for the process lifetime) a benchmark's close series.
    Returns None on any failure — callers treat that as pass-through.
    """
    key = f"{symbol}:{period}"
    if key in _benchmark_cache:
        return _benchmark_cache[key]
    try:
        import yfinance as yf
        df = yf.download(symbol, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):  # yfinance MultiIndex quirk
            close = close.iloc[:, 0]
        close = close.dropna()
        if close.empty:
            return None
        _benchmark_cache[key] = close
        return close
    except Exception:
        return None


def clear_benchmark_cache() -> None:
    _benchmark_cache.clear()


def mansfield_rs(close: pd.Series, bench_close: pd.Series | None,
                 period: int = 252) -> dict:
    """
    Mansfield Relative Strength at the latest bar.

    rs_line     = close / benchmark (inner-joined dates — handles NSE/US
                  holiday calendar mismatches)
    rs_mansfield = (rs_line / SMA(rs_line, period) - 1) * 100
                  > 0: outperforming its own trailing year vs the market

    Also reports the 20-day RS-line slope (normalized), whether the RS line
    just printed a new high over the period window, and a coarse rs_trend.
    Returns all-None dict when benchmark data is missing/insufficient.
    """
    empty = {"rs_mansfield": None, "rs_line_slope_20d": None,
             "rs_new_high": None, "rs_trend": None}
    if bench_close is None or len(bench_close) == 0:
        return empty

    joined = pd.concat(
        [close.rename("stock"), bench_close.rename("bench")], axis=1, join="inner"
    ).dropna()
    if len(joined) < 60:
        return empty

    rs_line = joined["stock"] / joined["bench"]
    window = min(period, len(rs_line))
    rs_ma = rs_line.rolling(window, min_periods=window // 2).mean()
    ma_last = rs_ma.iloc[-1]
    if pd.isna(ma_last) or ma_last == 0:
        return empty

    rs_m = (float(rs_line.iloc[-1]) / float(ma_last) - 1.0) * 100.0

    slope = None
    seg = rs_line.iloc[-20:]
    if len(seg) == 20:
        x = np.arange(20, dtype=float)
        raw = np.polyfit(x, seg.values.astype(float), 1)[0]
        slope = raw * 20 / (float(seg.mean()) or 1.0)  # ≈ pct change over 20 bars

    rs_new_high = bool(rs_line.iloc[-1] >= rs_line.iloc[-window:].max() * 0.999)

    if slope is None:
        rs_trend = None
    elif slope > 0.01:
        rs_trend = "improving"
    elif slope < -0.01:
        rs_trend = "deteriorating"
    else:
        rs_trend = "flat"

    return {
        "rs_mansfield": round(rs_m, 2),
        "rs_line_slope_20d": round(slope, 4) if slope is not None else None,
        "rs_new_high": rs_new_high,
        "rs_trend": rs_trend,
    }


def rs_gate(direction: str, rs: dict,
            soft_floor: float = -5.0, hard_floor: float = -20.0) -> dict:
    """
    Gate a setup on relative strength.

    Bull setups: pass when rs_mansfield > soft_floor OR the RS trend is
    improving; hard fail below hard_floor. Bear setups mirrored.
    Missing RS data → pass-through (rs_pass=None).
    """
    rs_m = rs.get("rs_mansfield")
    trend = rs.get("rs_trend")
    if rs_m is None:
        return {"rs_pass": None, "rs_reason": "no benchmark data"}

    if direction == "bullish":
        if rs_m <= hard_floor:
            return {"rs_pass": False,
                    "rs_reason": f"severe laggard (Mansfield RS {rs_m:+.1f})"}
        if rs_m > soft_floor or trend == "improving":
            return {"rs_pass": True,
                    "rs_reason": f"RS acceptable (Mansfield {rs_m:+.1f}, {trend})"}
        return {"rs_pass": False,
                "rs_reason": f"lagging market (Mansfield {rs_m:+.1f}, {trend})"}
    else:  # bearish setups want weak RS
        if rs_m >= -hard_floor:
            return {"rs_pass": False,
                    "rs_reason": f"too strong to short (Mansfield RS {rs_m:+.1f})"}
        if rs_m < -soft_floor or trend == "deteriorating":
            return {"rs_pass": True,
                    "rs_reason": f"weak RS confirms short (Mansfield {rs_m:+.1f})"}
        return {"rs_pass": False,
                "rs_reason": f"RS not weak enough (Mansfield {rs_m:+.1f})"}


def rs_percentile(rs_values: dict[str, float | None],
                  benchmark_groups: dict[str, str] | None = None) -> dict[str, int | None]:
    """
    IBD-style RS rating 1-99 across a scanned universe.

    rs_values:        {ticker: rs_mansfield or None}
    benchmark_groups: {ticker: benchmark symbol} — percentiles are computed
                      within each benchmark group so NSE names are ranked
                      against NSE names. Omit to rank everything together.
    """
    groups: dict[str, list] = {}
    for t, v in rs_values.items():
        if v is None:
            continue
        g = (benchmark_groups or {}).get(t, "ALL")
        groups.setdefault(g, []).append((t, v))

    out: dict[str, int | None] = dict.fromkeys(rs_values)
    for _, members in groups.items():
        if len(members) < 2:
            for t, _v in members:
                out[t] = None
            continue
        vals = np.array([v for _, v in members], dtype=float)
        for t, v in members:
            pct = (vals < v).sum() / len(vals)  # strict rank fraction
            out[t] = round(1 + pct * 98)
    return out
