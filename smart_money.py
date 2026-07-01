"""
smart_money.py
==============
Fetches "smart money" signals for a set of tickers:

  INSIDERS    — Recent Form 4 filings (corporate officers/directors)
                Source: yfinance insider_transactions
  CONGRESS    — House & Senate stock disclosure filings (last 90 days)
                Source: house-stock-watcher & senate-stock-watcher (public S3)
  HEDGE FUNDS — Top institutional holders & recent % change in position
                Source: yfinance institutional_holders
  NEWS        — Top headlines + sentiment (from existing equity_calls.json)

Usage:
    python smart_money.py
    python smart_money.py --tickers "AAPL,MSFT,NVDA,RELIANCE.NS,INFY.NS"
    python smart_money.py --days 60   # Congress/insider lookback window

Output:
    dashboard/smart_money.json   (read by dashboard)
"""

import os, sys, json, argparse, logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("smart_money")

DEFAULT_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "NVDA", "META", "AMZN", "TSLA",
    "JPM", "V", "MA", "WMT", "KO", "JNJ", "LLY", "BAC",
    "RELIANCE.NS", "INFY.NS", "TCS.NS", "HDFCBANK.NS",
]

CONGRESS_LOOKBACK_DAYS = 90
INSIDER_LOOKBACK_DAYS  = 60
REQUEST_TIMEOUT        = 20   # seconds

