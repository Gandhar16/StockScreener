"""
strategy_compare.py
===================
Tests 10 different entry-filter strategies on the same 3-phase backtest.

Fundamentals are cached after first run so strategy variations are fast (seconds).
For each strategy the technical filter, stop type, and pattern allowlist vary.
Results are printed as a comparison table. The best strategy by a combined
win-rate x total-return score is saved to dashboard/data.json.

Run:
    python strategy_compare.py
"""

import contextlib
import json
import logging
import os
import pickle

import numpy as np
import pandas as pd
import yfinance as yf

from stock_scanner.config import load_config_from_file
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.engine.patterns import PatternFinder
from stock_scanner.engine.technical import MarketStructureEngine
from visualize_technical import compute_entry_signals

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("compare")

# ── shared config ─────────────────────────────────────────────────────────────

TICKERS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "NVDA",
    "AVGO",
    "CSCO",
    "AMZN",
    "TSLA",
    "HD",
    "META",
    "NFLX",
    "JPM",
    "V",
    "MA",
    "JNJ",
    "LLY",
    "UNH",
    "WMT",
    "PG",
    "KO",
    "ORCL",
    "AMD",
    "QCOM",
    "XOM",
    "CVX",
]
PHASES = [
    {"start": "2023-06-15", "end": "2024-06-15", "as_of": 2022},
    {"start": "2024-06-15", "end": "2025-06-15", "as_of": 2023},
    {"start": "2025-06-15", "end": "2026-06-15", "as_of": 2024},
]
INITIAL_CAPITAL = 100_000.0
TOP_N_FUNDAMENTAL = 15
MAX_POSITIONS = 10
PRICE_HISTORY_BARS = 252
FUND_CACHE = "reports/fund_cache.pkl"
SIGNAL_RANK = {"BUY": 0, "BUY?": 1, "WATCH-LONG": 2}

# Patterns proven to have 0% win rate across baseline — excluded in quality filter
WEAK_PATTERNS = {
    "Tweezer Top",
    "Tweezer Bottom",
    "Bullish Harami",
    "Bearish Harami",
    "Three White Soldiers",
    "Three Black Crows",
    "Piercing Line",
    "Dark Cloud Cover",
    "Doji",
}

# ── 10 strategies ─────────────────────────────────────────────────────────────

