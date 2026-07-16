"""
scan_and_alert.py
=================
Full-universe US stock scanner designed to run once per day via Windows Task Scheduler.

Two-tier caching strategy:
  ┌─ FUNDAMENTAL UNIVERSE (reports/fund_universe.json) ─────────────────────────┐
  │  Per-ticker cache with 30-day TTL.                                           │
  │  First run: screens all S&P 500 (~30-45 min).                                │
  │  Daily runs: re-screens only tickers whose 30-day window expired.            │
  │  Stores: score, rating, passes/fails, strengths, weaknesses, risks.          │
  └──────────────────────────────────────────────────────────────────────────────┘
  ┌─ DAILY TECHNICAL SCAN ───────────────────────────────────────────────────────┐
  │  Runs every day on the "strong universe" (tickers that passed fundamentals). │
  │  Technicals + sentiment + insider + hedge-fund — fast, ~5-15 min.            │
  │  Sends one rich Telegram report per HIGH CONVICTION / CONFIRMED signal.      │
  └──────────────────────────────────────────────────────────────────────────────┘

Usage:
    python scan_and_alert.py                       # normal daily run
    python scan_and_alert.py --no-telegram         # scan only, no Telegram
    python scan_and_alert.py --force-refund        # force re-screen all fundamentals now
    python scan_and_alert.py --min-conviction SETUP
    python scan_and_alert.py --tickers AAPL,MSFT   # ad-hoc specific tickers
    python scan_and_alert.py --show-universe       # print current strong universe and exit
"""

import os, sys, json, math, time, argparse, logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import yfinance as yf
import requests

from stock_scanner.config import load_config_from_file
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.engine.technical import MarketStructureEngine
from stock_scanner.engine.patterns import PatternFinder
from stock_scanner.engine.sentiment import SentimentEngine
from stock_scanner.engine.indicators import compute_indicators
from stock_scanner.engine.trade_quality import enrich_trade_signal
from stock_scanner.engine.relative_strength import rs_percentile, benchmark_for
from visualize_technical import (compute_entry_signals, annotate_at_levels,
                                  select_zones, select_trendlines,
                                  find_fib_pivots, find_fib_pivots_bearish)
# Reuse helpers from generate_calls
from generate_calls import (
    graham_number, get_yf_fundamentals, fair_value_estimate,
    compute_fib_targets, compute_fib_targets_bearish,
    swing_conviction, lt_conviction, sentiment_adjust,
    currency_sym, fmt, WEAK_PATTERNS, MIN_RR
)
# Smart money helpers
from smart_money import fetch_insider_data, fetch_hf_data

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("scan_alert")

FUND_UNIVERSE_PATH = "reports/fund_universe.json"   # per-ticker 30-day cache
FUND_TTL_DAYS      = 30       # re-screen a ticker after this many days
MIN_FUND_SCORE     = 62.0     # minimum score to enter the strong universe
INSIDER_DAYS       = 60

# ── Ticker universe ────────────────────────────────────────────────────────────

SP500_FALLBACK = [
    # Mega-cap tech & AI
    "AAPL","MSFT","NVDA","GOOGL","GOOG","META","AMZN","AVGO","TSLA","ORCL",
    "ADBE","CRM","NOW","MU","AMD","QCOM","INTC","TXN","CSCO","PLTR","UBER",
    "NFLX","AMAT","LRCX","KLAC","MRVL","SNPS","CDNS","ANSS",
    # Financials
    "JPM","BAC","WFC","GS","MS","BLK","AXP","V","MA","SPGI","MCO","ICE",
    "CME","SCHW","BX","KKR","APO",
    # Healthcare
    "LLY","UNH","JNJ","ABBV","MRK","PFE","TMO","ABT","DHR","BSX","ISRG",
    "SYK","MDT","AMGN","GILD","REGN","VRTX","MRNA","BMY","CVS","CI",
    # Consumer
    "WMT","COST","HD","TGT","LOW","MCD","SBUX","NKE","PG","KO","PEP",
    "PM","MO","CL","MDLZ","GIS","K","HRL",
    # Industrials & Energy
    "CAT","DE","HON","GE","RTX","LMT","BA","UPS","FDX","XOM","CVX",
    "COP","PSX","SLB","EOG","PXD","MPC","VLO",
    # Real estate & utilities
    "AMT","PLD","EQIX","CCI","SPG","O","DLR",
    # Materials
    "LIN","APD","SHW","ECL","NEM","FCX",
    # Consumer discretionary
    "AMZN","TSLA","BKNG","ABNB","MAR","HLT","CMG","YUM","DRI",
]


def get_sp500_tickers() -> List[str]:
    """Fetch S&P 500 tickers from Wikipedia. Falls back to curated list on failure."""
    try:
        print("  Loading S&P 500 tickers from Wikipedia ...", end=" ", flush=True)
        import requests
        from io import StringIO
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text), attrs={"id": "constituents"})
        tickers = tables[0]["Symbol"].tolist()
        # Clean: BRK.B -> BRK-B, etc.
        tickers = [t.replace(".", "-") for t in tickers if isinstance(t, str)]
        print(f"OK ({len(tickers)} tickers)")
        return sorted(set(tickers))
    except Exception as e:
        print(f"FAILED ({e}), using curated fallback list ({len(SP500_FALLBACK)} tickers)")
        return sorted(set(SP500_FALLBACK))


# ── Fundamental universe — 30-day per-ticker cache ────────────────────────────

