"""
run_pipeline.py
===============
Full 3-stage pipeline:

  Stage 1 — Fundamental screen
      FundamentalEngine scores all candidate tickers using point-in-time
      statements (no lookahead bias).  Top-N by total_score advance.

  Stage 2 — Technical confirmation
      PatternFinder runs on historical OHLCV up to the screen date.
      Only stocks with a bullish signal (BUY, BUY?, WATCH-LONG) confirmed
      by a chart/candlestick pattern proceed to the trade.

  Stage 3 — Trade simulation + backtest
      Long entry: first day after screen date where High >= entry_price.
      Stop-loss exit: first day where Low <= stop_loss (exits at stop price).
      Time exit: if stop never hit, sell at close on phase end date.
      Daily portfolio NAV tracked against S&P 500 benchmark.

Output: dashboard/data.json  (read by dashboard/index.html)
        reports/pipeline_summary.json  (detailed per-phase breakdown)

Usage:
    python run_pipeline.py
"""

import json
import logging
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from typing import Any

import pandas as pd
import yfinance as yf

from stock_scanner.config import load_config_from_file
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.engine.indicators import compute_indicators
from stock_scanner.engine.mtf import analyze_mtf
from stock_scanner.engine.patterns import PatternFinder
from stock_scanner.engine.relative_strength import mansfield_rs, rs_gate
from stock_scanner.engine.technical import MarketStructureEngine
from stock_scanner.engine.trade_quality import choose_stop, position_size, risk_reward, setup_score

# ── re-use the entry signal logic from visualize_technical ───────────────────
from visualize_technical import compute_entry_signals

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"
)
logger = logging.getLogger("pipeline")

# ── configuration ─────────────────────────────────────────────────────────────

TICKERS = [
    # Mega-cap tech
    "AAPL",
    "MSFT",
    "GOOGL",
    "NVDA",
    "AVGO",
    "META",
    "AMZN",
    "ORCL",
    "ADBE",
    "CRM",
    "NOW",
    "MU",
    # Semiconductors / hardware
    "AMD",
    "QCOM",
    "INTC",
    "TXN",
    # Consumer tech / platforms
    "TSLA",
    "NFLX",
    "UBER",
    "PLTR",
    # Financials
    "JPM",
    "V",
    "MA",
    "BAC",
    "GS",
    "MS",
    "WFC",
    "BLK",
    "AXP",
    # Healthcare
    "JNJ",
    "LLY",
    "UNH",
    "PFE",
    "MRK",
    "ABBV",
    # Consumer staples / discretionary
    "WMT",
    "PG",
    "KO",
    "HD",
    "MCD",
    "SBUX",
    "NKE",
    "COST",
    "TGT",
    # Energy
    "XOM",
    "CVX",
    # Industrials
    "BA",
    "CAT",
    "GE",
    # Networking
    "CSCO",
]

PHASES = [
    {"start": "2023-06-15", "end": "2024-06-15", "as_of": 2022},
    {"start": "2024-06-15", "end": "2025-06-15", "as_of": 2023},
    {"start": "2025-06-15", "end": "2026-06-15", "as_of": 2024},
]

INITIAL_CAPITAL = 100_000.0
TOP_N_FUNDAMENTAL = 15  # how many pass fundamental filter
MAX_POSITIONS = 10  # max concurrent holdings
PRICE_HISTORY_BARS = 504  # bars of OHLCV (~2 yr — weekly MTF needs 30wk SMA + RS needs 252d)
RISK_PER_TRADE = 0.01  # fraction of capital risked per trade (stop-based sizing)
MAX_POSITION_PCT = 0.15  # notional cap per position

# Signal priority: lower = better
SIGNAL_RANK = {"BUY": 0, "BUY?": 1, "WATCH-LONG": 2}


# ── helpers ───────────────────────────────────────────────────────────────────


