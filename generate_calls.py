"""
generate_calls.py
=================
Generates actionable equity calls for:

  LONG-TERM  — Stocks to buy/accumulate for months to years.
               Driven by fundamental quality score + fair value estimate.
               Shows analyst consensus target, Graham number, and key thesis.

  SWING      — Stocks with a confirmed technical setup for a trade lasting
               days to weeks.  Driven by pattern detection: entry, stop,
               and target from the nearest resistance zone (R:R >= 1.5).

Usage:
    python generate_calls.py
    python generate_calls.py --tickers AAPL,MSFT,RELIANCE.NS,INFY.NS
    python generate_calls.py --period 6mo

Output:
    Console call sheet  (formatted for easy reading)
    reports/equity_calls.json  (read by the dashboard)
"""

import argparse
import json
import logging
import math
import os
import pickle
import sys

# Force UTF-8 output on Windows so currency symbols don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from stock_scanner.config import load_config_from_file
from stock_scanner.engine.calls_db import export_portfolio_json, upsert_call
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.engine.indicators import compute_indicators
from stock_scanner.engine.patterns import PatternFinder
from stock_scanner.engine.sentiment import SentimentEngine
from stock_scanner.engine.technical import MarketStructureEngine
from stock_scanner.engine.trade_quality import enrich_trade_signal
from visualize_technical import (
    annotate_at_levels,
    compute_entry_signals,
    find_fib_pivots,
    find_fib_pivots_bearish,
    save_chart,
    select_trendlines,
    select_zones,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("calls")

# ── ticker universe ────────────────────────────────────────────────────────────

DEFAULT_US = [
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
DEFAULT_INDIA = [
    "RELIANCE.NS",
    "INFY.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "WIPRO.NS",
    "LT.NS",
    "BAJFINANCE.NS",
    "AXISBANK.NS",
    "SBIN.NS",
]

LIVE_FUND_CACHE = "reports/live_fund_cache.pkl"
CACHE_MAX_AGE_H = 24  # refresh fundamental cache after 24 hours
MIN_FUND_SCORE = 60.0  # minimum total_score to appear in long-term calls
MIN_RR = 1.5  # minimum risk:reward for swing calls
SWING_BARS = 252  # price history for technical analysis

# Patterns with historically poor win rates — excluded from swing calls
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


# ── fair value helpers ────────────────────────────────────────────────────────


def graham_number(eps: float, bvps: float) -> float | None:
    """Graham Number = sqrt(22.5 × EPS × BVPS).  Conservative intrinsic value."""
    if eps and bvps and eps > 0 and bvps > 0:
        return math.sqrt(22.5 * eps * bvps)
    return None


def get_yf_fundamentals(ticker: str) -> dict[str, Any]:
    """Fetch key live metrics from yfinance .info dict."""
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        info = {}
    return {
        "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "analyst_target": info.get("targetMeanPrice"),
        "analyst_low": info.get("targetLowPrice"),
        "analyst_high": info.get("targetHighPrice"),
        "forward_pe": info.get("forwardPE"),
        "trailing_pe": info.get("trailingPE"),
        "peg": info.get("pegRatio"),
        "pb": info.get("priceToBook"),
        "eps_ttm": info.get("trailingEps"),
        "eps_forward": info.get("forwardEps"),
        "bvps": info.get("bookValue"),
        "dividend_yield": info.get("dividendYield"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "market_cap": info.get("marketCap"),
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency", "USD"),
    }


def fair_value_estimate(yf_data: dict, fund_row: dict | None = None) -> dict[str, Any]:
    """
    Returns a dict with fair_value, method, and upside_pct.
    Priority: analyst_target → Graham number → forward P/E based.
    """
    price = yf_data.get("current_price") or 0
    analyst = yf_data.get("analyst_target")
    gn = graham_number(yf_data.get("eps_ttm"), yf_data.get("bvps"))
    fwd_pe = yf_data.get("forward_pe")
    fwd_eps = yf_data.get("eps_forward")

    candidates = []
    if analyst and analyst > 0:
        candidates.append(("Analyst consensus", analyst))
    if gn and gn > 0:
        candidates.append(("Graham Number", gn))
    if fwd_pe and fwd_eps and fwd_pe < 50:
        # Use 20× forward EPS as a reasonable "fair" multiple
        fwd_val = fwd_eps * 20
        if fwd_val > 0:
            candidates.append(("20x Fwd EPS", fwd_val))

    if not candidates or price <= 0:
        return {"fair_value": None, "method": None, "upside_pct": None}

    # Use the median to avoid outlier estimates pulling the number
    values = [v for _, v in candidates]
    fair = float(np.median(values))
    method = " / ".join(m for m, _ in candidates)
    upside = (fair - price) / price

    return {"fair_value": round(fair, 2), "method": method, "upside_pct": round(upside, 4)}


# ── fibonacci targets ─────────────────────────────────────────────────────────


def compute_fib_targets(
    df: pd.DataFrame, p_highs: list, p_lows: list, entry: float, stop: float
) -> dict[str, Any]:
    """
    Find the recent swing_low / swing_high from pivot data and compute:
      T1 = 100% measured move (return to swing_high / prior high)
      T2 = 127.2% extension
      T3 = 161.8% extension
    Falls back to recent high if no pivot structure is found.
    """
    current = float(df["Close"].iloc[-1])
    pivots = find_fib_pivots(df, p_highs, p_lows, current)

    if pivots:
        swing_low = pivots["swing_low"]
        swing_high = pivots["swing_high"]
    else:
        swing_low = stop
        lookback = df["High"].iloc[-60:] if len(df) >= 60 else df["High"]
        swing_high = float(lookback.max())

    move = swing_high - swing_low
    if move <= 0:
        move = max(abs(entry - stop), 0.01) * 3
        swing_high = swing_low + move

    t1 = round(swing_low + 1.000 * move, 2)
    t2 = round(swing_low + 1.272 * move, 2)
    t3 = round(swing_low + 1.618 * move, 2)

    fib_levels = {
        "0.786": round(swing_high - 0.786 * move, 2),
        "0.618": round(swing_high - 0.618 * move, 2),
        "0.500": round(swing_high - 0.500 * move, 2),
        "0.382": round(swing_high - 0.382 * move, 2),
        "0.236": round(swing_high - 0.236 * move, 2),
    }

    return {
        "swing_low": round(swing_low, 2),
        "swing_high": round(swing_high, 2),
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "fib_levels": fib_levels,
    }


def compute_fib_targets_bearish(
    df: pd.DataFrame, p_highs: list, p_lows: list, entry: float, stop: float
) -> dict[str, Any]:
    """
    Bearish Fibonacci targets for SELL calls.
      swing_high came FIRST (peak), swing_low came SECOND (trough).
      Price bounced to entry level (between them) — selling into the bounce.
      T1 = swing_low (return to trough, 100% of the downmove)
      T2 = swing_high - 1.272 × move  (127.2% extension below swing_low)
      T3 = swing_high - 1.618 × move  (161.8% extension below swing_low)
    """
    current = float(df["Close"].iloc[-1])
    pivots = find_fib_pivots_bearish(df, p_highs, p_lows, current)

    if pivots:
        swing_low = pivots["swing_low"]
        swing_high = pivots["swing_high"]
    else:
        swing_high = stop  # stop is above entry for a short
        lookback = df["Low"].iloc[-60:] if len(df) >= 60 else df["Low"]
        swing_low = float(lookback.min())

    move = swing_high - swing_low
    if move <= 0:
        move = max(abs(stop - entry), 0.01) * 3
        swing_low = swing_high - move

    t1 = round(swing_high - 1.000 * move, 2)  # = swing_low
    t2 = round(swing_high - 1.272 * move, 2)
    t3 = round(swing_high - 1.618 * move, 2)

    fib_levels = {
        "0.236": round(swing_low + 0.236 * move, 2),
        "0.382": round(swing_low + 0.382 * move, 2),
        "0.500": round(swing_low + 0.500 * move, 2),
        "0.618": round(swing_low + 0.618 * move, 2),
        "0.786": round(swing_low + 0.786 * move, 2),
    }

    return {
        "swing_low": round(swing_low, 2),
        "swing_high": round(swing_high, 2),
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "fib_levels": fib_levels,
    }


# ── technical helpers ─────────────────────────────────────────────────────────


def run_technicals(
    ticker: str, period: str = "2y", make_chart: bool = False
) -> tuple[dict | None, dict | None, list[dict], dict]:
    """
    Download OHLCV, run pattern detection, and return:
      (best_bullish_signal, best_bearish_signal, all_patterns, structure_result)
    """
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if raw.empty:
            return None, None, [], {}
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        if len(df) < 30:
            return None, None, [], {}

        indic = compute_indicators(df)

        engine = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
        finder = PatternFinder(
            price_tolerance=0.03, min_pullback=0.03, recent_candle_bars=15, recent_chart_bars=30
        )

        result = engine.analyze_structure(df)
        p_highs, p_lows = engine._find_pivots(df)
        patterns = finder.find_all(df, p_highs, p_lows)
        patterns += finder.find_forming(df, p_highs, p_lows)

        if not patterns:
            return None, None, [], result

        compute_entry_signals(patterns, df, indicators=indic)

        current = float(df["Close"].iloc[-1])
        vis_sup = select_zones(result.get("support_zones", []), current, "support", 3)
        vis_res = select_zones(result.get("resistance_zones", []), current, "resistance", 3)
        lt_sup = select_trendlines(
            result.get("long_term_support_trendlines", []), current, "support"
        )
        lt_res = select_trendlines(
            result.get("long_term_resistance_trendlines", []), current, "resistance"
        )
        st_sup = select_trendlines(
            result.get("short_term_support_trendlines", []), current, "support"
        )
        st_res = select_trendlines(
            result.get("short_term_resistance_trendlines", []), current, "resistance"
        )

        annotate_at_levels(patterns, vis_sup, vis_res, lt_sup + st_sup, lt_res + st_res, df)

        # ── Best bullish signal ───────────────────────────────────────────────
        BUY_RANK = {"BUY": 0, "BUY?": 1, "WATCH-LONG": 2}
        SELL_RANK = {"SELL": 0, "SELL?": 1, "WATCH-SHORT": 2}

        bullish = [
            p
            for p in patterns
            if p.get("signal") in BUY_RANK
            and p.get("entry_price")
            and p.get("stop_loss")
            and p.get("name") not in WEAK_PATTERNS
            and p.get("risk_pct", 0) >= 2.0
        ]

        bearish = [
            p
            for p in patterns
            if p.get("signal") in SELL_RANK
            and p.get("entry_price")
            and p.get("stop_loss")
            and p.get("name") not in WEAK_PATTERNS
            and p.get("risk_pct", 0) >= 2.0
        ]

        best_bull = best_bear = None

        if bullish:
            best_bull = min(
                bullish,
                key=lambda p: (
                    BUY_RANK[p["signal"]],
                    not p.get("vol_confirmed", False),
                    -p["completed_bar"],
                ),
            )
            entry = best_bull["entry_price"]
            stop = best_bull["stop_loss"]
            risk = entry - stop

            fib = compute_fib_targets(df, p_highs, p_lows, entry, stop)
            t1, t2, t3 = fib["t1"], fib["t2"], fib["t3"]

            def _rr_bull(tgt):
                return round((tgt - entry) / risk, 2) if risk > 0 and tgt > entry else 0

            best_bull["swing_target"] = t1
            best_bull["t1"] = t1
            best_bull["t2"] = t2
            best_bull["t3"] = t3
            best_bull["swing_low"] = fib["swing_low"]
            best_bull["swing_high"] = fib["swing_high"]
            best_bull["fib_levels"] = fib["fib_levels"]
            best_bull["risk_reward"] = _rr_bull(t1)
            best_bull["rr_t2"] = _rr_bull(t2)
            best_bull["rr_t3"] = _rr_bull(t3)
            enrich_trade_signal(best_bull, df, ticker, indic)

        if bearish:
            best_bear = min(
                bearish,
                key=lambda p: (
                    SELL_RANK[p["signal"]],
                    not p.get("vol_confirmed", False),
                    -p["completed_bar"],
                ),
            )
            entry_s = best_bear["entry_price"]
            stop_s = best_bear["stop_loss"]
            risk_s = stop_s - entry_s  # stop is ABOVE entry for a short

            fib_b = compute_fib_targets_bearish(df, p_highs, p_lows, entry_s, stop_s)
            t1_s, t2_s, t3_s = fib_b["t1"], fib_b["t2"], fib_b["t3"]

            def _rr_bear(tgt):
                return round((entry_s - tgt) / risk_s, 2) if risk_s > 0 and tgt < entry_s else 0

            best_bear["swing_target"] = t1_s
            best_bear["t1"] = t1_s
            best_bear["t2"] = t2_s
            best_bear["t3"] = t3_s
            best_bear["swing_low"] = fib_b["swing_low"]
            best_bear["swing_high"] = fib_b["swing_high"]
            best_bear["fib_levels"] = fib_b["fib_levels"]
            best_bear["risk_reward"] = _rr_bear(t1_s)
            best_bear["rr_t2"] = _rr_bear(t2_s)
            best_bear["rr_t3"] = _rr_bear(t3_s)
            enrich_trade_signal(best_bear, df, ticker, indic)

        if make_chart:
            try:
                out = save_chart(ticker, period, df, result, patterns, p_highs, p_lows)
                logger.info(f"Chart saved: {out}")
            except Exception as e:
                logger.warning(f"Chart generation failed for {ticker}: {e}")

        return best_bull, best_bear, patterns, result

    except Exception as e:
        logger.warning(f"Technical analysis failed for {ticker}: {e}")
        return None, None, [], {}


# ── sentiment conviction adjustment ──────────────────────────────────────────

_LT_DOWNGRADE = {
    "STRONG BUY": "BUY",
    "BUY": "ACCUMULATE",
    "ACCUMULATE": "WATCH",
    "WATCH": "WATCH",
}
_SW_DOWNGRADE = {
    "HIGH CONVICTION": "CONFIRMED",
    "CONFIRMED": "SETUP",
    "SETUP": "SETUP",
}


def sentiment_adjust(conviction: str, sentiment_label: str, call_type: str) -> tuple[str, bool]:
    """Downgrade conviction one tier when news is bearish. Returns (new_conv, was_flagged)."""
    if sentiment_label != "BEARISH":
        return conviction, False
    table = _LT_DOWNGRADE if call_type == "LONG-TERM" else _SW_DOWNGRADE
    new = table.get(conviction, conviction)
    flagged = new != conviction
    return new, flagged


# Additive trader-grade fields copied from an enriched signal into call JSON.
_TRADER_FIELD_KEYS = (
    "pattern_score",
    "setup_score",
    "setup_grade",
    "mtf_score",
    "mtf_aligned",
    "rs_mansfield",
    "rs_trend",
    "rs_percentile",
    "rvol",
    "trend_strength",
    "rsi_divergence",
    "pattern_stop",
    "stop_source",
    "stop_pct",
    "position_shares",
    "position_value",
    "capital_at_risk",
)


def _trader_fields(sig: dict) -> dict:
    return {k: sig.get(k) for k in _TRADER_FIELD_KEYS if k in sig}


# ── conviction label ──────────────────────────────────────────────────────────


def swing_conviction(sig: dict) -> str:
    """
    Conviction tier — three-level fallback chain:

    1. setup_score (trader-grade composite: pattern + weekly MTF + relative
       strength + volume + R:R) when present:
         HIGH CONVICTION  ≥ 70  AND weekly trend not against setup AND rr ≥ 2.0
         CONFIRMED        ≥ 58  AND rr ≥ 1.5
         SETUP            otherwise
    2. pattern_score (older composite) when setup_score absent.
    3. Original vol + level + R:R heuristic.
    """
    score = sig.get("pattern_score")
    rr = sig.get("risk_reward", 0) or 0

    setup = sig.get("setup_score")
    if setup is not None:
        mtf_against = sig.get("mtf_aligned") is False
        if setup >= 70 and not mtf_against and rr >= 2.0:
            return "HIGH CONVICTION"
        if setup >= 58 and rr >= 1.5:
            return "CONFIRMED"
        return "SETUP"

    if score is not None:
        if score >= 62 and rr >= 1.8:
            return "HIGH CONVICTION"
        if score >= 42 and rr >= 1.3:
            return "CONFIRMED"
        return "SETUP"

    # Fallback for patterns scored without indicators
    vol = sig.get("vol_confirmed", False)
    at = sig.get("at_level")
    s = sig.get("signal", "")
    if s == "BUY" and vol and at and rr >= 2.0:
        return "HIGH CONVICTION"
    if s in ("BUY", "BUY?") and (vol or at) and rr >= 1.5:
        return "CONFIRMED"
    return "SETUP"


def lt_conviction(score: float, upside: float | None, rating: str) -> str:
    if upside is None:
        upside = 0
    if score >= 78 and upside >= 0.20:
        return "STRONG BUY"
    if score >= 70 and upside >= 0.12:
        return "BUY"
    if score >= 64 and upside >= 0.08:
        return "ACCUMULATE"
    if "Watchlist" in rating or "Hold" in rating:
        return "WATCH"
    return "WATCH"


# ── formatting ────────────────────────────────────────────────────────────────


def currency_sym(cur: str) -> str:
    return {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}.get(cur, cur + " ")


def fmt(val: float | None, sym: str = "$", pct: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "—"
    if pct:
        return f"{val*100:+.1f}%"
    if abs(val) >= 1e9:
        return f"{sym}{val/1e9:.2f}B"
    if abs(val) >= 1e6:
        return f"{sym}{val/1e6:.2f}M"
    return f"{sym}{val:,.2f}"


# ── main ─────────────────────────────────────────────────────────────────────


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--tickers",
        type=str,
        default=None,
        help="Comma-separated tickers, e.g. AAPL,MSFT,RELIANCE.NS",
    )
    p.add_argument(
        "--period",
        type=str,
        default="2y",
        help="Price history period for technical analysis (default: 2y — needed for weekly MTF + RS)",
    )
    p.add_argument(
        "--no-fundamentals",
        action="store_true",
        help="Skip fundamental screen, show technical-only swing calls",
    )
    p.add_argument(
        "--no-sentiment",
        action="store_true",
        help="Skip news sentiment analysis (faster, no FinBERT download)",
    )
    p.add_argument(
        "--save-charts",
        action="store_true",
        help="Save a technical chart PNG for every ticker analyzed",
    )
    p.add_argument(
        "--telegram",
        action="store_true",
        help="Send equity calls to Telegram after generating (requires config/telegram.json)",
    )
    p.add_argument(
        "--telegram-smart-money",
        action="store_true",
        help="Include smart money summary in Telegram message",
    )
    return p.parse_args()


def load_or_refresh_fundamentals(tickers: list[str], force: bool = False) -> dict[str, dict]:
    """Return {ticker: fund_row_dict} from cache if fresh, else re-run screen."""
    if not force and os.path.exists(LIVE_FUND_CACHE):
        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(LIVE_FUND_CACHE))
        if age < timedelta(hours=CACHE_MAX_AGE_H):
            with open(LIVE_FUND_CACHE, "rb") as f:
                cached = pickle.load(f)
            # check if all requested tickers are in cache
            if all(t in cached for t in tickers):
                return cached

    config_path = "config/scanner_config.yaml"
    config = load_config_from_file(config_path)
    engine = FundamentalEngine(config)
    df = engine.analyze_tickers(tickers, as_of_year=None)

    result = {}
    if not df.empty:
        for _, row in df.iterrows():
            result[row["ticker"]] = row.to_dict()

    os.makedirs("reports", exist_ok=True)
    with open(LIVE_FUND_CACHE, "wb") as f:
        pickle.dump(result, f)
    return result


def generate_calls(
    tickers: list[str],
    period: str,
    run_fundamentals: bool,
    save_charts: bool = False,
    force_refresh: bool = False,
    run_sentiment: bool = True,
) -> dict:
    """
    Main call generation. Returns a dict with long_term_calls and swing_calls.
    """
    # Split US vs India (FinanceToolkit works better with US tickers)
    us_tickers = [t for t in tickers if not t.endswith(".NS") and not t.endswith(".BO")]
    [t for t in tickers if t.endswith((".NS", ".BO"))]

    # ── Fundamentals ──────────────────────────────────────────────────────────
    fund_data: dict[str, dict] = {}
    if run_fundamentals and us_tickers:
        fund_data = load_or_refresh_fundamentals(us_tickers, force=force_refresh)

    # ── Sentiment ─────────────────────────────────────────────────────────────
    sentiment_data: dict[str, dict] = {}
    if run_sentiment:
        try:
            sent_engine = SentimentEngine()
            sentiment_data = sent_engine.analyze_batch(tickers)
        except ImportError:
            pass
        except Exception:
            pass

    # ── Generate calls ────────────────────────────────────────────────────────
    long_term_calls: list[dict] = []
    swing_calls: list[dict] = []
    sell_calls: list[dict] = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    for ticker in tickers:
        # yfinance live data
        yf_d = get_yf_fundamentals(ticker)
        price = yf_d.get("current_price") or 0
        currency_sym(yf_d.get("currency", "USD"))
        if price <= 0:
            continue

        # Sentiment (pre-computed in batch above)
        sent = sentiment_data.get(ticker, {})
        sent_label = sent.get("sentiment_label", "NEUTRAL")
        sent_score = sent.get("sentiment_score", 0)
        sent_headlines = sent.get("top_headlines", [])
        sent_count = sent.get("news_count", 0)

        # Technical
        best_sig, best_sell, all_patterns, struct = run_technicals(
            ticker, period, make_chart=save_charts
        )
        f"BUY={best_sig['signal']}" if best_sig else "no buy"
        f"SELL={best_sell['signal']}" if best_sell else "no sell"

        # ── Long-term call ────────────────────────────────────────────────────
        fund_row = fund_data.get(ticker)
        if fund_row:
            score = float(fund_row.get("total_score", 0))
            rating = str(fund_row.get("rating", ""))
            if score >= MIN_FUND_SCORE and "Avoid" not in rating:
                fv = fair_value_estimate(yf_d, fund_row)
                upside = fv.get("upside_pct")
                conv = lt_conviction(score, upside, rating)

                original_conv = conv
                conv, sent_flagged = sentiment_adjust(conv, sent_label, "LONG-TERM")
                sent_boost = sent_label == "BULLISH"

                # Build thesis from existing strength/weakness text
                strengths = fund_row.get("strengths", [])[:2]
                weaknesses = fund_row.get("weaknesses", [])[:1]
                risks_list = fund_row.get("risks", [])[:1]
                thesis = []
                if strengths:
                    thesis += [f"+ {s}" for s in strengths]
                if weaknesses:
                    thesis += [f"- {w}" for w in weaknesses]
                if risks_list:
                    thesis += [f"! {r}" for r in risks_list]

                # Technical context for entry timing
                tech_context = struct.get("context", "")
                at_support = any(
                    p.get("at_level") and "Sup" in str(p.get("at_level", "")) for p in all_patterns
                )

                lt_call = {
                    "ticker": ticker,
                    "name": yf_d["name"],
                    "sector": yf_d["sector"],
                    "date": date_str,
                    "call_type": "LONG-TERM",
                    "conviction": conv,
                    "current_price": round(price, 2),
                    "currency": yf_d.get("currency", "USD"),
                    "fair_value": fv.get("fair_value"),
                    "fv_method": fv.get("method"),
                    "upside_pct": upside,
                    "analyst_target": yf_d.get("analyst_target"),
                    "fund_score": round(score, 1),
                    "rating": rating,
                    "pe": yf_d.get("trailing_pe"),
                    "forward_pe": yf_d.get("forward_pe"),
                    "roic_3y": fund_row.get("roic_3y"),
                    "op_margin": fund_row.get("operating_margin"),
                    "rev_growth_3y": fund_row.get("revenue_growth_3y"),
                    "52w_high": yf_d.get("52w_high"),
                    "52w_low": yf_d.get("52w_low"),
                    "market_cap": yf_d.get("market_cap"),
                    "tech_context": tech_context,
                    "at_support": at_support,
                    "thesis": thesis,
                    "entry_note": (
                        "Good technical entry — at support"
                        if at_support
                        else "Wait for pullback to support"
                        if "Resistance" in tech_context
                        else "Buy in tranches"
                    ),
                    # Fib targets from technical setup (when available)
                    "t1": best_sig.get("t1") if best_sig else None,
                    "t2": best_sig.get("t2") if best_sig else None,
                    "t3": best_sig.get("t3") if best_sig else None,
                    "swing_low": best_sig.get("swing_low") if best_sig else None,
                    "swing_high": best_sig.get("swing_high") if best_sig else None,
                    # Sentiment
                    "sentiment_label": sent_label,
                    "sentiment_score": sent_score,
                    "sentiment_flagged": sent_flagged,
                    "sentiment_boost": sent_boost,
                    "sentiment_note": (
                        f"Downgraded from {original_conv} — bearish news"
                        if sent_flagged
                        else "Supported by bullish news"
                        if sent_boost
                        else ""
                    ),
                    "news_count": sent_count,
                    "top_headlines": sent_headlines,
                }
                long_term_calls.append(lt_call)

        # ── Swing call ────────────────────────────────────────────────────────
        if best_sig and best_sig.get("risk_reward", 0) >= MIN_RR:
            entry = best_sig["entry_price"]
            stop = best_sig["stop_loss"]
            t1 = best_sig.get("t1") or best_sig["swing_target"]
            t2 = best_sig.get("t2", t1)
            t3 = best_sig.get("t3", t1)
            conv = swing_conviction(best_sig)
            sw_orig_conv = conv
            conv, sw_sent_flagged = sentiment_adjust(conv, sent_label, "SWING")

            swing_call = {
                "ticker": ticker,
                "name": yf_d["name"],
                "sector": yf_d["sector"],
                "date": date_str,
                "call_type": "SWING",
                "conviction": conv,
                "signal": best_sig["signal"],
                "pattern": best_sig["name"],
                "at_level": best_sig.get("at_level"),
                "vol_confirmed": best_sig.get("vol_confirmed", False),
                "vol_ratio": best_sig.get("vol_ratio", 0),
                "current_price": round(price, 2),
                "currency": yf_d.get("currency", "USD"),
                "entry_price": round(entry, 2),
                "stop_loss": round(stop, 2),
                "target": t1,  # backward compat — primary target
                "t1": t1,
                "t2": t2,
                "t3": t3,
                "swing_low": best_sig.get("swing_low"),
                "swing_high": best_sig.get("swing_high"),
                "fib_levels": best_sig.get("fib_levels", {}),
                "risk_pct": round(best_sig.get("risk_pct", 0), 2),
                "risk_reward": best_sig.get("risk_reward", 0),
                "rr_t2": best_sig.get("rr_t2", 0),
                "rr_t3": best_sig.get("rr_t3", 0),
                "upside_pct": round((t1 - entry) / entry, 4) if entry else 0,
                "upside_t2": round((t2 - entry) / entry, 4) if entry else 0,
                "upside_t3": round((t3 - entry) / entry, 4) if entry else 0,
                "fund_score": round(float(fund_row.get("total_score", 0)), 1) if fund_row else None,
                "forming": best_sig.get("forming", False),
                "time_horizon": "1–4 weeks" if not best_sig.get("forming") else "Wait for breakout",
                # Sentiment
                "sentiment_label": sent_label,
                "sentiment_score": sent_score,
                "sentiment_flagged": sw_sent_flagged,
                "sentiment_note": (
                    f"Downgraded from {sw_orig_conv} — bearish news" if sw_sent_flagged else ""
                ),
                "news_count": sent_count,
                "top_headlines": sent_headlines,
            }
            swing_call.update(_trader_fields(best_sig))
            swing_calls.append(swing_call)

        # ── Sell call ─────────────────────────────────────────────────────────
        if best_sell and best_sell.get("risk_reward", 0) >= MIN_RR:
            entry_s = best_sell["entry_price"]
            stop_s = best_sell["stop_loss"]
            t1_s = best_sell.get("t1") or best_sell["swing_target"]
            t2_s = best_sell.get("t2", t1_s)
            t3_s = best_sell.get("t3", t1_s)
            conv_s = (
                "HIGH CONVICTION"
                if (
                    best_sell.get("vol_confirmed")
                    and best_sell.get("signal") == "SELL"
                    and best_sell.get("risk_reward", 0) >= 2.0
                )
                else "CONFIRMED"
                if best_sell.get("signal") in ("SELL", "SELL?")
                else "SETUP"
            )
            sl_orig_conv = conv_s
            # For sell calls, bullish news is a headwind (downgrade); bearish news is a tailwind
            sl_sent_adj = (
                "BEARISH"
                if sent_label == "BULLISH"
                else "BULLISH"
                if sent_label == "BEARISH"
                else "NEUTRAL"
            )
            conv_s, sl_sent_flagged = sentiment_adjust(conv_s, sl_sent_adj, "SWING")

            sell_call = {
                "ticker": ticker,
                "name": yf_d["name"],
                "sector": yf_d["sector"],
                "date": date_str,
                "call_type": "SELL",
                "conviction": conv_s,
                "signal": best_sell["signal"],
                "pattern": best_sell["name"],
                "at_level": best_sell.get("at_level"),
                "vol_confirmed": best_sell.get("vol_confirmed", False),
                "vol_ratio": best_sell.get("vol_ratio", 0),
                "current_price": round(price, 2),
                "currency": yf_d.get("currency", "USD"),
                "entry_price": round(entry_s, 2),
                "stop_loss": round(stop_s, 2),
                "t1": t1_s,
                "t2": t2_s,
                "t3": t3_s,
                "swing_low": best_sell.get("swing_low"),
                "swing_high": best_sell.get("swing_high"),
                "fib_levels": best_sell.get("fib_levels", {}),
                "risk_pct": round(best_sell.get("risk_pct", 0), 2),
                "risk_reward": best_sell.get("risk_reward", 0),
                "rr_t2": best_sell.get("rr_t2", 0),
                "rr_t3": best_sell.get("rr_t3", 0),
                "downside_pct": round((entry_s - t1_s) / entry_s, 4) if entry_s else 0,
                "downside_t2": round((entry_s - t2_s) / entry_s, 4) if entry_s else 0,
                "downside_t3": round((entry_s - t3_s) / entry_s, 4) if entry_s else 0,
                "fund_score": round(float(fund_row.get("total_score", 0)), 1) if fund_row else None,
                "forming": best_sell.get("forming", False),
                "time_horizon": "1–4 weeks"
                if not best_sell.get("forming")
                else "Wait for breakdown",
                # Sentiment (bullish news = headwind for a short)
                "sentiment_label": sent_label,
                "sentiment_score": sent_score,
                "sentiment_flagged": sl_sent_flagged,
                "sentiment_note": (
                    f"Downgraded from {sl_orig_conv} — bullish news is a headwind"
                    if sl_sent_flagged
                    else ""
                ),
                "news_count": sent_count,
                "top_headlines": sent_headlines,
            }
            sell_call.update(_trader_fields(best_sell))
            sell_calls.append(sell_call)

    # Sort
    long_term_calls.sort(key=lambda c: -(c.get("fund_score", 0)))
    swing_calls.sort(
        key=lambda c: (
            {"HIGH CONVICTION": 0, "CONFIRMED": 1, "SETUP": 2}.get(c["conviction"], 3),
            -(c.get("setup_score") or 0),
            -c["risk_reward"],
        )
    )
    sell_calls.sort(
        key=lambda c: (
            {"HIGH CONVICTION": 0, "CONFIRMED": 1, "SETUP": 2}.get(c["conviction"], 3),
            -(c.get("setup_score") or 0),
            -c["risk_reward"],
        )
    )

    # Persist BUY positions to database (SELL/bearish signals are NOT tracked as positions)
    try:
        for c in long_term_calls:
            upsert_call(c, "LONG-TERM")
        for c in swing_calls:
            upsert_call(c, "SWING")
        export_portfolio_json()
    except Exception:
        pass

    return {
        "long_term_calls": long_term_calls,
        "swing_calls": swing_calls,
        "sell_calls": sell_calls,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── print formatted call sheet ────────────────────────────────────────────────


def print_calls(calls: dict):
    lt = calls["long_term_calls"]
    sw = calls["swing_calls"]
    sl = calls.get("sell_calls", [])
    now = calls["generated_at"]

    def line(ch="-"):
        pass

    def header(text):
        pass

    header(f"EQUITY CALLS  —  {now}")

    # ── Long-term calls ───────────────────────────────────────────────────────
    line()

    if not lt:
        pass
    for c in lt:
        sym = currency_sym(c.get("currency", "USD"))
        f"{sym}{c['current_price']:,.2f}"
        f"{sym}{c['fair_value']:,.2f}" if c.get("fair_value") else "   —"
        f"{c['upside_pct']*100:+.1f}%" if c.get("upside_pct") is not None else "   —"
        f"{c['pe']:.1f}x" if c.get("pe") else "   —"
        f"{c['fund_score']}"

        if c.get("tech_context"):
            pass

        for _t in c.get("thesis", [])[:3]:
            pass

        if c.get("analyst_target"):
            c["analyst_target"]
            currency_sym(c.get("currency", "USD"))

    # ── Swing calls ───────────────────────────────────────────────────────────
    line()

    if not sw:
        pass
    for c in sw:
        sym = currency_sym(c.get("currency", "USD"))
        f"{sym}{c['entry_price']:,.2f}"
        f"{sym}{c['stop_loss']:,.2f}"
        f"{sym}{c['t1']:,.2f}" if c.get("t1") else "—"
        f"{sym}{c['t2']:,.2f}" if c.get("t2") else "—"
        f"{sym}{c['t3']:,.2f}" if c.get("t3") else "—"
        f"{c['risk_reward']:.1f}:1"
        c["pattern"][:21]
        " [F]" if c.get("forming") else ""
        vol = " [V]" if c.get("vol_confirmed") else ""

        swing_lo = c.get("swing_low")
        swing_hi = c.get("swing_high")
        if swing_lo and swing_hi:
            pass

        lvl = c.get("at_level", "")
        notes = []
        if lvl:
            notes.append(str(lvl))
        if vol:
            notes.append("Vol confirmed")
        if c.get("signal") == "WATCH-LONG":
            notes.append("Wait for entry trigger")
        if notes:
            pass

        if c.get("fund_score"):
            pass

    # ── Sell calls ────────────────────────────────────────────────────────────
    line()

    if not sl:
        pass
    for c in sl:
        sym = currency_sym(c.get("currency", "USD"))
        f"{sym}{c['entry_price']:,.2f}"
        f"{sym}{c['stop_loss']:,.2f}"
        f"{sym}{c['t1']:,.2f}" if c.get("t1") else "—"
        f"{sym}{c['t2']:,.2f}" if c.get("t2") else "—"
        f"{sym}{c['t3']:,.2f}" if c.get("t3") else "—"
        f"{c['risk_reward']:.1f}:1"
        c["pattern"][:21]
        " [F]" if c.get("forming") else ""
        vol = " [V]" if c.get("vol_confirmed") else ""

        swing_lo = c.get("swing_low")
        swing_hi = c.get("swing_high")
        if swing_lo and swing_hi:
            pass

        lvl = c.get("at_level", "")
        notes = []
        if lvl:
            notes.append(str(lvl))
        if vol:
            notes.append("Vol confirmed")
        if c.get("signal") == "WATCH-SHORT":
            notes.append("Wait for breakdown trigger")
        if notes:
            pass

        if c.get("fund_score"):
            pass

    # ── Summary ───────────────────────────────────────────────────────────────
    sum(1 for c in lt if c["conviction"] == "STRONG BUY")
    sum(1 for c in lt if c["conviction"] == "BUY")
    sum(1 for c in lt if c["conviction"] == "ACCUMULATE")
    sum(1 for c in sw if c["conviction"] == "HIGH CONVICTION")
    sum(1 for c in sw if c["conviction"] == "CONFIRMED")
    sum(1 for c in sl if c["conviction"] == "HIGH CONVICTION")
    sum(1 for c in sl if c["conviction"] == "CONFIRMED")

    line("=")
    line("=")


# ── entry point ───────────────────────────────────────────────────────────────


def main():
    args = parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = DEFAULT_US + DEFAULT_INDIA

    run_fund = not args.no_fundamentals
    run_sentiment = not args.no_sentiment

    calls = generate_calls(
        tickers, args.period, run_fund, save_charts=args.save_charts, run_sentiment=run_sentiment
    )

    print_calls(calls)

    os.makedirs("reports", exist_ok=True)
    os.makedirs("dashboard", exist_ok=True)
    out_path = "reports/equity_calls.json"
    dash_path = "dashboard/equity_calls.json"
    payload = json.dumps(calls, indent=2, default=str)
    with open(out_path, "w") as f:
        f.write(payload)
    with open(dash_path, "w") as f:
        f.write(payload)

    if args.telegram:
        try:
            from telegram_notifier import send_calls

            send_calls(include_smart_money=args.telegram_smart_money)
        except Exception:
            pass


if __name__ == "__main__":
    main()