def load_universe() -> Dict[str, Dict]:
    """Load the fund_universe.json file. Returns {} if it doesn't exist yet."""
    if os.path.exists(FUND_UNIVERSE_PATH):
        with open(FUND_UNIVERSE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_universe(universe: Dict):
    os.makedirs("reports", exist_ok=True)
    with open(FUND_UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2, default=str)


def ticker_needs_rescore(entry: Dict) -> bool:
    """True if the ticker has never been scored or its score is older than FUND_TTL_DAYS."""
    last = entry.get("last_scored")
    if not last:
        return True
    try:
        age = datetime.now() - datetime.fromisoformat(str(last))
        return age.days >= FUND_TTL_DAYS
    except Exception:
        return True


def refresh_fundamentals(tickers_to_screen: List[str], universe: Dict) -> Dict:
    """
    Run FundamentalEngine on tickers_to_screen and merge results into universe.
    Saves after each chunk so progress isn't lost on crash.
    """
    if not tickers_to_screen:
        return universe

    print(f"\n  Scoring {len(tickers_to_screen)} tickers (fundamentals, ~{len(tickers_to_screen)//10} min) ...")
    config = load_config_from_file("config/scanner_config.yaml")
    engine = FundamentalEngine(config)

    chunk_size = 50
    total_chunks = math.ceil(len(tickers_to_screen) / chunk_size)
    scored = 0

    for i in range(0, len(tickers_to_screen), chunk_size):
        chunk = tickers_to_screen[i:i + chunk_size]
        print(f"  Chunk {i//chunk_size + 1}/{total_chunks}: {chunk[0]}…{chunk[-1]}", end=" ", flush=True)
        try:
            df = engine.analyze_tickers(chunk, as_of_year=None)
            if not df.empty:
                for _, row in df.iterrows():
                    t = row["ticker"]
                    score = float(row.get("total_score", 0) or 0)
                    passes = (score >= MIN_FUND_SCORE
                              and "Avoid" not in str(row.get("rating", "")))
                    universe[t] = {
                        "score":             round(score, 2),
                        "rating":            str(row.get("rating", "") or ""),
                        "passes":            passes,
                        "last_scored":       datetime.now().isoformat(),
                        "strengths":         list(row.get("strengths",  []) or []),
                        "weaknesses":        list(row.get("weaknesses", []) or []),
                        "risks":             list(row.get("risks",      []) or []),
                        "roic_3y":           row.get("roic_3y"),
                        "revenue_growth_3y": row.get("revenue_growth_3y"),
                        "operating_margin":  row.get("operating_margin"),
                    }
                    scored += 1
            print(f"OK (+{min(len(chunk), scored)} scored)")
        except Exception as e:
            print(f"FAILED ({e})")
            logger.warning(f"Fundamental chunk failed: {e}")

        # Save after every chunk so a crash doesn't lose progress
        save_universe(universe)

    return universe


def get_strong_universe(universe: Dict) -> List[str]:
    """Return tickers that passed the fundamental screen (score ≥ MIN_FUND_SCORE)."""
    return [t for t, d in universe.items() if d.get("passes", False)]


def print_universe_status(universe: Dict):
    strong = get_strong_universe(universe)
    weak   = [t for t, d in universe.items() if not d.get("passes", False)]
    now    = datetime.now()
    stale  = [t for t, d in universe.items() if ticker_needs_rescore(d)]

    print(f"\n{'='*60}")
    print(f"  FUNDAMENTAL UNIVERSE STATUS")
    print(f"  Total scored: {len(universe)}  |  Strong: {len(strong)}  |  Weak/Avoid: {len(weak)}")
    print(f"  Stale (needs re-score in next run): {len(stale)}")
    print(f"\n  Strong universe ({len(strong)} tickers):")
    rows = sorted([(t, universe[t]["score"]) for t in strong], key=lambda x: -x[1])
    for t, sc in rows:
        d   = universe[t]
        age = (now - datetime.fromisoformat(str(d["last_scored"]))).days
        print(f"    {t:<8} score={sc:.0f}  rating={d['rating'][:20]:<20}  scored {age}d ago")
    print(f"{'='*60}\n")


def update_universe(all_tickers: List[str], force: bool = False) -> Dict:
    """
    Load universe, identify tickers that need re-scoring, run FundamentalEngine on them.
    Returns the updated universe dict.
    """
    universe = load_universe()

    if force:
        tickers_to_screen = all_tickers
        print(f"  Force refresh: re-screening all {len(all_tickers)} tickers")
    else:
        # Tickers never scored OR whose 30-day window has expired
        tickers_to_screen = [
            t for t in all_tickers
            if t not in universe or ticker_needs_rescore(universe[t])
        ]

        fresh = len(all_tickers) - len(tickers_to_screen)
        if tickers_to_screen:
            print(f"  Fundamental cache: {fresh} tickers fresh (≤{FUND_TTL_DAYS}d old), "
                  f"{len(tickers_to_screen)} need re-scoring")
        else:
            print(f"  Fundamental cache: all {fresh} tickers fresh — skipping re-screen ✓")

    universe = refresh_fundamentals(tickers_to_screen, universe)
    return universe


# ── Technical scan ─────────────────────────────────────────────────────────────

def run_technicals(ticker: str, period: str = "2y") -> Tuple[Optional[Dict], Optional[Dict], List, Dict, Dict]:
    """Returns (best_bull, best_bear, all_patterns, structure_result, indicators)."""
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if raw.empty or len(raw) < 30:
            return None, None, [], {}, {}
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        df = raw[["Open","High","Low","Close","Volume"]].dropna()

        # Compute indicators once — passed into scoring so no redundant work
        indic = compute_indicators(df)

        engine  = MarketStructureEngine(window_size=5, tolerance_pct=0.015)
        finder  = PatternFinder(price_tolerance=0.03, min_pullback=0.03,
                                recent_candle_bars=15, recent_chart_bars=30)
        result  = engine.analyze_structure(df)
        p_highs, p_lows = engine._find_pivots(df)
        patterns = finder.find_all(df, p_highs, p_lows) + finder.find_forming(df, p_highs, p_lows)

        if not patterns:
            return None, None, [], result, indic

        compute_entry_signals(patterns, df, indicators=indic)

        current = float(df["Close"].iloc[-1])
        vis_sup = select_zones(result.get("support_zones",    []), current, "support",    3)
        vis_res = select_zones(result.get("resistance_zones", []), current, "resistance", 3)
        lt_sup  = select_trendlines(result.get("long_term_support_trendlines",    []), current, "support")
        lt_res  = select_trendlines(result.get("long_term_resistance_trendlines", []), current, "resistance")
        st_sup  = select_trendlines(result.get("short_term_support_trendlines",   []), current, "support")
        st_res  = select_trendlines(result.get("short_term_resistance_trendlines",[]), current, "resistance")
        annotate_at_levels(patterns, vis_sup, vis_res, lt_sup+st_sup, lt_res+st_res, df)

        BUY_RANK  = {"BUY": 0, "BUY?": 1, "WATCH-LONG": 2}
        SELL_RANK = {"SELL": 0, "SELL?": 1, "WATCH-SHORT": 2}

        bullish = [p for p in patterns
                   if p.get("signal") in BUY_RANK
                   and p.get("entry_price") and p.get("stop_loss")
                   and p.get("name") not in WEAK_PATTERNS
                   and p.get("risk_pct", 0) >= 2.0]

        bearish = [p for p in patterns
                   if p.get("signal") in SELL_RANK
                   and p.get("entry_price") and p.get("stop_loss")
                   and p.get("name") not in WEAK_PATTERNS
                   and p.get("risk_pct", 0) >= 2.0]

        best_bull = best_bear = None

        if bullish:
            # Sort: confirmed signal first, then vol, then pattern_score, then recency
            best_bull = min(bullish, key=lambda p: (
                BUY_RANK[p["signal"]],
                not p.get("vol_confirmed", False),
                -(p.get("pattern_score") or 0),
                -p["completed_bar"],
            ))
            entry, stop = best_bull["entry_price"], best_bull["stop_loss"]
            risk = entry - stop
            fib = compute_fib_targets(df, p_highs, p_lows, entry, stop)
            t1, t2, t3 = fib["t1"], fib["t2"], fib["t3"]
            best_bull.update({
                "swing_target": t1, "t1": t1, "t2": t2, "t3": t3,
                "swing_low": fib["swing_low"], "swing_high": fib["swing_high"],
                "fib_levels": fib["fib_levels"],
                "risk_reward":  round((t1-entry)/risk, 2) if risk > 0 and t1>entry else 0,
                "rr_t2": round((t2-entry)/risk, 2) if risk > 0 and t2>entry else 0,
                "rr_t3": round((t3-entry)/risk, 2) if risk > 0 and t3>entry else 0,
            })
            # Trader-grade enrichment: ATR stop, weekly MTF, RS, setup score,
            # position size — recomputes risk_reward off the chosen stop.
            enrich_trade_signal(best_bull, df, ticker, indic)
            if best_bull.get("risk_reward", 0) < MIN_RR:
                best_bull = None
            elif best_bull.get("rs_pass") is False and \
                    best_bull.get("rs_mansfield", 0) is not None and \
                    best_bull.get("rs_mansfield", 0) <= -20:
                best_bull = None   # severe laggard — hard RS fail

        if bearish:
            best_bear = min(bearish, key=lambda p: (
                SELL_RANK[p["signal"]],
                not p.get("vol_confirmed", False),
                -(p.get("pattern_score") or 0),
                -p["completed_bar"],
            ))
            entry_s, stop_s = best_bear["entry_price"], best_bear["stop_loss"]
            risk_s = stop_s - entry_s
            fib_b = compute_fib_targets_bearish(df, p_highs, p_lows, entry_s, stop_s)
            t1_s, t2_s, t3_s = fib_b["t1"], fib_b["t2"], fib_b["t3"]
            best_bear.update({
                "swing_target": t1_s, "t1": t1_s, "t2": t2_s, "t3": t3_s,
                "swing_low": fib_b["swing_low"], "swing_high": fib_b["swing_high"],
                "fib_levels": fib_b["fib_levels"],
                "risk_reward":  round((entry_s-t1_s)/risk_s, 2) if risk_s > 0 and t1_s<entry_s else 0,
                "rr_t2": round((entry_s-t2_s)/risk_s, 2) if risk_s > 0 and t2_s<entry_s else 0,
                "rr_t3": round((entry_s-t3_s)/risk_s, 2) if risk_s > 0 and t3_s<entry_s else 0,
            })
            enrich_trade_signal(best_bear, df, ticker, indic)
            if best_bear.get("risk_reward", 0) < MIN_RR:
                best_bear = None

        return best_bull, best_bear, patterns, result, indic
    except Exception as e:
        logger.debug(f"Technical failed for {ticker}: {e}")
        return None, None, [], {}, {}


# ── Telegram message builder ───────────────────────────────────────────────────

TG_API = "https://api.telegram.org/bot{token}/{method}"

def load_tg_config() -> Optional[Dict]:
    if not os.path.exists("config/telegram.json"):
        return None
    with open("config/telegram.json") as f:
        return json.load(f)

def tg_send(token: str, chat_id: str, text: str):
    url = TG_API.format(token=token, method="sendMessage")
    r = requests.post(url, json={
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }, timeout=15)
    if not r.json().get("ok"):
        logger.warning(f"Telegram error: {r.json().get('description','?')}")

def tg_send_long(token: str, chat_id: str, text: str):
    MAX = 4000
    if len(text) <= MAX:
        tg_send(token, chat_id, text)
        return
    parts, current, cur_len = [], [], 0
    for line in text.split("\n"):
        if cur_len + len(line) + 1 > MAX and current:
            parts.append("\n".join(current))
            current, cur_len = [], 0
        current.append(line)
        cur_len += len(line) + 1
    if current:
        parts.append("\n".join(current))
    for i, part in enumerate(parts):
        if i: time.sleep(0.5)
        tg_send(token, chat_id, part)

def esc(v) -> str:
    return str(v).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def pct(v, mul=True, cap=None) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    val = v * 100 if mul else v
    if cap and abs(val) > cap:
        return "—"
    return f"{val:+.1f}%"

def price(v, cur="USD") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    sym = {"USD":"$","INR":"₹","GBP":"£","EUR":"€"}.get(cur, "$")
    return f"{sym}{v:,.2f}"

def num(v, decimals=1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{decimals}f}"

def bar(value: float, max_val: float = 100, width: int = 10) -> str:
    """Visual bar: ████████░░  for 80/100"""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "░" * width
    filled = max(0, min(width, round((value / max_val) * width)))
    return "█" * filled + "░" * (width - filled)

def mktcap_str(v) -> str:
    if not v: return "—"
    return f"${v/1e12:.2f}T" if v >= 1e12 else f"${v/1e9:.1f}B"

def scorecard_dot(signal_ok: bool, neutral: bool = False) -> str:
    if neutral: return "🟡"
    return "🟢" if signal_ok else "🔴"


def build_call_message(
    ticker: str,
    call_type: str,
    conviction: str,
    yf_d: Dict,
    fund_row: Optional[Dict],
    sig: Dict,
    fv: Dict,
    sent: Dict,
    insider: Dict,
    hf: Dict,
    indic: Dict = None,
) -> str:
    cur      = yf_d.get("currency", "USD")
    name     = esc((yf_d.get("name") or ticker)[:32])
    sector   = esc(yf_d.get("sector") or "")
    industry = esc(yf_d.get("industry") or "")
    px       = yf_d.get("current_price") or 0

    conv_icon = {"HIGH CONVICTION": "🔥", "CONFIRMED": "✅", "SETUP": "👀"}.get(conviction, "•")
    dir_word  = "LONG" if call_type == "BUY" else "SHORT"
    dir_arrow = "📈" if call_type == "BUY" else "📉"

    score    = float((fund_row or {}).get("score") or (fund_row or {}).get("total_score") or 0)
    roic     = (fund_row or {}).get("roic_3y")
    rev_g    = (fund_row or {}).get("revenue_growth_3y")
    op_m     = (fund_row or {}).get("operating_margin")
    rating   = esc((fund_row or {}).get("rating") or "—")
    strengths  = list((fund_row or {}).get("strengths",  []) or [])
    weaknesses = list((fund_row or {}).get("weaknesses", []) or [])
    risks      = list((fund_row or {}).get("risks",      []) or [])

    pe_t   = yf_d.get("trailing_pe")
    pe_f   = yf_d.get("forward_pe")
    pb     = yf_d.get("pb")
    mktcap = yf_d.get("market_cap")

    fv_val    = fv.get("fair_value")
    upside    = fv.get("upside_pct")
    at_mean   = yf_d.get("analyst_target")
    at_low    = yf_d.get("analyst_low")
    at_high   = yf_d.get("analyst_high")
    hi52      = yf_d.get("52w_high")
    lo52      = yf_d.get("52w_low")

    entry_p  = sig.get("entry_price")
    stop_p   = sig.get("stop_loss")
    t1       = sig.get("t1") or sig.get("swing_target")
    t2       = sig.get("t2", t1)
    t3       = sig.get("t3", t1)
    rr       = sig.get("risk_reward", 0) or 0
    rr2      = sig.get("rr_t2", 0) or 0
    rr3      = sig.get("rr_t3", 0) or 0
    risk_pct = sig.get("risk_pct", 0) or 0
    vol      = sig.get("vol_confirmed", False)
    vol_r    = sig.get("vol_ratio", 0) or 0
    at_level = sig.get("at_level") or ""
    forming  = sig.get("forming", False)
    sw_lo    = sig.get("swing_low")
    sw_hi    = sig.get("swing_high")
    pattern  = esc(sig.get("name") or "")

    sent_label = sent.get("sentiment_label", "NEUTRAL")
    sent_score = sent.get("sentiment_score", 0) or 0
    headlines  = sent.get("top_headlines", [])
    n_news     = sent.get("news_count", 0)
    flagged    = sent.get("flagged", False)

    ins_signal = insider.get("signal", "NEUTRAL")
    ins_buys   = insider.get("buy_count", 0)
    ins_sells  = insider.get("sell_count", 0)
    ins_recent = insider.get("recent", [])
    hf_signal  = hf.get("net_signal", "UNKNOWN")
    top_hf     = hf.get("top_holders", [])

    if call_type == "BUY":
        t1_p = pct((t1-entry_p)/entry_p) if t1 and entry_p else "—"
        t2_p = pct((t2-entry_p)/entry_p) if t2 and entry_p else "—"
        t3_p = pct((t3-entry_p)/entry_p) if t3 and entry_p else "—"
        arr  = "▲"
    else:
        t1_p = pct((entry_p-t1)/entry_p) if t1 and entry_p else "—"
        t2_p = pct((entry_p-t2)/entry_p) if t2 and entry_p else "—"
        t3_p = pct((entry_p-t3)/entry_p) if t3 and entry_p else "—"
        arr  = "▼"

    # ── Valuation signal ──────────────────────────────────────────────────────
    val_ok = None
    if upside is not None:
        if call_type == "BUY":
            val_ok = upside >= 0.05   # at least 5% upside to fair value
        else:
            val_ok = upside <= -0.05  # overvalued by 5%+ for a short

    # ── Signal scorecard inputs ────────────────────────────────────────────────
    tech_ok  = conviction in ("HIGH CONVICTION", "CONFIRMED")
    fund_ok  = score >= MIN_FUND_SCORE
    news_ok  = (sent_label == "BULLISH" if call_type == "BUY"
                else sent_label == "BEARISH")
    news_neu = sent_label == "NEUTRAL"
    ins_ok   = (ins_signal == "BUYING" if call_type == "BUY"
                else ins_signal == "SELLING")
    ins_neu  = ins_signal in ("NEUTRAL", "MIXED", "NONE")
    hf_ok    = (hf_signal == "INCREASING" if call_type == "BUY"
                else hf_signal == "DECREASING")
    hf_neu   = hf_signal in ("STABLE", "UNKNOWN")

    green = sum([tech_ok, fund_ok, news_ok, ins_ok, hf_ok,
                 bool(val_ok) if val_ok is not None else False])

    L = "━" * 28
    lines = []

    # ══ HEADER ════════════════════════════════════════════════════════════════
    lines += [
        L,
        f"{conv_icon}  <b>{esc(conviction)} {dir_word}</b>  {dir_arrow}",
        L,
        f"<b>${esc(ticker)}</b>  ·  {name}",
        f"💼 {sector}  ·  {industry}",
        f"💰 Price: <b>{price(px, cur)}</b>  ·  Cap: {mktcap_str(mktcap)}",
        f"📅 {datetime.now().strftime('%b %d, %Y · %H:%M')}",
    ]

    # ══ BUSINESS QUALITY ══════════════════════════════════════════════════════
    lines += ["", f"━━ 📊 <b>BUSINESS QUALITY</b> ━━"]

    if score:
        lines.append(f"Score    <code>{bar(score)}</code>  <b>{score:.0f}/100</b>  {rating}")
    if roic is not None and not (isinstance(roic, float) and math.isnan(roic)):
        roic_pct = roic * 100
        lines.append(f"ROIC     <code>{bar(min(roic_pct,100),100)}</code>  <b>{roic_pct:+.1f}%</b>  (3Y avg)")
    if rev_g is not None and not (isinstance(rev_g, float) and math.isnan(rev_g)):
        rev_pct = rev_g * 100
        lines.append(f"Growth   <code>{bar(min(rev_pct,100),100)}</code>  <b>{rev_pct:+.1f}%</b>  (3Y avg)")
    if op_m is not None and not (isinstance(op_m, float) and math.isnan(op_m)):
        om_pct = op_m * 100
        lines.append(f"Margin   <code>{bar(min(om_pct,100),100)}</code>  <b>{om_pct:+.1f}%</b>  (TTM)")

    lines.append(f"PE {num(pe_t)}x  ·  Fwd PE {num(pe_f)}x  ·  P/B {num(pb)}")

    # ══ WHY ═══════════════════════════════════════════════════════════════════
    if strengths or weaknesses:
        lines += ["", "━━ 💡 <b>WHY</b> ━━"]
        for s in strengths[:2]:
            lines.append(f"  ✅ {esc(str(s)[:85])}")
        for w in weaknesses[:1]:
            lines.append(f"  ⚠️ {esc(str(w)[:85])}")
        for r in risks[:1]:
            lines.append(f"  🚨 {esc(str(r)[:85])}")

    # ══ TRADE SETUP ═══════════════════════════════════════════════════════════
    pat_score    = sig.get("pattern_score")
    form_conf    = sig.get("forming_confidence")
    form_trigger = sig.get("completion_trigger")
    form_move    = sig.get("expected_move_pct")
    form_bars    = sig.get("bars_to_trigger")

    form_tag = ""
    if forming and form_conf is not None:
        conf_bar = bar(form_conf, 100, 8)
        form_tag = f"  <i>[Forming  ·  <code>{conf_bar}</code>  <b>{form_conf}%</b> confidence]</i>"
    elif forming:
        form_tag = "  <i>[Forming — wait for confirmation]</i>"

    score_line = ""
    if pat_score is not None:
        score_bar = bar(pat_score, 100, 8)
        score_line = f"Quality  <code>{score_bar}</code>  <b>{pat_score}/100</b>"

    lines += [
        "",
        f"━━ ⚡ <b>TRADE SETUP</b> ━━{form_tag}",
        f"Pattern  <b>{pattern}</b>{'  🔊 Vol ×'+f'{vol_r:.1f}' if vol else '  🔇 Vol unconfirmed'}",
        score_line,
        f"{'Level    '+esc(at_level) if at_level else ''}",
        "",
        f"  {'LONG ' if call_type=='BUY' else 'SHORT'}  @  <code>{price(entry_p, cur)}</code>",
        f"  STOP   {'↑' if call_type=='SELL' else '↓'}  <code>{price(stop_p, cur)}</code>  ({risk_pct:.1f}% risk)",
        f"  {'─'*26}",
        f"  T1 {arr}  <code>{price(t1, cur)}</code>  ({t1_p})  <b>{rr:.1f}× R:R</b>",
        f"  T2 {arr}  <code>{price(t2, cur)}</code>  ({t2_p})  {rr2:.1f}× R:R",
        f"  T3 {arr}  <code>{price(t3, cur)}</code>  ({t3_p})  {rr3:.1f}× R:R",
    ]
    if forming and form_trigger:
        lines.append(f"  Trigger  <b>{price(form_trigger, cur)}</b>  ({'break above' if call_type=='BUY' else 'break below'})")
        if form_move:
            lines.append(f"  Expected move  <b>+{form_move:.1f}%</b> once triggered")
        if form_bars:
            lines.append(f"  Est. timing  ~{form_bars} bars to trigger level")
    elif sw_lo and sw_hi:
        lines.append(f"  Swing  {price(sw_lo,cur)} → {price(sw_hi,cur)}")
    lines.append(f"  Horizon: {'1–4 weeks' if not forming else 'wait for breakout'}")

    # ══ MULTI-TIMEFRAME & RELATIVE STRENGTH ═══════════════════════════════════
    setup_sc   = sig.get("setup_score")
    setup_gr   = sig.get("setup_grade")
    mtf_sc     = sig.get("mtf_score")
    mtf_ok     = sig.get("mtf_aligned")
    rs_m       = sig.get("rs_mansfield")
    rs_trend   = sig.get("rs_trend")
    rs_rank    = sig.get("rs_percentile")
    rvol_v     = sig.get("rvol")
    pos_shares = sig.get("position_shares")
    pos_risk   = sig.get("capital_at_risk")
    stop_src   = sig.get("stop_source")

    if any(v is not None for v in (setup_sc, mtf_sc, rs_m)):
        lines += ["", "━━ 🧭 <b>MULTI-TIMEFRAME &amp; RS</b> ━━"]
        if setup_sc is not None:
            lines.append(f"Setup    <code>{bar(setup_sc, 100, 8)}</code>  <b>{setup_sc}/100</b>  Grade <b>{esc(setup_gr or '—')}</b>")
        if mtf_sc is not None:
            mtf_dot = "🟢" if mtf_ok else "🔴"
            lines.append(f"Weekly   {mtf_dot} {'aligned' if mtf_ok else 'AGAINST setup'}  ({mtf_sc}/100)")
        if rs_m is not None:
            rs_dot = "🟢" if rs_m > 0 else ("🟡" if rs_m > -5 else "🔴")
            rank_txt = f"  ·  RS rank <b>{rs_rank}</b>/99" if rs_rank else ""
            lines.append(f"Rel Str  {rs_dot} Mansfield <b>{rs_m:+.1f}</b>  ({esc(rs_trend or '—')}){rank_txt}")
        if rvol_v is not None:
            lines.append(f"RVOL     ×{rvol_v:.1f} today's volume vs 20d avg")
        if pos_shares:
            lines.append(f"Size     <b>{pos_shares}</b> sh  ·  risk {price(pos_risk, cur)}  ·  stop via {esc(stop_src or 'pattern')}")

    # ══ VALUATION ═════════════════════════════════════════════════════════════
    val_label = "Undervalued" if (upside or 0) > 0 else "Overvalued"
    lines += [
        "",
        "━━ 💰 <b>VALUATION</b> ━━",
        f"Fair Value  <b>{price(fv_val, cur)}</b>  →  {val_label}  <b>{pct(upside)}</b>",
        f"Wall St     {price(at_mean, cur)}  (Range: {price(at_low,cur)} – {price(at_high,cur)})",
        f"52W         {price(lo52,cur)} – {price(hi52,cur)}",
    ]

    # ══ NEWS SENTIMENT ════════════════════════════════════════════════════════
    sent_emoji = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "➖"}.get(sent_label, "➖")
    lines += [
        "",
        f"━━ 📰 <b>NEWS</b>  ·  {sent_emoji} <b>{esc(sent_label)}</b>  ({n_news} articles, score {sent_score:+.2f}) ━━",
    ]
    if flagged:
        lines.append("  ⚠️  <i>Bearish news flagged — conviction downgraded one tier</i>")
    for h in headlines[:3]:
        if isinstance(h, dict):
            s     = h.get("sentiment", "neutral")
            title = esc(h.get("title", "")[:78])
            icon  = "🟢" if s == "positive" else "🔴" if s == "negative" else "⚪"
        else:
            title = esc(str(h)[:78])
            icon  = "⚪"
        lines.append(f"  {icon} {title}")

    # ══ SMART MONEY ═══════════════════════════════════════════════════════════
    ins_arrow = {"BUYING":"⬆️","SELLING":"⬇️","MIXED":"↔️","NEUTRAL":"➖","NONE":"➖"}.get(ins_signal,"➖")
    hf_arrow  = {"INCREASING":"⬆️","DECREASING":"⬇️","STABLE":"➖","UNKNOWN":"➖"}.get(hf_signal,"➖")

    lines += [
        "",
        "━━ 🧠 <b>SMART MONEY</b> ━━",
        f"Insiders     {ins_arrow} <b>{esc(ins_signal)}</b>  ({ins_buys} buys · {ins_sells} sells, {INSIDER_DAYS}d)",
    ]
    for r in ins_recent[:2]:
        d_icon = "⬆️" if r["direction"] == "BUY" else "⬇️"
        val_s  = f"  ${r['value']/1e6:.1f}M" if (r.get("value") or 0) > 1e4 else ""
        lines.append(f"  └ {d_icon} {esc(r['name'][:22])}  {r.get('shares',0):,} sh{val_s}  {r.get('date','')}")

    lines.append(f"Hedge Funds  {hf_arrow} <b>{esc(hf_signal)}</b>")
    for h in top_hf[:3]:
        chg = h.get("change_pct", 0) or 0
        ci  = "⬆️" if chg > 0.5 else "⬇️" if chg < -0.5 else "➖"
        lines.append(f"  └ {ci} {esc(h['name'][:28])}  {h.get('pct_held',0):.1f}%  ({chg:+.1f}% qtr)")

    # ══ SIGNAL SCORECARD ══════════════════════════════════════════════════════
    # Inline indicator context
    rsi_v      = sig.get("_rsi",   indic.get("rsi",   50) if indic else 50)
    above_200  = indic.get("above_200") if indic else None
    macd_hi_v  = indic.get("macd_hist", 0) if indic else 0
    bull_x     = indic.get("macd_bull_cross", False) if indic else False
    bear_x     = indic.get("macd_bear_cross", False) if indic else False
    ma200_v    = indic.get("ma200") if indic else None

    rsi_label  = f"RSI {rsi_v:.0f}  {'🔴 overbought' if rsi_v>70 else '🟢 oversold' if rsi_v<30 else '⚪ neutral'}"
    trend_label = ("🟢 Above 200MA" if above_200 else "🔴 Below 200MA" if above_200 is False else "—")
    macd_label  = ("🟢 Bull cross" if bull_x else "🔴 Bear cross" if bear_x
                   else ("🟢 Bullish" if macd_hi_v > 0 else "🔴 Bearish"))

    lines += [
        "",
        "━━ ✅ <b>SIGNAL SCORECARD</b> ━━",
        f"  {scorecard_dot(tech_ok)}  Technical   {esc(conviction)}  ·  {pattern}",
        f"  {scorecard_dot(fund_ok)}  Fundamental  Score {score:.0f}/100",
        f"  {scorecard_dot(val_ok is True, val_ok is None)}  Valuation    {pct(upside)} to fair value",
        f"  {scorecard_dot(news_ok, news_neu)}  News         {esc(sent_label)}  ({sent_score:+.2f})",
        f"  {scorecard_dot(ins_ok,  ins_neu)}  Insiders     {esc(ins_signal)}",
        f"  {scorecard_dot(hf_ok,   hf_neu)}  Hedge Funds  {esc(hf_signal)}",
        f"  {'─'*24}",
        f"  {conv_icon}  <b>{esc(conviction)}</b>  ·  {green}/6 signals aligned",
        "",
        f"  📡  {rsi_label}  ·  {trend_label}  ·  MACD: {macd_label}",
    ]

    # ══ TRADE PLAN (bottom) ════════════════════════════════════════════════════
    lines += [
        "",
        L,
        f"🎯  <b>{'BUY' if call_type=='BUY' else 'SHORT'}</b>  <code>{price(entry_p, cur)}</code>"
        f"  →  T1 <code>{price(t1, cur)}</code>  (<b>{rr:.1f}×</b>)",
        f"    Stop: <code>{price(stop_p, cur)}</code>  ·  Risk: {risk_pct:.1f}%  ·  Horizon: 1–4 wks",
        L,
    ]

    # Clean up blank lines from empty at_level
    return "\n".join(l for l in lines if l != "")


