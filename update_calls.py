"""
update_calls.py
===============
Refreshes all ACTIVE/HOLD calls in the database:
  1. Fetches current price from yfinance
  2. Checks if stop was hit or target was reached
  3. Refreshes sentiment (uses 4-hour cache — fast)
  4. Calculates P&L since the call was given
  5. Writes a recommendation (HOLD / REVIEW / EXIT)
  6. Exports dashboard/portfolio.json

Usage:
    python update_calls.py            # update all active calls
    python update_calls.py --no-sentiment   # skip sentiment refresh
    python update_calls.py --close 42 195.00  # manually close call id=42 at $195
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import yfinance as yf

from stock_scanner.engine.calls_db import (
    close_call,
    export_portfolio_json,
    get_active_calls,
    init_db,
    update_call,
)

logging.basicConfig(level=logging.WARNING)

logger = logging.getLogger(__name__)

NOTIONAL = 10_000   # assumed $ per call for P&L display


# ── helpers ───────────────────────────────────────────────────────────────────

def fetch_pnl_curve(ticker: str, call_date: str, entry_price: float,
                    call_type: str) -> list[dict]:
    """Daily P&L % from call_date to today."""
    try:
        raw = yf.download(ticker, start=call_date, auto_adjust=True, progress=False)
        if raw.empty:
            return []
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        closes = raw["Close"].dropna()
        curve = []
        for dt, price in closes.items():
            px = float(price)
            pnl = ((entry_price - px) / entry_price if call_type == "SELL"
                   else (px - entry_price) / entry_price) * 100
            curve.append({"date": dt.strftime("%Y-%m-%d"), "pnl_pct": round(pnl, 2)})
        return curve
    except Exception:
        return []


def compute_portfolio_curve(curves: dict[str, list[dict]]) -> list[dict]:
    """Average daily P&L across all calls, aligned by date."""
    date_vals: dict[str, list] = defaultdict(list)
    for curve in curves.values():
        for pt in curve:
            date_vals[pt["date"]].append(pt["pnl_pct"])
    combined = [
        {"date": d, "pnl_pct": round(sum(v) / len(v), 2)}
        for d, v in sorted(date_vals.items())
        if v
    ]
    return combined


def fetch_price(ticker: str) -> float | None:
    try:
        info = yf.Ticker(ticker).fast_info
        return float(info.last_price or info.previous_close or 0) or None
    except Exception:
        return None


def calc_pnl(call_type: str, entry: float, current: float):
    if not entry or not current:
        return 0.0, 0.0
    pct = (entry - current) / entry if call_type == "SELL" else (current - entry) / entry
    return round(pct, 6), round(pct * NOTIONAL, 2)


def determine_status(entry: float, stop: float | None,
                     t1: float | None, current: float,
                     pnl_pct: float, sentiment_label: str,
                     call_type: str) -> str:
    """
    Returns BUY / HOLD / SELL.
    BUY  = still open, good opportunity to add
    HOLD = open, just keep holding
    SELL = exit the position
    """
    # Stop hit → always SELL
    if stop and current <= stop:
        return "SELL"

    # T1 target reached → SELL (take profits, re-enter later if needed)
    if t1 and current >= t1:
        return "SELL"

    # Bearish sentiment AND in drawdown → SELL (sentiment turned against us)
    if sentiment_label == "BEARISH" and pnl_pct < -0.03:
        return "SELL"

    # Small pullback, still above stop, thesis intact → good to add (BUY more)
    if stop and current > stop:
        dist_to_stop = (current - stop) / current
        if 0 < dist_to_stop < 0.05 and pnl_pct > -0.05 and sentiment_label != "BEARISH":
            return "BUY"

    # Default: keep holding
    return "HOLD"


def build_notes(call: dict, current: float, status: str,
                pnl_pct: float, sentiment_label: str) -> tuple:
    """Returns (notes_str, recommendation_str)."""
    _entry    = call.get("entry_price") or current
    stop     = call.get("stop_loss")
    t1       = call.get("t1")
    pct_disp = f"{pnl_pct*100:+.1f}%"
    parts    = []

    if status == "SELL":
        if stop and current <= stop:
            notes = f"Stop loss hit at {current:.2f}. Position closed at {pct_disp}."
            rec   = "SELL — stop triggered. Exit the position immediately."
        elif t1 and current >= t1:
            notes = f"T1 target {t1:.2f} reached at {current:.2f}. Up {pct_disp}."
            rec   = "SELL — T1 target hit. Take profits. Re-enter on next BUY signal."
        else:
            notes = f"Sentiment turned bearish while in drawdown ({pct_disp}). Thesis weakened."
            rec   = "SELL — bearish news in drawdown. Cut the position."
        return notes, rec

    if status == "BUY":
        notes = f"Pulled back to good add zone ({pct_disp}). Above stop, thesis intact."
        rec   = f"BUY MORE — good add opportunity near support. Stop at {stop:.2f}." if stop else "BUY MORE — add to position."
        return notes, rec

    # HOLD
    if pnl_pct >= 0.15:
        parts.append(f"Strong run {pct_disp} — tighten stop to protect gains")
    elif pnl_pct >= 0.05:
        parts.append(f"Running well {pct_disp} — hold for T2/T3")
    elif pnl_pct >= 0:
        parts.append(f"Slightly positive {pct_disp} — hold for target")
    else:
        if stop:
            dist = (current - stop) / current * 100
            parts.append(f"Drawdown {pct_disp} — stop at {stop:.2f} ({dist:.1f}% away)")
        else:
            parts.append(f"Drawdown {pct_disp} — monitor fundamentals")

    if sentiment_label == "BULLISH":
        parts.append("News sentiment bullish — supports the thesis")
    elif sentiment_label == "BEARISH":
        parts.append("News sentiment bearish — watch closely")

    notes = " | ".join(parts)

    if pnl_pct >= 0.10 and t1 and current < t1:
        rec = f"HOLD — up {pct_disp}, still targeting {t1:.2f}. Trail stop."
    elif pnl_pct < 0 and stop:
        rec = f"HOLD — in drawdown, stop at {stop:.2f}. Do not average down."
    elif sentiment_label == "BEARISH":
        rec = "HOLD cautiously — bearish news. Tighten stop if possible."
    else:
        rec = "HOLD — thesis intact."

    return notes, rec


# ── main refresh ──────────────────────────────────────────────────────────────

def refresh_all(run_sentiment: bool = True):
    init_db()
    calls = get_active_calls()
    if not calls:
        logger.info("No active calls in database.")
        return

    logger.info(f"\nRefreshing {len(calls)} active calls ...\n")

    # Batch sentiment refresh (uses 4-hour cache so usually instant)
    sentiment_map = {}
    if run_sentiment:
        tickers = list({c["ticker"] for c in calls})
        try:
            from stock_scanner.engine.sentiment import SentimentEngine
            engine = SentimentEngine()
            sentiment_map = engine.analyze_batch(tickers)
        except Exception as e:
            logger.warning(f"  Sentiment refresh skipped: {e}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for call in calls:
        ticker    = call["ticker"]
        call_id   = call["id"]
        call_type = call.get("call_type", "SWING")
        entry     = call.get("entry_price")

        current = fetch_price(ticker)
        if current is None:
            logger.warning(f"  {ticker:<12}  Could not fetch price — skipping")
            continue

        pnl_pct, pnl_abs = calc_pnl(call_type, entry, current)

        sent_data     = sentiment_map.get(ticker, {})
        sent_label    = sent_data.get("sentiment_label", call.get("sentiment_label", "NEUTRAL"))

        status = determine_status(
            entry=entry or current,
            stop=call.get("stop_loss"),
            t1=call.get("t1"),
            current=current,
            pnl_pct=pnl_pct,
            sentiment_label=sent_label,
            call_type=call_type,
        )

        notes, rec = build_notes(call, current, status, pnl_pct, sent_label)

        update_call(
            call_id        = call_id,
            current_price  = current,
            status         = status,
            pnl_pct        = pnl_pct,
            pnl_abs        = pnl_abs,
            notes          = notes,
            recommendation = rec,
            sentiment_label= sent_label,
            exit_price     = current if status == "SELL" else None,
        )

        f"{pnl_pct*100:+.1f}%"

    # Build P&L curves for active calls
    logger.info("\n  Building P&L curves ...")
    active_after = get_active_calls()
    equity_curves: dict[str, list] = {}
    for call in active_after:
        ticker     = call["ticker"]
        call_date  = (call.get("call_date") or "")[:10]
        entry      = call.get("entry_price")
        call_type  = call.get("call_type", "SWING")
        if entry and call_date:
            curve = fetch_pnl_curve(ticker, call_date, entry, call_type)
            if curve:
                # Use ticker+type as key to avoid collisions (e.g., MSFT SWING vs LONG-TERM)
                key = f"{ticker} ({call_type[:2]})"
                equity_curves[key] = curve
                logger.debug(f"    {key}: {len(curve)} days")

    portfolio_curve = compute_portfolio_curve(equity_curves)

    # Export to dashboard
    path = export_portfolio_json(
        equity_curves=equity_curves,
        portfolio_curve=portfolio_curve,
    )
    logger.info(f"\n  Portfolio exported → {path}")
    logger.info(f"  Updated at {now_str}\n")


# ── entry point ───────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--no-sentiment", action="store_true",
                   help="Skip sentiment refresh")
    p.add_argument("--close", nargs=2, metavar=("CALL_ID", "EXIT_PRICE"),
                   help="Manually close a call: --close 42 195.00")
    return p.parse_args()


def main():
    args = parse_args()

    if args.close:
        call_id    = int(args.close[0])
        exit_price = float(args.close[1])
        close_call(call_id, exit_price)
        logger.info(f"  Call #{call_id} closed at {exit_price:.2f}")
        export_portfolio_json()
        return

    refresh_all(run_sentiment=not args.no_sentiment)


if __name__ == "__main__":
    main()