# Congressional disclosure data — public GitHub mirrors (maintained by the community)
# Primary: raw GitHub exports from house/senate stock watcher projects
# Fallback: official government portals (web only, no machine-readable API)
CONGRESS_SOURCES = [
    # GitHub-hosted mirrors — usually the most up-to-date free source
    ("House",   "https://raw.githubusercontent.com/AlejandroHerr/house-stock-watcher-data/main/data/all_transactions.json"),
    ("Senate",  "https://raw.githubusercontent.com/AlejandroHerr/senate-stock-watcher-data/main/aggregate/all_transactions.json"),
    # S3 buckets (original source — may be inaccessible)
    ("House",   "https://house-stock-watcher-data.s3.amazonaws.com/data/all_transactions.json"),
    ("Senate",  "https://senate-stock-watcher-data.s3.amazonaws.com/aggregate/all_transactions.json"),
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _safe_date(val) -> Optional[datetime]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return pd.to_datetime(val, errors="coerce").to_pydatetime()
    except Exception:
        return None


def _ticker_variants(ticker: str) -> List[str]:
    """Return possible ticker strings as they appear in congress disclosure data."""
    base = ticker.replace(".NS", "").replace(".BO", "").upper()
    return [base, f"${base}", ticker.upper()]


def _amount_sort_key(amount_str: str) -> int:
    """Convert '$1,001 - $15,000' style strings to a sortable integer (lower bound)."""
    if not amount_str:
        return 0
    import re
    nums = re.findall(r"[\d,]+", amount_str.replace(",", ""))
    try:
        return int(nums[0]) if nums else 0
    except (ValueError, IndexError):
        return 0


# ── Congress data ──────────────────────────────────────────────────────────────

def fetch_congress_data(lookback_days: int) -> Dict[str, List[Dict]]:
    """
    Fetch House + Senate disclosure filings and return {ticker: [trade, ...]}
    for trades within the lookback window.
    Tries multiple sources in priority order; gracefully skips if all fail.
    """
    cutoff = datetime.now() - timedelta(days=lookback_days)
    result: Dict[str, List[Dict]] = {}
    fetched_chambers: set = set()

    for chamber, url in CONGRESS_SOURCES:
        if chamber in fetched_chambers:
            continue
        print(f"  Fetching {chamber} disclosure data ...", end=" ", flush=True)
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                print(f"EMPTY")
                continue
            print(f"OK ({len(data):,} records)")
            fetched_chambers.add(chamber)
        except Exception as e:
            print(f"FAILED")
            continue

        for row in data:
            ticker_raw = str(row.get("ticker") or "").strip().upper().lstrip("$")
            if not ticker_raw or ticker_raw in ("N/A", "--", ""):
                continue

            tx_date = _safe_date(row.get("transaction_date") or row.get("disclosure_date"))
            if tx_date is None or tx_date < cutoff:
                continue

            tx_type = str(row.get("type") or "").lower()
            if "purchase" in tx_type:
                direction = "BUY"
            elif "sale" in tx_type or "sell" in tx_type:
                direction = "SELL"
            elif "exchange" in tx_type:
                direction = "OTHER"
            else:
                continue

            member = (row.get("representative") or row.get("senator") or "Unknown").strip()
            amount = str(row.get("amount") or "").strip()
            asset  = str(row.get("asset_description") or "").strip()[:60]

            trade = {
                "member":    member,
                "chamber":   chamber,
                "direction": direction,
                "amount":    amount,
                "date":      tx_date.strftime("%Y-%m-%d"),
                "asset":     asset,
                "amount_num": _amount_sort_key(amount),
            }

            result.setdefault(ticker_raw, []).append(trade)

    return result


# ── Insider data ───────────────────────────────────────────────────────────────

def fetch_insider_data(ticker: str, lookback_days: int) -> Dict[str, Any]:
    """Fetch recent insider transactions from yfinance."""
    cutoff = datetime.now() - timedelta(days=lookback_days)
    try:
        t = yf.Ticker(ticker)
        df = t.insider_transactions
        if df is None or df.empty:
            return {"signal": "NEUTRAL", "recent": [], "buy_count": 0, "sell_count": 0, "net_shares": 0}
    except Exception:
        return {"signal": "NEUTRAL", "recent": [], "buy_count": 0, "sell_count": 0, "net_shares": 0}

    recent = []
    buy_shares = sell_shares = 0
    buy_count = sell_count = 0

    for _, row in df.iterrows():
        tx_date = _safe_date(row.get("Start Date") or row.get("Date") or row.get("startDate"))
        if tx_date and tx_date < cutoff:
            continue

        # yfinance puts trade info in `Text` column ("Sale at price X" or "Purchase at price X")
        # The `Transaction` column is often empty — check both
        tx_text = (str(row.get("Text") or "") + " " +
                   str(row.get("Transaction") or "")).lower()
        shares  = int(row.get("Shares") or row.get("shares") or 0)
        value   = float(row.get("Value") or row.get("value") or 0)
        name    = str(row.get("Insider") or row.get("insider") or row.get("Name") or "").strip()
        role    = str(row.get("Position") or row.get("Relationship") or row.get("relationship") or "").strip()

        if "sale" in tx_text or "sold" in tx_text:
            direction = "SELL"
            sell_shares += abs(shares)
            sell_count  += 1
        elif "purchase" in tx_text or "buy" in tx_text or "acquired" in tx_text or "acquisition" in tx_text:
            direction = "BUY"
            buy_shares += abs(shares)
            buy_count  += 1
        else:
            direction = "OTHER"

        if direction in ("BUY", "SELL"):
            recent.append({
                "name":      name[:40],
                "role":      role[:40],
                "direction": direction,
                "shares":    abs(shares),
                "value":     round(value, 0),
                "date":      tx_date.strftime("%Y-%m-%d") if tx_date else "—",
            })

    recent.sort(key=lambda x: x["date"], reverse=True)
    recent = recent[:10]

    net = buy_shares - sell_shares
    if buy_count == 0 and sell_count == 0:
        signal = "NEUTRAL"
    elif buy_count > sell_count * 1.5:
        signal = "BUYING"
    elif sell_count > buy_count * 1.5:
        signal = "SELLING"
    else:
        signal = "MIXED"

    return {
        "signal":      signal,
        "recent":      recent,
        "buy_count":   buy_count,
        "sell_count":  sell_count,
        "net_shares":  net,
    }


# ── Hedge fund data ────────────────────────────────────────────────────────────

def fetch_hf_data(ticker: str) -> Dict[str, Any]:
    """Fetch top institutional holders from yfinance (13F data)."""
    try:
        t = yf.Ticker(ticker)
        df = t.institutional_holders
        if df is None or df.empty:
            return {"top_holders": [], "net_signal": "UNKNOWN"}
    except Exception:
        return {"top_holders": [], "net_signal": "UNKNOWN"}

    holders = []
    for _, row in df.iterrows():
        name   = str(row.get("Holder") or "").strip()
        shares = int(row.get("Shares") or 0)
        # yfinance column names changed: pctHeld (0.0779) and pctChange (-0.0086)
        pct_raw = float(row.get("pctHeld") or row.get("% Out") or 0)
        pct     = pct_raw * 100 if pct_raw < 1 else pct_raw   # normalize to %
        chg_raw = float(row.get("pctChange") or row.get("% Change") or 0)
        # yfinance stores as decimal fraction: 0.0296 = +2.96%, -0.0086 = -0.86%
        chg = max(-99.0, min(99.0, chg_raw * 100))
        date_r  = _safe_date(row.get("Date Reported") or row.get("dateReported"))

        holders.append({
            "name":        name[:45],
            "shares":      shares,
            "pct_held":    round(pct, 2),
            "change_pct":  round(chg, 2),
            "date_reported": date_r.strftime("%Y-%m-%d") if date_r else "—",
        })

    holders = holders[:8]

    # Net signal from recent changes (change_pct is now in % form, e.g. +1.5, -0.8)
    increasing = sum(1 for h in holders if h["change_pct"] > 0.5)
    decreasing = sum(1 for h in holders if h["change_pct"] < -0.5)
    if increasing > decreasing * 1.5:
        net_signal = "INCREASING"
    elif decreasing > increasing * 1.5:
        net_signal = "DECREASING"
    else:
        net_signal = "STABLE"

    return {"top_holders": holders, "net_signal": net_signal}


# ── News summary ───────────────────────────────────────────────────────────────

def load_news_from_equity_calls(tickers: List[str]) -> Dict[str, Dict]:
    """Pull latest news/sentiment from existing equity_calls.json to avoid re-running FinBERT."""
    news_map: Dict[str, Dict] = {}
    paths = ["dashboard/equity_calls.json", "reports/equity_calls.json"]
    for path in paths:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    calls = json.load(f)
                for call in calls.get("long_term_calls", []) + calls.get("swing_calls", []):
                    t = call.get("ticker")
                    if t and t not in news_map:
                        news_map[t] = {
                            "sentiment_label": call.get("sentiment_label", "NEUTRAL"),
                            "sentiment_score": call.get("sentiment_score", 0),
                            "top_headlines":   call.get("top_headlines", []),
                            "news_count":      call.get("news_count", 0),
                        }
            except Exception:
                pass
            break

    # For tickers not in calls file, fetch direct from yfinance
    missing = [t for t in tickers if t not in news_map]
    if missing:
        print(f"  Fetching news for {len(missing)} tickers without sentiment cache ...")
        for t in missing:
            try:
                info = yf.Ticker(t)
                raw_news = info.news or []
                headlines = [n.get("content", {}).get("title") or n.get("title", "")
                             for n in raw_news[:5] if n]
                headlines = [h for h in headlines if h]
                news_map[t] = {
                    "sentiment_label": "NEUTRAL",
                    "sentiment_score": 0,
                    "top_headlines":   headlines,
                    "news_count":      len(raw_news),
                }
            except Exception:
                news_map[t] = {"sentiment_label": "NEUTRAL", "sentiment_score": 0,
                                "top_headlines": [], "news_count": 0}

    return news_map


# ── main aggregator ────────────────────────────────────────────────────────────

def generate_smart_money(tickers: List[str], lookback_days: int) -> Dict:
    print(f"\nFetching smart money data for {len(tickers)} tickers (lookback={lookback_days}d)\n")

    # 1. Congress (one batch call for all tickers)
    congress_all = fetch_congress_data(lookback_days)

    # 2. News from existing calls file
    print("  Loading news/sentiment from equity_calls.json ...")
    news_all = load_news_from_equity_calls(tickers)

    # 3. Per-ticker: insiders + hedge funds
    ticker_data: Dict[str, Dict] = {}

    for ticker in tickers:
        print(f"  {ticker}: insiders ...", end=" ", flush=True)
        insider = fetch_insider_data(ticker, INSIDER_LOOKBACK_DAYS)
        print(f"({insider['signal']})  hedge funds ...", end=" ", flush=True)
        hf      = fetch_hf_data(ticker)
        print(f"({hf['net_signal']})")

        # Match congressional trades for this ticker
        base_ticker = ticker.replace(".NS", "").replace(".BO", "").upper()
        cong_trades = congress_all.get(base_ticker, [])
        buy_cong  = [t for t in cong_trades if t["direction"] == "BUY"]
        sell_cong = [t for t in cong_trades if t["direction"] == "SELL"]

        if len(buy_cong) > len(sell_cong) * 1.5 and buy_cong:
            cong_signal = "BUYING"
        elif len(sell_cong) > len(buy_cong) * 1.5 and sell_cong:
            cong_signal = "SELLING"
        elif buy_cong or sell_cong:
            cong_signal = "MIXED"
        else:
            cong_signal = "NONE"

        # Sort by amount (largest first) then by date
        cong_trades_sorted = sorted(cong_trades, key=lambda x: (-x["amount_num"], x["date"]), reverse=False)
        cong_trades_sorted.sort(key=lambda x: x["date"], reverse=True)

        news = news_all.get(ticker, {"sentiment_label": "NEUTRAL", "sentiment_score": 0,
                                      "top_headlines": [], "news_count": 0})

        # Overall smart money verdict
        signals = []
        if insider["signal"] in ("BUYING",):   signals.append("BUY")
        if insider["signal"] in ("SELLING",):  signals.append("SELL")
        if cong_signal in ("BUYING",):         signals.append("BUY")
        if cong_signal in ("SELLING",):        signals.append("SELL")
        if hf["net_signal"] == "INCREASING":   signals.append("BUY")
        if hf["net_signal"] == "DECREASING":   signals.append("SELL")

        buy_votes  = signals.count("BUY")
        sell_votes = signals.count("SELL")

        if buy_votes > sell_votes:
            overall = "BULLISH"
        elif sell_votes > buy_votes:
            overall = "BEARISH"
        elif buy_votes > 0 or sell_votes > 0:
            overall = "MIXED"
        else:
            overall = "NEUTRAL"

        ticker_data[ticker] = {
            "ticker":  ticker,
            "overall": overall,
            "insiders": {
                "signal":     insider["signal"],
                "buy_count":  insider["buy_count"],
                "sell_count": insider["sell_count"],
                "net_shares": insider["net_shares"],
                "recent":     insider["recent"][:6],
            },
            "congress": {
                "signal":     cong_signal,
                "buy_count":  len(buy_cong),
                "sell_count": len(sell_cong),
                "recent":     cong_trades_sorted[:8],
            },
            "hedge_funds": {
                "net_signal":  hf["net_signal"],
                "top_holders": hf["top_holders"],
            },
            "news": {
                "sentiment_label": news["sentiment_label"],
                "sentiment_score": round(float(news["sentiment_score"] or 0), 3),
                "top_headlines":   news["top_headlines"][:5],
                "news_count":      news["news_count"],
            },
        }

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": lookback_days,
        "tickers": ticker_data,
    }


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=str, default=None)
    p.add_argument("--days",    type=int, default=CONGRESS_LOOKBACK_DAYS,
                   help="Lookback window in days for congress + insider data (default 90)")
    return p.parse_args()


def main():
    args = parse_args()
    tickers = ([t.strip().upper() for t in args.tickers.split(",") if t.strip()]
               if args.tickers else DEFAULT_TICKERS)

    result = generate_smart_money(tickers, args.days)

    os.makedirs("dashboard", exist_ok=True)
    out_path = "dashboard/smart_money.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\n  Saved to {out_path}")

    # Print quick summary
    print(f"\n  {'Ticker':<12} {'Overall':<10} {'Insiders':<10} {'Congress':<10} {'HedgeFunds':<12} {'News'}")
    print("  " + "-" * 72)
    for ticker, d in result["tickers"].items():
        print(f"  {ticker:<12} {d['overall']:<10} {d['insiders']['signal']:<10} "
              f"{d['congress']['signal']:<10} {d['hedge_funds']['net_signal']:<12} "
              f"{d['news']['sentiment_label']}")


if __name__ == "__main__":
    main()