def build_scan_summary(confirmed: List[Dict], total_scanned: int, duration_s: float) -> str:
    now   = datetime.now()
    buys  = [c for c in confirmed if c["call_type"] == "BUY"]
    sells = [c for c in confirmed if c["call_type"] == "SELL"]
    hc    = [c for c in confirmed if c["conviction"] == "HIGH CONVICTION"]
    conf  = [c for c in confirmed if c["conviction"] == "CONFIRMED"]
    setup = [c for c in confirmed if c["conviction"] == "SETUP"]

    L = "━" * 28
    day = now.strftime("%A, %b %d %Y")
    tm  = now.strftime("%H:%M")

    lines = [
        L,
        "🔍  <b>STOCKCALLS DAILY SCAN</b>",
        L,
        f"📅  {day}  ·  {tm}",
        f"⚡  {total_scanned} quality stocks scanned  ·  {duration_s/60:.1f} min",
        "",
    ]

    total = len(confirmed)
    if total == 0:
        lines += [
            "😴  <b>No confirmed signals today</b>",
            "    Market may be consolidating — check back tomorrow.",
        ]
    else:
        lines.append(f"📊  <b>{total} SIGNAL{'S' if total>1 else ''} FOUND</b>")
        lines.append(f"    🔥 {len(hc)} High Conviction  ·  ✅ {len(conf)} Confirmed  ·  👀 {len(setup)} Setup")
        lines.append("")

        # Best call highlight
        best = next((c for c in confirmed if c["conviction"] == "HIGH CONVICTION"),
               next((c for c in confirmed if c["conviction"] == "CONFIRMED"), confirmed[0]))
        lines.append(f"⭐  <b>Top pick:  ${esc(best['ticker'])} {best['call_type']}</b>"
                     f"  ·  {esc(best['conviction'])}  ·  {best.get('rr',0):.1f}× R:R")
        lines.append("")

        def _summary_line(c):
            icon  = "🔥" if c["conviction"]=="HIGH CONVICTION" else "✅" if c["conviction"]=="CONFIRMED" else "👀"
            rr    = c.get("rr", 0) or 0
            grade = c.get("setup_grade")
            grade_txt = f"  ·  Setup <b>{esc(grade)}</b>" if grade else ""
            return (f"  {icon}  <b>${esc(c['ticker'])}</b>"
                    f"  ·  {esc(c['conviction'])}"
                    f"  ·  {esc(c['pattern'][:22])}"
                    f"  ·  {rr:.1f}× R:R{grade_txt}")

        if buys:
            lines.append(f"📈  <b>LONG  ({len(buys)})</b>")
            lines += [_summary_line(c) for c in buys]

        if sells:
            lines.append("")
            lines.append(f"📉  <b>SHORT  ({len(sells)})</b>")
            lines += [_summary_line(c) for c in sells]

    lines += ["", "📲  <i>Detailed reports follow below  ↓</i>", L]
    return "\n".join(lines)