def download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Download adjusted close + OHLCV for all symbols in one call."""
    symbols = list({*tickers, "^GSPC"})
    logger.info(f"Downloading prices for {len(symbols)} symbols ({start} to {end}) ...")
    raw = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        return raw
    return raw


def ohlcv_for(price_df: pd.DataFrame, ticker: str, end_date: pd.Timestamp) -> pd.DataFrame:
    """
    Return a clean OHLCV DataFrame for ticker up to end_date,
    using the last PRICE_HISTORY_BARS bars.
    """
    try:
        cols = ["Open", "High", "Low", "Close", "Volume"]
        sub = pd.DataFrame(
            {c: price_df[c][ticker] for c in cols if c in price_df.columns.get_level_values(0)}
        )
        sub = sub.loc[:end_date].dropna()
        if len(sub) > PRICE_HISTORY_BARS:
            sub = sub.iloc[-PRICE_HISTORY_BARS:]
        return sub
    except Exception as e:
        logger.debug(f"ohlcv_for({ticker}): {e}")
        return pd.DataFrame()


def get_technical_signal(
    ticker: str, df: pd.DataFrame, bench_close: pd.Series | None = None
) -> dict[str, Any] | None:
    """
    Run the full pattern + signal pipeline on a historical OHLCV slice,
    then apply the trader-grade gates:
      - weekly multi-timeframe alignment (daily setup must not fight the
        weekly trend)
      - relative strength vs benchmark (no severe laggards)
      - ATR-vs-pattern stop selection
    Returns the best bullish signal dict (with `reject_reason` set and the
    dict returned as None if a gate fails), or None if no bullish setup exists.
    """
    if len(df) < 30:
        return None
    try:
        indic = compute_indicators(df)

        engine = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
        finder = PatternFinder(
            price_tolerance=0.03, min_pullback=0.03, recent_candle_bars=15, recent_chart_bars=30
        )
        p_highs, p_lows = engine._find_pivots(df)
        patterns = finder.find_all(df, p_highs, p_lows)
        patterns += finder.find_forming(df, p_highs, p_lows)
        if not patterns:
            return None
        compute_entry_signals(patterns, df, indicators=indic)

        # keep only bullish signals with a valid entry price
        bullish = [
            p
            for p in patterns
            if p.get("signal") in SIGNAL_RANK
            and p.get("entry_price")
            and p.get("stop_loss")
            and p["entry_price"] > 0
            and p["stop_loss"] > 0
        ]
        if not bullish:
            return None

        # pick best by signal rank, then pattern quality, then recency
        best = min(
            bullish,
            key=lambda p: (
                SIGNAL_RANK[p["signal"]],
                -(p.get("pattern_score") or 0),
                -p["completed_bar"],
            ),
        )

        # ── Gate 1: weekly trend must not be against the setup ──────────────
        mtf = analyze_mtf(df, "bullish")
        best["mtf_score"] = mtf.get("mtf_score")
        best["mtf_aligned"] = mtf.get("mtf_aligned")
        if mtf.get("mtf_aligned") is False:
            logger.info(
                f"  {ticker}: rejected — weekly trend against setup "
                f"(MTF {mtf.get('mtf_score')}/100)"
            )
            return None

        # ── Gate 2: relative strength (skip severe laggards) ────────────────
        rs = (
            mansfield_rs(df["Close"], bench_close)
            if bench_close is not None
            else {"rs_mansfield": None, "rs_trend": None}
        )
        gate = rs_gate("bullish", rs)
        best["rs_mansfield"] = rs.get("rs_mansfield")
        best["rs_trend"] = rs.get("rs_trend")
        if gate.get("rs_pass") is False and (rs.get("rs_mansfield") or 0) <= -20:
            logger.info(f"  {ticker}: rejected — {gate.get('rs_reason')}")
            return None

        # ── Stop upgrade: tighter of pattern vs 2×ATR, noise-guarded ────────
        stop_res = choose_stop(best["entry_price"], best["stop_loss"], indic.get("atr"), "bullish")
        if stop_res["stop"] is not None:
            best["pattern_stop"] = best["stop_loss"]
            best["stop_loss"] = stop_res["stop"]
            best["stop_source"] = stop_res["stop_source"]

        # Composite setup score for ranking
        rr = risk_reward(
            best["entry_price"],
            best["stop_loss"],
            best.get("t1") or best.get("swing_target"),
            "bullish",
        )
        ss = setup_score(best.get("pattern_score"), mtf, rs, indic, rr, best)
        best["setup_score"] = ss["setup_score"]
        best["setup_grade"] = ss["setup_grade"]
        return best
    except Exception as e:
        logger.warning(f"Technical analysis failed for {ticker}: {e}")
        return None


def simulate_trade(
    price_df: pd.DataFrame,
    ticker: str,
    entry_price: float,
    stop_loss: float,
    phase_start: pd.Timestamp,
    phase_end: pd.Timestamp,
    allocation: float,
) -> dict[str, Any] | None:
    """
    Simulate a long trade:
      - Enter on the first trading day where High >= entry_price.
      - Exit on the first day after entry where Low <= stop_loss (at stop price).
      - Otherwise exit at close on phase_end.
    Returns a trade dict or None if the entry trigger was never reached.
    """
    try:
        closes = price_df["Close"][ticker].loc[phase_start:phase_end].dropna()
        highs = price_df["High"][ticker].loc[phase_start:phase_end].dropna()
        lows = price_df["Low"][ticker].loc[phase_start:phase_end].dropna()
    except Exception:
        return None

    if closes.empty:
        return None

    # Find entry day: first day High >= entry_price
    entry_mask = highs >= entry_price
    if not entry_mask.any():
        # Price never reached entry trigger in this phase — skip
        return None

    entry_day = entry_mask.idxmax()
    entry_px = float(entry_price)
    shares = allocation / entry_px

    # Find stop day: first day after entry where Low <= stop_loss
    after_entry_lows = lows.loc[entry_day:].iloc[1:]  # skip entry bar
    stop_mask = after_entry_lows <= stop_loss
    if stop_mask.any():
        stop_day = stop_mask.idxmax()
        exit_px = float(stop_loss)
        exit_day = stop_day
        exit_reason = "STOP"
    else:
        # Hold to end of phase
        exit_day = closes.index[-1]
        exit_px = float(closes.loc[exit_day])
        exit_reason = "TIME"

    final_val = shares * exit_px
    profit_loss = final_val - allocation
    pct_return = (exit_px - entry_px) / entry_px

    return {
        "ticker": ticker,
        "entry_date": entry_day.strftime("%Y-%m-%d") + " 09:30:00",
        "exit_date": exit_day.strftime("%Y-%m-%d") + " 16:00:00",
        "entry_price": round(entry_px, 4),
        "exit_price": round(exit_px, 4),
        "stop_loss": round(stop_loss, 4),
        "shares": round(shares, 4),
        "profit_loss": round(profit_loss, 4),
        "profit_loss_pct": round(pct_return, 6),
        "exit_reason": exit_reason,
        "status": "WIN" if profit_loss > 0 else "LOSS",
    }


def daily_portfolio_values(
    holdings: list[dict], price_df: pd.DataFrame, trading_days: pd.DatetimeIndex
) -> dict[str, float]:
    """
    Returns {date_str: portfolio_value} for each trading day.
    Holdings may exit mid-phase (stop or time); after exit the cash sits idle.
    """
    # Build per-ticker exit info keyed by date
    exit_map: dict[str, dict[str, Any]] = {}
    for h in holdings:
        exit_map[h["ticker"]] = {
            "exit_date": pd.Timestamp(h["exit_date"][:10]),
            "exit_price": h["exit_price"],
            "shares": h["shares"],
        }

    day_values: dict[str, float] = {}
    cash_freed: dict[str, float] = {}  # cash returned after stop / time exit

    # Pre-build cash freed per exit date
    for ticker, info in exit_map.items():
        ed = info["exit_date"].strftime("%Y-%m-%d")
        val = info["shares"] * info["exit_price"]
        cash_freed[ed] = cash_freed.get(ed, 0.0) + val

    total_cash = 0.0
    for day in trading_days:
        ds = day.strftime("%Y-%m-%d")
        # Add any cash freed today
        total_cash += cash_freed.get(ds, 0.0)
        # Mark value of still-open positions
        equity = 0.0
        for ticker, info in exit_map.items():
            if day <= info["exit_date"]:
                try:
                    px = float(price_df["Close"][ticker].loc[day])
                    equity += info["shares"] * px
                except Exception:
                    pass
        day_values[ds] = equity + total_cash

    return day_values


# ── main pipeline ─────────────────────────────────────────────────────────────


def run_pipeline():
    # 1. Load fundamental engine
    config_path = "config/scanner_config.yaml"
    if not os.path.exists(config_path):
        logger.error(f"Config not found: {config_path}")
        return
    config = load_config_from_file(config_path)
    fund_engine = FundamentalEngine(config)

    # 2. Download all price history in one call
    earliest_start = min(p["start"] for p in PHASES)
    # go back an extra year so we have history for technical analysis on start date
    dl_start = str(pd.Timestamp(earliest_start) - pd.DateOffset(years=1))[:10]
    dl_end = "2026-12-31"
    price_df = download_prices(TICKERS, dl_start, dl_end)
    if price_df.empty:
        logger.error("Price download failed.")
        return

    # 3. Phase loop
    portfolio_history: list[dict] = []
    trade_logs: list[dict] = []
    phase_summaries: list[dict] = []

    initial_capital = INITIAL_CAPITAL
    current_cash = initial_capital
    benchmark_shares = 0.0

    for phase_idx, phase in enumerate(PHASES):
        p_start = pd.Timestamp(phase["start"])
        p_end = pd.Timestamp(phase["end"])
        as_of = phase["as_of"]

        logger.info("=" * 60)
        logger.info(f"Phase {phase_idx+1}: {phase['start']} -> {phase['end']}  (as_of={as_of})")
        logger.info("=" * 60)

        # ── Stage 1: Fundamental screen ─────────────────────────────────────
        logger.info("Stage 1: Fundamental screen ...")
        scored_df = fund_engine.analyze_tickers(TICKERS, as_of_year=as_of)
        if scored_df.empty:
            logger.warning("No fundamental scores — skipping phase.")
            continue

        eligible = scored_df[
            not scored_df.get("is_disqualified", pd.Series(False, index=scored_df.index))
        ]
        top_candidates = eligible.head(TOP_N_FUNDAMENTAL)["ticker"].tolist()
        logger.info(f"  Fundamental top-{TOP_N_FUNDAMENTAL}: {top_candidates}")

        # ── Stage 2: Technical confirmation ─────────────────────────────────
        logger.info("Stage 2: Technical filter ...")
        try:
            bench_hist = price_df["Close"]["^GSPC"].loc[:p_start].dropna()
        except Exception:
            bench_hist = None
        confirmed: list[dict[str, Any]] = []
        for ticker in top_candidates:
            df_hist = ohlcv_for(price_df, ticker, p_start)
            if df_hist.empty:
                logger.debug(f"  {ticker}: no OHLCV history")
                continue
            sig = get_technical_signal(ticker, df_hist, bench_close=bench_hist)
            if sig is None:
                logger.info(f"  {ticker}: no qualifying bullish setup — skipped")
                continue
            fund_row = eligible[eligible["ticker"] == ticker].iloc[0]
            confirmed.append(
                {
                    "ticker": ticker,
                    "entry_price": sig["entry_price"],
                    "stop_loss": sig["stop_loss"],
                    "signal": sig["signal"],
                    "pattern": sig["name"],
                    "risk_pct": sig.get("risk_pct", 0.0),
                    "vol_confirmed": sig.get("vol_confirmed", False),
                    "fund_score": round(float(fund_row["total_score"]), 1),
                    "setup_score": sig.get("setup_score"),
                    "setup_grade": sig.get("setup_grade"),
                    "mtf_score": sig.get("mtf_score"),
                    "rs_mansfield": sig.get("rs_mansfield"),
                    "stop_source": sig.get("stop_source"),
                }
            )
            logger.info(
                f"  {ticker}: {sig['signal']:12s}  pattern={sig['name']:<24s}"
                f"  entry={sig['entry_price']:.2f}  stop={sig['stop_loss']:.2f}"
                f"  risk={sig.get('risk_pct', 0):.1f}%"
            )

        if not confirmed:
            logger.warning("No technically confirmed stocks for this phase.")
            continue

        # Sort by setup quality (composite), then signal rank, then fund score
        confirmed.sort(
            key=lambda x: (
                -(x.get("setup_score") or 0),
                SIGNAL_RANK.get(x["signal"], 9),
                -x["fund_score"],
            )
        )
        selected = confirmed[:MAX_POSITIONS]
        logger.info(f"  Selected {len(selected)} positions for phase.")

        # ── Stage 3: Simulate trades ─────────────────────────────────────────
        logger.info("Stage 3: Simulating trades ...")
        equal_allocation = current_cash / len(selected)
        phase_holdings: list[dict] = []

        trading_days = price_df["Close"].loc[p_start:p_end].dropna(how="all").index

        for stock in selected:
            # Fixed-fractional sizing: risk RISK_PER_TRADE of capital per
            # trade based on stop distance, notional-capped; residual stays
            # cash. Falls back to equal weight if sizing degenerates.
            ps = position_size(
                current_cash,
                RISK_PER_TRADE,
                stock["entry_price"],
                stock["stop_loss"],
                max_position_pct=MAX_POSITION_PCT,
            )
            allocation = ps["position_value"] or min(
                equal_allocation, current_cash * MAX_POSITION_PCT
            )
            if allocation <= 0:
                logger.info(f"  {stock['ticker']}: position sized to zero — skipped")
                continue
            trade = simulate_trade(
                price_df=price_df,
                ticker=stock["ticker"],
                entry_price=stock["entry_price"],
                stop_loss=stock["stop_loss"],
                phase_start=p_start,
                phase_end=p_end,
                allocation=allocation,
            )
            if trade is None:
                logger.info(f"  {stock['ticker']}: entry trigger never reached — idle cash")
                continue

            trade["signal"] = stock["signal"]
            trade["pattern"] = stock["pattern"]
            trade["fund_score"] = stock["fund_score"]
            trade["vol_confirmed"] = stock["vol_confirmed"]
            trade["setup_score"] = stock.get("setup_score")
            trade["setup_grade"] = stock.get("setup_grade")
            trade["mtf_score"] = stock.get("mtf_score")
            trade["rs_mansfield"] = stock.get("rs_mansfield")
            trade["stop_source"] = stock.get("stop_source")
            trade["capital_at_risk"] = ps.get("capital_at_risk")
            phase_holdings.append(trade)
            trade_logs.append(trade)

            logger.info(
                f"  {stock['ticker']}: {trade['exit_reason']:4s}  "
                f"{trade['entry_price']:.2f} -> {trade['exit_price']:.2f}  "
                f"P&L={trade['profit_loss']:+.0f}  ({trade['profit_loss_pct']:+.1%})"
            )

        if not phase_holdings:
            logger.warning("No trades executed in this phase.")
            continue

        # ── Daily NAV ────────────────────────────────────────────────────────
        # Benchmark: buy S&P 500 on first trading day of phase
        if phase_idx == 0 or benchmark_shares == 0.0:
            try:
                bench_buy_px = float(price_df["Close"]["^GSPC"].loc[p_start:].iloc[0])
                benchmark_shares = initial_capital / bench_buy_px
            except Exception:
                benchmark_shares = 0.0

        day_nav = daily_portfolio_values(phase_holdings, price_df, trading_days)

        # Risk-based sizing leaves part of the capital uninvested — that idle
        # cash is still part of the portfolio and must be carried in the NAV.
        invested = sum(h["shares"] * h["entry_price"] for h in phase_holdings)
        idle_cash = max(0.0, current_cash - invested)

        for day in trading_days:
            ds = day.strftime("%Y-%m-%d")
            port_val = day_nav.get(ds, 0.0) + idle_cash
            try:
                bench_val = benchmark_shares * float(price_df["Close"]["^GSPC"].loc[day])
            except Exception:
                bench_val = 0.0

            portfolio_history.append(
                {
                    "date": ds,
                    "portfolio_value": round(port_val, 2),
                    "benchmark_value": round(bench_val, 2),
                }
            )

        # Update cash to end-of-phase portfolio value
        last_nav = portfolio_history[-1]["portfolio_value"] if portfolio_history else current_cash
        current_cash = last_nav

        phase_summaries.append(
            {
                "phase": f"{phase['start']} to {phase['end']}",
                "candidates": top_candidates,
                "confirmed": [c["ticker"] for c in confirmed],
                "traded": [h["ticker"] for h in phase_holdings],
                "wins": sum(1 for h in phase_holdings if h["status"] == "WIN"),
                "losses": sum(1 for h in phase_holdings if h["status"] == "LOSS"),
                "stops_hit": sum(1 for h in phase_holdings if h["exit_reason"] == "STOP"),
            }
        )

    if not portfolio_history:
        logger.error("No portfolio history generated — nothing to save.")
        return

    # ── 4. Drawdowns ─────────────────────────────────────────────────────────
    max_port = initial_capital
    max_bench = initial_capital
    for rec in portfolio_history:
        max_port = max(max_port, rec["portfolio_value"])
        max_bench = max(max_bench, rec["benchmark_value"])
        rec["portfolio_drawdown"] = (
            (rec["portfolio_value"] - max_port) / max_port if max_port else 0.0
        )
        rec["benchmark_drawdown"] = (
            (rec["benchmark_value"] - max_bench) / max_bench if max_bench else 0.0
        )

    # ── 5. Build output ───────────────────────────────────────────────────────
    final_port = portfolio_history[-1]["portfolio_value"]
    final_bench = portfolio_history[-1]["benchmark_value"]

    output = {
        "initial_capital": initial_capital,
        "final_capital": round(final_port, 2),
        "total_return": round((final_port - initial_capital) / initial_capital, 6),
        "benchmark_return": round((final_bench - initial_capital) / initial_capital, 6),
        "max_drawdown": round(min(r["portfolio_drawdown"] for r in portfolio_history), 6),
        "benchmark_max_drawdown": round(min(r["benchmark_drawdown"] for r in portfolio_history), 6),
        "equity_curve": portfolio_history,
        "trade_logs": trade_logs,
        "phase_summaries": phase_summaries,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    os.makedirs("dashboard", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    with open("dashboard/data.json", "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Saved -> dashboard/data.json")

    with open("reports/pipeline_summary.json", "w") as f:
        json.dump(
            {
                "phases": phase_summaries,
                "trades": len(trade_logs),
                "final_capital": round(final_port, 2),
            },
            f,
            indent=2,
        )
    logger.info("Saved -> reports/pipeline_summary.json")

    # ── Console summary ───────────────────────────────────────────────────────
    (final_bench - initial_capital) / initial_capital
    sum(1 for t in trade_logs if t["status"] == "WIN")
    sum(1 for t in trade_logs if t["exit_reason"] == "STOP")


# ── Long-term backtest ────────────────────────────────────────────────────────
# Strategy: buy on fundamentals (score ≥ 60), NO stop-loss.
# Quarterly rescreen — exit only if thesis breaks (score < 50 or D/E > 3).
# Output: dashboard/lt_data.json

LT_SCORE_ENTRY = 60.0
LT_SCORE_EXIT = 50.0
LT_DE_EXIT = 3.0
LT_POSITION_PCT = 0.08  # 8% of capital per position
LT_MAX_POSITIONS = 12


def _lt_daily_nav(
    holdings: list[dict], price_df: pd.DataFrame, trading_days: pd.DatetimeIndex
) -> dict[str, float]:
    """Daily NAV for long-term holdings (exits keyed by date, idle cash after)."""
    exit_map = {}
    for h in holdings:
        exit_map[h["ticker"]] = {
            "exit_date": pd.Timestamp(h["exit_date"]),
            "exit_price": h["exit_price"],
            "shares": h["shares"],
        }

    cash_freed: dict[str, float] = {}
    for info in exit_map.values():
        ed = info["exit_date"].strftime("%Y-%m-%d")
        cash_freed[ed] = cash_freed.get(ed, 0.0) + info["shares"] * info["exit_price"]

    total_cash = 0.0
    day_values: dict[str, float] = {}
    for day in trading_days:
        ds = day.strftime("%Y-%m-%d")
        total_cash += cash_freed.get(ds, 0.0)
        equity = 0.0
        for ticker, info in exit_map.items():
            if day <= info["exit_date"]:
                try:
                    px = float(price_df["Close"][ticker].loc[day])
                    equity += info["shares"] * px
                except Exception:
                    pass
        day_values[ds] = equity + total_cash
    return day_values


def run_lt_backtest():
    """
    Long-term fundamental backtest — no stop-losses.

    Entry  : fundamental score >= 60 at phase start (no technical gate).
    Sizing : 8% of capital per position, up to 12 positions.
    Exit   : quarterly rescreen (every ~90 days).
             If score < 50 → FUND_DETERIORATION exit.
             If D/E  > 3.0 → DE_SPIKE exit.
             Otherwise hold to phase end → PHASE_END exit.
    """
    config_path = "config/scanner_config.yaml"
    if not os.path.exists(config_path):
        logger.error(f"Config not found: {config_path}")
        return

    config = load_config_from_file(config_path)
    fund_engine = FundamentalEngine(config)

    # Pre-load fundamental scores for all needed years so we don't re-fetch.
    needed_years = sorted({p["as_of"] for p in PHASES} | {p["as_of"] + 1 for p in PHASES})
    logger.info(f"LT backtest: pre-loading fundamental data for years {needed_years} ...")
    scored_cache: dict[int, pd.DataFrame] = {}
    for year in needed_years:
        try:
            df = fund_engine.analyze_tickers(TICKERS, as_of_year=year)
            scored_cache[year] = df
            logger.info(f"  Loaded {len(df)} tickers for {year}")
        except Exception as e:
            logger.warning(f"  Could not load year {year}: {e}")
            scored_cache[year] = pd.DataFrame()

    # Download price history
    earliest_start = min(p["start"] for p in PHASES)
    dl_start = str(pd.Timestamp(earliest_start) - pd.DateOffset(years=1))[:10]
    dl_end = "2026-12-31"
    price_df = download_prices(TICKERS, dl_start, dl_end)
    if price_df.empty:
        logger.error("Price download failed.")
        return

    portfolio_history: list[dict] = []
    trade_logs: list[dict] = []
    phase_summaries: list[dict] = []

    initial_capital = INITIAL_CAPITAL
    current_capital = initial_capital
    benchmark_shares = 0.0

    for phase_idx, phase in enumerate(PHASES):
        p_start = pd.Timestamp(phase["start"])
        p_end = pd.Timestamp(phase["end"])
        as_of = phase["as_of"]

        logger.info("=" * 60)
        logger.info(f"LT Phase {phase_idx+1}: {phase['start']} → {phase['end']}  (as_of={as_of})")

        # ── Initial screen ────────────────────────────────────────────────────
        init_df = scored_cache.get(as_of, pd.DataFrame())
        if init_df.empty:
            logger.warning("  No fundamental data — skipping phase.")
            continue

        is_disq = init_df.get("is_disqualified", pd.Series(False, index=init_df.index))
        eligible = init_df[not is_disq].copy()
        eligible["total_score"] = pd.to_numeric(eligible["total_score"], errors="coerce").fillna(0)
        qualified = (
            eligible[eligible["total_score"] >= LT_SCORE_ENTRY]
            .sort_values("total_score", ascending=False)
            .head(LT_MAX_POSITIONS)
        )

        if qualified.empty:
            logger.warning("  No tickers passed LT_SCORE_ENTRY — skipping phase.")
            continue

        tickers_selected = qualified["ticker"].tolist()
        logger.info(f"  Qualified: {tickers_selected}")

        # ── Enter positions at first close after phase start ──────────────────
        alloc_per = current_capital * LT_POSITION_PCT
        holdings: dict[str, dict] = {}

        for ticker in tickers_selected:
            try:
                series = price_df["Close"][ticker].loc[p_start:].dropna()
                if series.empty:
                    continue
                entry_px = float(series.iloc[0])
                entry_day = series.index[0]
                row = qualified[qualified["ticker"] == ticker].iloc[0]
                holdings[ticker] = {
                    "shares": alloc_per / entry_px,
                    "entry_px": entry_px,
                    "entry_day": entry_day,
                    "alloc": alloc_per,
                    "fund_score": round(float(row["total_score"]), 1),
                }
            except Exception as e:
                logger.debug(f"  {ticker}: entry failed — {e}")

        if not holdings:
            logger.warning("  No positions entered.")
            continue

        # ── Quarterly rescreens: 90, 180, 270 days into phase ────────────────
        early_exits: dict[str, tuple] = {}  # ticker → (exit_day, exit_px, reason)

        for q_offset in (90, 180, 270):
            q_date = p_start + pd.DateOffset(days=q_offset)
            if q_date >= p_end:
                break

            # Use next year's data once we're 6+ months in (more realistic)
            q_as_of = (as_of + 1) if q_offset >= 180 else as_of
            q_df = scored_cache.get(q_as_of, scored_cache.get(as_of, pd.DataFrame()))
            if q_df.empty:
                continue

            active = [t for t in holdings if t not in early_exits]
            for ticker in active:
                q_row = q_df[q_df["ticker"] == ticker]
                if q_row.empty:
                    continue

                new_score = float(pd.to_numeric(q_row.iloc[0]["total_score"], errors="coerce") or 0)
                de_raw = q_row.iloc[0].get("debt_to_equity")
                try:
                    de_ratio = float(de_raw) if de_raw is not None else 0.0
                except (ValueError, TypeError):
                    de_ratio = 0.0

                reason = None
                if new_score < LT_SCORE_EXIT:
                    reason = "FUND_DETERIORATION"
                elif de_ratio > LT_DE_EXIT:
                    reason = "DE_SPIKE"

                if reason:
                    try:
                        ex_series = price_df["Close"][ticker].loc[q_date:].dropna()
                        if ex_series.empty:
                            continue
                        exit_px = float(ex_series.iloc[0])
                        exit_day = ex_series.index[0]
                        early_exits[ticker] = (exit_day, exit_px, reason)
                        logger.info(
                            f"  {ticker}: {reason} @ {exit_day.date()}  "
                            f"score={new_score:.1f}  D/E={de_ratio:.1f}"
                        )
                    except Exception:
                        pass

        # ── Build trade log for this phase ────────────────────────────────────
        phase_trades: list[dict] = []

        for ticker, h in holdings.items():
            if ticker in early_exits:
                exit_day, exit_px, exit_reason = early_exits[ticker]
            else:
                try:
                    end_series = price_df["Close"][ticker].loc[:p_end].dropna()
                    if end_series.empty:
                        continue
                    exit_day = end_series.index[-1]
                    exit_px = float(end_series.iloc[-1])
                    exit_reason = "PHASE_END"
                except Exception:
                    continue

            pnl = h["shares"] * exit_px - h["alloc"]
            pct = (exit_px - h["entry_px"]) / h["entry_px"]

            trade = {
                "ticker": ticker,
                "entry_date": h["entry_day"].strftime("%Y-%m-%d") + " 09:30:00",
                "exit_date": exit_day.strftime("%Y-%m-%d") + " 16:00:00",
                "entry_price": round(h["entry_px"], 4),
                "exit_price": round(exit_px, 4),
                "stop_loss": None,
                "shares": round(h["shares"], 4),
                "profit_loss": round(pnl, 4),
                "profit_loss_pct": round(pct, 6),
                "exit_reason": exit_reason,
                "status": "WIN" if pnl > 0 else "LOSS",
                "signal": "BUY",
                "pattern": "Fundamental Quality",
                "fund_score": h["fund_score"],
                "vol_confirmed": False,
            }
            phase_trades.append(trade)
            trade_logs.append(trade)
            logger.info(
                f"  {ticker}: {exit_reason:20s}  "
                f"{h['entry_px']:.2f} → {exit_px:.2f}  P&L={pnl:+.0f}  ({pct:+.1%})"
            )

        if not phase_trades:
            logger.warning("  No completed trades.")
            continue

        # ── Daily NAV ─────────────────────────────────────────────────────────
        if phase_idx == 0 or benchmark_shares == 0.0:
            try:
                bench_px0 = float(price_df["Close"]["^GSPC"].loc[p_start:].iloc[0])
                benchmark_shares = initial_capital / bench_px0
            except Exception:
                benchmark_shares = 0.0

        trading_days = price_df["Close"].loc[p_start:p_end].dropna(how="all").index
        day_nav = _lt_daily_nav(phase_trades, price_df, trading_days)

        for day in trading_days:
            ds = day.strftime("%Y-%m-%d")
            port_val = day_nav.get(ds, 0.0)
            try:
                bench_val = benchmark_shares * float(price_df["Close"]["^GSPC"].loc[day])
            except Exception:
                bench_val = 0.0
            portfolio_history.append(
                {
                    "date": ds,
                    "portfolio_value": round(port_val, 2),
                    "benchmark_value": round(bench_val, 2),
                }
            )

        last_nav = (
            portfolio_history[-1]["portfolio_value"] if portfolio_history else current_capital
        )
        current_capital = last_nav

        wins = sum(1 for t in phase_trades if t["status"] == "WIN")
        early = sum(1 for t in phase_trades if t["exit_reason"] != "PHASE_END")
        phase_summaries.append(
            {
                "phase": f"{phase['start']} to {phase['end']}",
                "entered": list(holdings.keys()),
                "traded": [t["ticker"] for t in phase_trades],
                "wins": wins,
                "losses": len(phase_trades) - wins,
                "early_exits": early,
            }
        )

    if not portfolio_history:
        logger.error("LT backtest: no portfolio history generated.")
        return

    # ── Drawdowns ─────────────────────────────────────────────────────────────
    max_port = max_bench = initial_capital
    for rec in portfolio_history:
        max_port = max(max_port, rec["portfolio_value"])
        max_bench = max(max_bench, rec["benchmark_value"])
        rec["portfolio_drawdown"] = (
            (rec["portfolio_value"] - max_port) / max_port if max_port else 0.0
        )
        rec["benchmark_drawdown"] = (
            (rec["benchmark_value"] - max_bench) / max_bench if max_bench else 0.0
        )

    final_port = portfolio_history[-1]["portfolio_value"]
    final_bench = portfolio_history[-1]["benchmark_value"]

    output = {
        "strategy": "Long-Term Fundamental (No Stop-Loss)",
        "initial_capital": initial_capital,
        "final_capital": round(final_port, 2),
        "total_return": round((final_port - initial_capital) / initial_capital, 6),
        "benchmark_return": round((final_bench - initial_capital) / initial_capital, 6),
        "max_drawdown": round(min(r["portfolio_drawdown"] for r in portfolio_history), 6),
        "benchmark_max_drawdown": round(min(r["benchmark_drawdown"] for r in portfolio_history), 6),
        "equity_curve": portfolio_history,
        "trade_logs": trade_logs,
        "phase_summaries": phase_summaries,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    os.makedirs("dashboard", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    with open("dashboard/lt_data.json", "w") as f:
        json.dump(output, f, indent=2)
    with open("reports/lt_pipeline_summary.json", "w") as f:
        json.dump(
            {
                "phases": phase_summaries,
                "trades": len(trade_logs),
                "final_capital": round(final_port, 2),
            },
            f,
            indent=2,
        )

    wins = sum(1 for t in trade_logs if t["status"] == "WIN")
    early = sum(1 for t in trade_logs if t["exit_reason"] != "PHASE_END")
    (final_bench - initial_capital) / initial_capital


def run() -> dict:
    """Importable entry point — returns summary dict for pipeline.py."""
    run_pipeline()
    try:
        with open("reports/pipeline_summary.json") as f:
            return json.load(f)
    except Exception:
        return {}


def run_lt() -> dict:
    """Importable LT backtest entry point for pipeline.py."""
    run_lt_backtest()
    try:
        with open("reports/lt_pipeline_summary.json") as f:
            return json.load(f)
    except Exception:
        return {}


if __name__ == "__main__":
    import sys

    if "--lt" in sys.argv:
        run_lt_backtest()
    else:
        run_pipeline()