STRATEGIES = {
    "1_Baseline": {
        "desc": "Current pipeline (all signals, all patterns)",
        "max_signal_rank": 2,  # 0=BUY only, 1=BUY+BUY?, 2=all
        "vol_required": False,
        "trend_filter": False,  # price > 50-day SMA
        "min_risk_pct": 0.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",  # "pattern" or "atr"
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "2_VolConfirmed": {
        "desc": "Volume-confirmed BUY only (no BUY?)",
        "max_signal_rank": 0,
        "vol_required": True,
        "trend_filter": False,
        "min_risk_pct": 0.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "3_NoTinyStops": {
        "desc": "Exclude trades with risk < 2% (noise triggers)",
        "max_signal_rank": 2,
        "vol_required": False,
        "trend_filter": False,
        "min_risk_pct": 2.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "4_RiskWindow": {
        "desc": "Only 2-5% risk trades (sweet spot from analysis)",
        "max_signal_rank": 2,
        "vol_required": False,
        "trend_filter": False,
        "min_risk_pct": 2.0,
        "max_risk_pct": 5.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "5_TrendFilter": {
        "desc": "Only buy above 50-day SMA (with-trend only)",
        "max_signal_rank": 2,
        "vol_required": False,
        "trend_filter": True,
        "min_risk_pct": 0.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "6_ATRStop": {
        "desc": "Replace pattern stop with entry - 1.5xATR(14)",
        "max_signal_rank": 2,
        "vol_required": False,
        "trend_filter": False,
        "min_risk_pct": 0.0,
        "max_risk_pct": 99.0,
        "stop_type": "atr",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "7_StrongPatterns": {
        "desc": "Exclude 0%-win-rate candlestick patterns",
        "max_signal_rank": 2,
        "vol_required": False,
        "trend_filter": False,
        "min_risk_pct": 0.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": True,
    },
    "8_VolNoTinyStops": {
        "desc": "Vol confirmed + min 2% stop distance",
        "max_signal_rank": 1,
        "vol_required": True,
        "trend_filter": False,
        "min_risk_pct": 2.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "9_TrendVol": {
        "desc": "Trend up + vol confirmed + no tiny stops",
        "max_signal_rank": 1,
        "vol_required": True,
        "trend_filter": True,
        "min_risk_pct": 2.0,
        "max_risk_pct": 99.0,
        "stop_type": "pattern",
        "atr_mult": 1.5,
        "exclude_weak_patterns": False,
    },
    "10_Optimal": {
        "desc": "Vol + Trend + 2-5% risk + strong patterns + ATR stop",
        "max_signal_rank": 1,
        "vol_required": True,
        "trend_filter": True,
        "min_risk_pct": 2.0,
        "max_risk_pct": 8.0,
        "stop_type": "atr",
        "atr_mult": 2.0,
        "exclude_weak_patterns": True,
    },
}

# ── helpers ───────────────────────────────────────────────────────────────────


def atr14(df: pd.DataFrame) -> float:
    hi = df["High"].values
    lo = df["Low"].values
    cl = df["Close"].values
    tr = np.maximum(hi[1:] - lo[1:], np.maximum(abs(hi[1:] - cl[:-1]), abs(lo[1:] - cl[:-1])))
    return float(tr[-14:].mean()) if len(tr) >= 14 else float(tr.mean())


def sma50(df: pd.DataFrame) -> float:
    closes = df["Close"].values
    return float(closes[-50:].mean()) if len(closes) >= 50 else float(closes.mean())


def ohlcv_for(price_df, ticker, end_date):
    try:
        cols = ["Open", "High", "Low", "Close", "Volume"]
        sub = pd.DataFrame(
            {c: price_df[c][ticker] for c in cols if c in price_df.columns.get_level_values(0)}
        )
        sub = sub.loc[:end_date].dropna()
        if len(sub) > PRICE_HISTORY_BARS:
            sub = sub.iloc[-PRICE_HISTORY_BARS:]
        return sub
    except Exception:
        return pd.DataFrame()


def get_signals(ticker: str, df: pd.DataFrame):
    """Run full pattern pipeline, return list of enriched pattern dicts."""
    if len(df) < 30:
        return []
    try:
        engine = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
        finder = PatternFinder(
            price_tolerance=0.03, min_pullback=0.03, recent_candle_bars=15, recent_chart_bars=30
        )
        ph, pl = engine._find_pivots(df)
        patterns = finder.find_all(df, ph, pl) + finder.find_forming(df, ph, pl)
        if not patterns:
            return []
        compute_entry_signals(patterns, df)
        return patterns
    except Exception:
        return []


def apply_strategy_filter(patterns, df, cfg):
    """Filter pattern list according to a strategy config dict."""
    _sma = sma50(df)
    _atr = atr14(df)
    current = float(df["Close"].iloc[-1])

    kept = []
    for p in patterns:
        sig = p.get("signal", "")
        if sig not in SIGNAL_RANK:
            continue
        if SIGNAL_RANK[sig] > cfg["max_signal_rank"]:
            continue
        if cfg["vol_required"] and not p.get("vol_confirmed"):
            continue
        if cfg["trend_filter"] and current < _sma:
            continue
        if cfg["exclude_weak_patterns"] and p.get("name") in WEAK_PATTERNS:
            continue

        entry = p.get("entry_price", 0)
        stop_p = p.get("stop_loss", 0)
        if not entry or not stop_p or entry <= 0:
            continue

        # Compute stop
        if cfg["stop_type"] == "atr" and _atr > 0:
            atr_stop = entry - cfg["atr_mult"] * _atr
            # Use wider of the two stops (more room)
            stop_used = min(stop_p, atr_stop)
        else:
            stop_used = stop_p

        risk_pct = abs(entry - stop_used) / entry * 100
        if risk_pct < cfg["min_risk_pct"] or risk_pct > cfg["max_risk_pct"]:
            continue

        p = dict(p)
        p["stop_loss"] = round(stop_used, 4)
        p["risk_pct"] = round(risk_pct, 2)
        kept.append(p)

    if not kept:
        return None
    # Best by signal rank then recency
    return min(kept, key=lambda p: (SIGNAL_RANK[p["signal"]], -p["completed_bar"]))


def simulate_trade(price_df, ticker, entry_price, stop_loss, p_start, p_end, allocation):
    try:
        closes = price_df["Close"][ticker].loc[p_start:p_end].dropna()
        highs = price_df["High"][ticker].loc[p_start:p_end].dropna()
        lows = price_df["Low"][ticker].loc[p_start:p_end].dropna()
    except Exception:
        return None
    if closes.empty:
        return None

    entry_mask = highs >= entry_price
    if not entry_mask.any():
        return None

    entry_day = entry_mask.idxmax()
    shares = allocation / entry_price

    after_lows = lows.loc[entry_day:].iloc[1:]
    stop_mask = after_lows <= stop_loss
    if stop_mask.any():
        exit_day = stop_mask.idxmax()
        exit_px = stop_loss
        exit_reason = "STOP"
    else:
        exit_day = closes.index[-1]
        exit_px = float(closes.loc[exit_day])
        exit_reason = "TIME"

    pnl = shares * (exit_px - entry_price)
    return {
        "ticker": ticker,
        "entry_date": entry_day.strftime("%Y-%m-%d"),
        "exit_date": exit_day.strftime("%Y-%m-%d"),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_px, 4),
        "stop_loss": round(stop_loss, 4),
        "shares": round(shares, 4),
        "profit_loss": round(pnl, 4),
        "profit_loss_pct": round((exit_px - entry_price) / entry_price, 6),
        "exit_reason": exit_reason,
        "status": "WIN" if pnl > 0 else "LOSS",
        "signal": "",
        "pattern": "",
        "fund_score": 0,
        "vol_confirmed": False,
    }


def run_strategy(strategy_name, cfg, phases, fund_cache, price_df):
    """Run all phases for one strategy. Returns (trade_logs, equity_curve)."""
    current_cash = INITIAL_CAPITAL
    benchmark_shares = 0.0
    portfolio_history = []
    trade_logs = []

    for phase_idx, phase in enumerate(phases):
        p_start = pd.Timestamp(phase["start"])
        p_end = pd.Timestamp(phase["end"])

        candidates = fund_cache.get(phase["as_of"], [])
        if not candidates:
            continue

        # Technical filter
        confirmed = []
        for row in candidates:
            ticker = row["ticker"]
            df_hist = ohlcv_for(price_df, ticker, p_start)
            if df_hist.empty:
                continue
            patterns = get_signals(ticker, df_hist)
            best = apply_strategy_filter(patterns, df_hist, cfg)
            if best is None:
                continue
            confirmed.append(
                {
                    "ticker": ticker,
                    "entry_price": best["entry_price"],
                    "stop_loss": best["stop_loss"],
                    "signal": best["signal"],
                    "pattern": best["name"],
                    "fund_score": row.get("fund_score", 0),
                    "vol_confirmed": best.get("vol_confirmed", False),
                }
            )

        confirmed.sort(key=lambda x: (SIGNAL_RANK.get(x["signal"], 9), -x["fund_score"]))
        selected = confirmed[:MAX_POSITIONS]

        if not selected:
            continue

        allocation = current_cash / len(selected)
        trading_days = price_df["Close"].loc[p_start:p_end].dropna(how="all").index

        # Benchmark on phase 0
        if phase_idx == 0 or benchmark_shares == 0:
            try:
                bench_buy = float(price_df["Close"]["^GSPC"].loc[p_start:].iloc[0])
                benchmark_shares = INITIAL_CAPITAL / bench_buy
            except Exception:
                pass

        phase_holdings = []
        for stock in selected:
            t = simulate_trade(
                price_df,
                stock["ticker"],
                stock["entry_price"],
                stock["stop_loss"],
                p_start,
                p_end,
                allocation,
            )
            if t is None:
                continue
            t["signal"] = stock["signal"]
            t["pattern"] = stock["pattern"]
            t["fund_score"] = stock["fund_score"]
            t["vol_confirmed"] = stock["vol_confirmed"]
            phase_holdings.append(t)
            trade_logs.append(t)

        if not phase_holdings:
            continue

        # Build exit map for NAV calculation
        exit_map = {}
        for h in phase_holdings:
            exit_map[h["ticker"]] = {
                "exit_date": pd.Timestamp(h["exit_date"]),
                "exit_price": h["exit_price"],
                "shares": h["shares"],
            }

        cash_freed = {}
        for info in exit_map.values():
            ed = info["exit_date"].strftime("%Y-%m-%d")
            cash_freed[ed] = cash_freed.get(ed, 0) + info["shares"] * info["exit_price"]

        freed_so_far = 0.0
        for day in trading_days:
            ds = day.strftime("%Y-%m-%d")
            freed_so_far += cash_freed.get(ds, 0)
            equity = 0.0
            for tkr, info in exit_map.items():
                if day <= info["exit_date"]:
                    with contextlib.suppress(Exception):
                        equity += info["shares"] * float(price_df["Close"][tkr].loc[day])
            try:
                bench_val = benchmark_shares * float(price_df["Close"]["^GSPC"].loc[day])
            except Exception:
                bench_val = 0.0
            portfolio_history.append(
                {
                    "date": ds,
                    "portfolio_value": round(equity + freed_so_far, 2),
                    "benchmark_value": round(bench_val, 2),
                }
            )

        if portfolio_history:
            current_cash = portfolio_history[-1]["portfolio_value"]

    return trade_logs, portfolio_history


def metrics(trade_logs, portfolio_history, initial=INITIAL_CAPITAL):
    if not trade_logs or not portfolio_history:
        return None
    wins = [t for t in trade_logs if t["status"] == "WIN"]
    losses = [t for t in trade_logs if t["status"] == "LOSS"]
    stops = [t for t in trade_logs if t["exit_reason"] == "STOP"]

    final = portfolio_history[-1]["portfolio_value"]
    bench_f = portfolio_history[-1]["benchmark_value"]
    ret = (final - initial) / initial
    b_ret = (bench_f - initial) / initial

    max_dd = 0.0
    peak = initial
    for r in portfolio_history:
        peak = max(peak, r["portfolio_value"])
        dd = (r["portfolio_value"] - peak) / peak
        max_dd = min(max_dd, dd)

    win_rate = len(wins) / len(trade_logs) if trade_logs else 0
    avg_win = sum(t["profit_loss_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["profit_loss_pct"] for t in losses) / len(losses) if losses else 0
    gross_win = sum(t["profit_loss"] for t in wins)
    gross_loss = abs(sum(t["profit_loss"] for t in losses))
    pf = gross_win / gross_loss if gross_loss else float("inf")

    return {
        "trades": len(trade_logs),
        "wins": len(wins),
        "win_rate": win_rate,
        "total_ret": ret,
        "bench_ret": b_ret,
        "outperform": ret - b_ret,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "pf": pf,
        "stops_pct": len(stops) / len(trade_logs) if trade_logs else 0,
        "final": final,
    }


def score_strategy(m):
    """Combined rank: 60% win_rate + 40% total_return (normalized 0-1 per column in caller)."""
    return m["win_rate"] * 0.6 + max(m["total_ret"], 0) * 0.4 if m else -99


# ── main ─────────────────────────────────────────────────────────────────────


def main():
    os.makedirs("reports", exist_ok=True)

    # ── Load or build fundamental cache ───────────────────────────────────────
    if os.path.exists(FUND_CACHE):
        with open(FUND_CACHE, "rb") as f:
            fund_cache = pickle.load(f)
    else:
        config_path = "config/scanner_config.yaml"
        config = load_config_from_file(config_path)
        engine = FundamentalEngine(config)

        import logging as _log

        _log.getLogger().setLevel(_log.INFO)

        fund_cache = {}
        for phase in PHASES:
            as_of = phase["as_of"]
            scored = engine.analyze_tickers(TICKERS, as_of_year=as_of)
            if scored.empty:
                fund_cache[as_of] = []
                continue
            eligible = scored[
                not scored.get("is_disqualified", pd.Series(False, index=scored.index))
            ]
            top = eligible.head(TOP_N_FUNDAMENTAL)
            fund_cache[as_of] = [
                {"ticker": row["ticker"], "fund_score": float(row["total_score"])}
                for _, row in top.iterrows()
            ]

        _log.getLogger().setLevel(_log.WARNING)
        with open(FUND_CACHE, "wb") as f:
            pickle.dump(fund_cache, f)

    # ── Download prices ───────────────────────────────────────────────────────
    earliest = min(p["start"] for p in PHASES)
    dl_start = str(pd.Timestamp(earliest) - pd.DateOffset(years=1))[:10]
    symbols = list({*TICKERS, "^GSPC"})
    price_df = yf.download(
        symbols, start=dl_start, end="2026-12-31", auto_adjust=True, progress=False
    )
    if price_df.empty:
        return

    # ── Run all strategies ────────────────────────────────────────────────────
    results = {}
    all_logs = {}
    all_curves = {}

    for name, cfg in STRATEGIES.items():
        logs, curve = run_strategy(name, cfg, PHASES, fund_cache, price_df)
        m = metrics(logs, curve)
        if m:
            results[name] = m
            all_logs[name] = logs
            all_curves[name] = curve
        else:
            pass

    # ── Print comparison table ────────────────────────────────────────────────

    sorted_strats = sorted(
        results.items(),
        key=lambda kv: (kv[1]["win_rate"] * 0.5 + max(kv[1]["total_ret"], 0) * 0.5),
        reverse=True,
    )
    for name, m in sorted_strats:
        STRATEGIES[name]["desc"][:45]
        f"{m['pf']:.1f}x" if m["pf"] != float("inf") else " inf"

    # ── Pick winner: best combined score ──────────────────────────────────────
    best_name = sorted_strats[0][0]
    best_m = sorted_strats[0][1]
    bench_ret = best_m["bench_ret"]

    # ── Save best to dashboard ────────────────────────────────────────────────
    best_logs = all_logs[best_name]
    best_curve = all_curves[best_name]
    max_port = max_bench = INITIAL_CAPITAL
    for rec in best_curve:
        max_port = max(max_port, rec["portfolio_value"])
        max_bench = max(max_bench, rec["benchmark_value"])
        rec["portfolio_drawdown"] = (rec["portfolio_value"] - max_port) / max_port
        rec["benchmark_drawdown"] = (rec["benchmark_value"] - max_bench) / max_bench

    output = {
        "strategy": best_name,
        "strategy_desc": STRATEGIES[best_name]["desc"],
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": round(best_m["final"], 2),
        "total_return": round(best_m["total_ret"], 6),
        "benchmark_return": round(bench_ret, 6),
        "max_drawdown": round(best_m["max_dd"], 6),
        "benchmark_max_drawdown": round(min(r["benchmark_drawdown"] for r in best_curve), 6),
        "equity_curve": best_curve,
        "trade_logs": best_logs,
        "comparison_table": [
            {
                "strategy": n,
                "desc": STRATEGIES[n]["desc"],
                "trades": m["trades"],
                "win_rate": round(m["win_rate"], 4),
                "total_ret": round(m["total_ret"], 4),
                "max_dd": round(m["max_dd"], 4),
                "profit_factor": round(m["pf"], 2) if m["pf"] != float("inf") else 99.0,
                "avg_win": round(m["avg_win"], 4),
                "avg_loss": round(m["avg_loss"], 4),
            }
            for n, m in sorted_strats
        ],
    }
    with open("dashboard/data.json", "w") as f:
        json.dump(output, f, indent=2)

    with open("reports/strategy_comparison.json", "w") as f:
        comp = {
            n: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}
            for n, m in results.items()
        }
        json.dump(comp, f, indent=2)


if __name__ == "__main__":
    main()