# ── Main scan ─────────────────────────────────────────────────────────────────

def scan_and_alert(
    all_tickers: List[str],
    period: str = "2y",
    force_refund: bool = False,
    send_telegram: bool = True,
    min_conviction: str = "CONFIRMED",
    run_sentiment: bool = True,
) -> List[Dict]:

    if min_conviction == "HIGH CONVICTION":
        allowed = {"HIGH CONVICTION"}
    elif min_conviction == "CONFIRMED":
        allowed = {"HIGH CONVICTION", "CONFIRMED"}
    else:
        allowed = {"HIGH CONVICTION", "CONFIRMED", "SETUP"}

    t0 = time.time()
    tg = load_tg_config() if send_telegram else None
    if send_telegram and not tg:
        print("  [WARN] No config/telegram.json — run python telegram_notifier.py --setup")
        print("         Continuing without Telegram.")

    # ── Step 1: Fundamental universe (30-day per-ticker cache) ────────────────
    print(f"\n[1/4] Fundamental universe ({len(all_tickers)} tickers, {FUND_TTL_DAYS}-day cache)")
    universe  = update_universe(all_tickers, force=force_refund)
    passing   = get_strong_universe(universe)
    weak_cnt  = len(universe) - len(passing)
    print(f"  Strong universe: {len(passing)} tickers pass  |  {weak_cnt} skipped (weak/avoid)")

    # 2. Sentiment (batch, for passing tickers only)
    sentiment_data: Dict[str, Dict] = {}
    if run_sentiment:
        print(f"\n[2/4] News sentiment ({len(passing)} tickers) ...")
        try:
            sent_engine = SentimentEngine()
            sentiment_data = sent_engine.analyze_batch(passing)
        except Exception as e:
            print(f"  [WARN] Sentiment skipped: {e}")

    # 3. Technical scan
    print(f"\n[3/4] Technical scan ({len(passing)} tickers) ...")
    confirmed: List[Dict] = []
    total_with_signal = 0

    for i, ticker in enumerate(passing, 1):
        sys.stdout.write(f"\r  [{i:>3}/{len(passing)}] {ticker:<12} ", )
        sys.stdout.flush()

        best_bull, best_bear, patterns, struct, indic = run_technicals(ticker, period)
        has_signal = bool(best_bull or best_bear)
        if has_signal:
            total_with_signal += 1

        fund_row = universe.get(ticker)
        yf_d     = get_yf_fundamentals(ticker)
        px       = yf_d.get("current_price") or 0
        if px <= 0:
            continue

        sent = sentiment_data.get(ticker, {
            "sentiment_label": "NEUTRAL", "sentiment_score": 0,
            "top_headlines": [], "news_count": 0
        })

        fv = fair_value_estimate(yf_d, fund_row) if fund_row else {}

        # Resolve conflict: never send both BUY and SELL for the same ticker.
        # Keep the higher-conviction signal; break ties by vol-confirmed then R:R.
        if best_bull and best_bear:
            CONV_RANK = {"HIGH CONVICTION": 0, "CONFIRMED": 1, "SETUP": 2}
            bull_raw = swing_conviction(best_bull)
            bear_raw = ("HIGH CONVICTION"
                        if best_bear.get("vol_confirmed") and
                           best_bear.get("signal") == "SELL" and
                           best_bear.get("risk_reward", 0) >= 2.0
                        else "CONFIRMED"
                        if best_bear.get("signal") in ("SELL", "SELL?")
                        else "SETUP")
            br, bb = CONV_RANK[bear_raw], CONV_RANK[bull_raw]
            if bb < br:
                best_bear = None          # bull is stronger
            elif br < bb:
                best_bull = None          # bear is stronger
            else:
                # Same conviction tier: prefer vol-confirmed, then higher R:R
                bull_score = (best_bull.get("vol_confirmed", False),
                              best_bull.get("risk_reward", 0))
                bear_score = (best_bear.get("vol_confirmed", False),
                              best_bear.get("risk_reward", 0))
                if bull_score >= bear_score:
                    best_bear = None
                else:
                    best_bull = None

        for sig, call_type in [(best_bull, "BUY"), (best_bear, "SELL")]:
            if not sig:
                continue

            # Compute conviction
            if call_type == "BUY":
                raw_conv = swing_conviction(sig)
                conv, flagged = sentiment_adjust(raw_conv, sent.get("sentiment_label","NEUTRAL"), "SWING")
            else:
                raw_conv = ("HIGH CONVICTION" if sig.get("vol_confirmed") and
                             sig.get("signal") == "SELL" and sig.get("risk_reward",0) >= 2.0
                             else "CONFIRMED" if sig.get("signal") in ("SELL","SELL?") else "SETUP")
                # For sells: bullish news = headwind
                sl_sent = "BEARISH" if sent.get("sentiment_label") == "BULLISH" else \
                          "BULLISH" if sent.get("sentiment_label") == "BEARISH" else "NEUTRAL"
                conv, flagged = sentiment_adjust(raw_conv, sl_sent, "SWING")

            sent_with_flag = {**sent, "flagged": flagged}

            if conv not in allowed:
                continue

            # Log the find
            sys.stdout.write(f"→ {conv} {call_type}")
            sys.stdout.flush()

            # 4. Smart money (inline, per confirmed ticker)
            insider = fetch_insider_data(ticker, INSIDER_DAYS)
            hf      = fetch_hf_data(ticker)

            # Also use conviction for SELL signals (symmetry with BUY)
            if call_type == "SELL":
                raw_conv = swing_conviction(sig)
                conv, flagged = sentiment_adjust(raw_conv, sl_sent, "SWING")
                sent_with_flag = {**sent, "flagged": flagged}
                if conv not in allowed:
                    continue

            confirmed.append({
                "ticker":     ticker,
                "call_type":  call_type,
                "conviction": conv,
                "pattern":    sig.get("name", ""),
                "rr":         sig.get("risk_reward", 0),
                "pat_score":  sig.get("pattern_score"),
                # Payload for message building
                "_yf_d":     yf_d,
                "_fund_row": fund_row,
                "_sig":      sig,
                "_fv":       fv,
                "_sent":     sent_with_flag,
                "_insider":  insider,
                "_hf":       hf,
                "_indic":    indic,
            })

    print(f"\n  Done. {total_with_signal} tickers had a signal, {len(confirmed)} passed conviction filter.")

    # ── RS percentile post-pass (IBD-style 1-99, per benchmark group) ─────────
    if confirmed:
        rs_vals = {c["ticker"]: c["_sig"].get("rs_mansfield") for c in confirmed}
        groups  = {c["ticker"]: benchmark_for(c["ticker"]) for c in confirmed}
        ranks   = rs_percentile(rs_vals, groups)
        for c in confirmed:
            c["_sig"]["rs_percentile"] = ranks.get(c["ticker"])
            c["rs_percentile"] = ranks.get(c["ticker"])
            c["setup_score"] = c["_sig"].get("setup_score")
            c["setup_grade"] = c["_sig"].get("setup_grade")
        # Triage order: best setups first
        confirmed.sort(key=lambda c: -(c.get("setup_score") or 0))

    if not confirmed:
        print("  No confirmed calls found. Try --min-conviction SETUP to widen the filter.")
        if tg:
            tg_send(tg["token"], tg["chat_id"],
                    f"🔍 <b>StockCalls Scan Complete</b>\n"
                    f"Scanned {len(passing)} tickers, no {min_conviction}+ calls found today.\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        return []

    duration = time.time() - t0
    print(f"\n  Total scan time: {duration/60:.1f} min")

    # Build summary + send
    if tg:
        print(f"\n[4/4] Sending {len(confirmed)} call reports to Telegram ...")
        summary = build_scan_summary(confirmed, len(passing), duration)
        tg_send_long(tg["token"], tg["chat_id"], summary)
        time.sleep(1)

        for i, c in enumerate(confirmed, 1):
            print(f"  [{i}/{len(confirmed)}] {c['ticker']} {c['call_type']} {c['conviction']}")
            msg = build_call_message(
                ticker    = c["ticker"],
                call_type = c["call_type"],
                conviction= c["conviction"],
                yf_d      = c["_yf_d"],
                fund_row  = c["_fund_row"],
                sig       = c["_sig"],
                fv        = c["_fv"],
                sent      = c["_sent"],
                insider   = c["_insider"],
                hf        = c["_hf"],
                indic     = c.get("_indic"),
            )
            tg_send_long(tg["token"], tg["chat_id"], msg)
            time.sleep(0.8)

    # Save results JSON
    save_payload = []
    for c in confirmed:
        row = {k: v for k, v in c.items() if not k.startswith("_")}
        row["entry_price"] = c["_sig"].get("entry_price")
        row["stop_loss"]   = c["_sig"].get("stop_loss")
        row["t1"]          = c["_sig"].get("t1")
        row["t2"]          = c["_sig"].get("t2")
        row["t3"]          = c["_sig"].get("t3")
        row["fund_score"]  = (c["_fund_row"] or {}).get("total_score")
        row["upside_pct"]  = c["_fv"].get("upside_pct")
        row["sentiment"]   = c["_sent"].get("sentiment_label")
        row["insider_signal"] = c["_insider"].get("signal")
        row["hf_signal"]   = c["_hf"].get("net_signal")
        # Trader-grade context (additive)
        for k in ("mtf_score", "mtf_aligned", "rs_mansfield", "rs_trend",
                  "rvol", "trend_strength", "rsi_divergence",
                  "pattern_stop", "stop_source", "stop_pct",
                  "position_shares", "position_value", "capital_at_risk"):
            row[k] = c["_sig"].get(k)
        save_payload.append(row)

    os.makedirs("reports", exist_ok=True)
    out_path = f"reports/scan_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(), "calls": save_payload}, f, indent=2, default=str)
    print(f"\n  Saved to {out_path}")

    return confirmed


# ── Entry ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers",          type=str, default=None,
                   help="Comma-separated tickers (default: full S&P 500)")
    p.add_argument("--period",           type=str, default="2y")
    p.add_argument("--min-conviction",   type=str, default="CONFIRMED",
                   choices=["HIGH CONVICTION", "CONFIRMED", "SETUP"])
    p.add_argument("--no-telegram",      action="store_true")
    p.add_argument("--no-sentiment",     action="store_true")
    p.add_argument("--force-refund",     action="store_true",
                   help="Force re-screen ALL tickers for fundamentals, ignoring cache")
    p.add_argument("--show-universe",    action="store_true",
                   help="Print the current strong universe and exit")
    return p.parse_args()


def main():
    args = parse_args()

    if args.show_universe:
        universe = load_universe()
        if not universe:
            print("No universe cached yet. Run python scan_and_alert.py first.")
        else:
            print_universe_status(universe)
        return

    if args.tickers:
        all_tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        print(f"\nAd-hoc scan: {len(all_tickers)} tickers (conviction ≥ {args.min_conviction})")
    else:
        print(f"\nDaily scan — S&P 500 universe (conviction ≥ {args.min_conviction})")
        all_tickers = get_sp500_tickers()

    scan_and_alert(
        all_tickers    = all_tickers,
        period         = args.period,
        force_refund   = args.force_refund,
        send_telegram  = not args.no_telegram,
        min_conviction = args.min_conviction,
        run_sentiment  = not args.no_sentiment,
    )


if __name__ == "__main__":
    main()
