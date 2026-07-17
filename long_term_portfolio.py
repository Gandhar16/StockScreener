"""
long_term_portfolio.py
======================
Long-term portfolio management system driven purely by quarterly
fundamental re-screening.  No price-based stop losses — exit is
triggered only when the fundamental thesis breaks.

Commands:
    python long_term_portfolio.py --scan              (default)
    python long_term_portfolio.py --add TICKER
    python long_term_portfolio.py --add TICKER --tranche 2
    python long_term_portfolio.py --rescreen
    python long_term_portfolio.py --rescreen --force-refresh
    python long_term_portfolio.py --status
    python long_term_portfolio.py --exit TICKER
    python long_term_portfolio.py --capital 150000
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime

# Force UTF-8 output on Windows so currency symbols don't crash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yfinance as yf

from generate_calls import (
    DEFAULT_US,
    MIN_FUND_SCORE,
    currency_sym,
    fair_value_estimate,
    get_yf_fundamentals,
    load_or_refresh_fundamentals,
)

# ── constants ──────────────────────────────────────────────────────────────────

PORTFOLIO_PATH      = "reports/lt_portfolio.json"
POSITION_PCT        = 0.08        # 8% of total capital per position
MAX_TRANCHES        = 3
DATE_FMT            = "%Y-%m-%d"

# Exit/trim thresholds
SCORE_EXIT          = 50.0        # thesis broken — exit immediately
SCORE_WATCH_LO      = 50.0
SCORE_WATCH_HI      = 58.0        # 50–58 → watch, don't add tranches
DE_EXIT_THRESHOLD   = 3.0        # D/E ratio > 3 → exit
FV_TRIM_PCT         = 1.30        # price > 130% of fair value → trim
FV_EXIT_PCT         = 1.60        # price > 160% of fair value → exit
SCORE_HOLD          = 60.0        # ≥ 60 and price < FV → hold / add tranche
MAX_POSITIONS       = 12          # maximum simultaneous positions

# ── portfolio file helpers ────────────────────────────────────────────────────

def _empty_portfolio(total_capital: float) -> dict:
    return {
        "meta": {
            "total_capital": total_capital,
            "cash": total_capital,
            "last_rescreen": None,
            "created": datetime.now().strftime(DATE_FMT),
        },
        "holdings": {}
    }


def load_portfolio() -> dict:
    if os.path.exists(PORTFOLIO_PATH):
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            return json.load(f)
    return _empty_portfolio(100_000.0)


def save_portfolio(port: dict) -> None:
    os.makedirs("reports", exist_ok=True)
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(port, f, indent=2, default=str)


# ── live price helper ─────────────────────────────────────────────────────────

def get_live_price(ticker: str) -> float | None:
    """Fetch current price via yfinance."""
    try:
        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price:
            return float(price)
        # fallback: last close from history
        hist = yf.download(ticker, period="2d", progress=False, auto_adjust=True)
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ── screening helpers ─────────────────────────────────────────────────────────

def _apply_rescreen_rules(ticker: str, holding: dict,
                           fund_row: dict | None,
                           yf_d: dict,
                           price: float) -> dict:
    """
    Apply exit/trim/watch/hold rules from the fund_row and live price.
    Returns an updated copy of the holding dict.
    """
    h = dict(holding)
    prev_score = h.get("fund_score")
    flags: list[str] = []
    status = "HOLD"

    if fund_row is None:
        flags.append("NO_FUND_DATA")
        h["flags"] = flags
        h["thesis_status"] = "WATCH"
        return h

    score = float(fund_row.get("total_score", 0))
    rev_growth = fund_row.get("revenue_growth_3y")   # may be float or None
    de_ratio   = fund_row.get("debt_to_equity")       # may be float or None

    # Fair value
    fv_data  = fair_value_estimate(yf_d, fund_row)
    fair_val = fv_data.get("fair_value")

    # --- Rule evaluation (priority order) ------------------------------------

    # 1. D/E spike
    if de_ratio is not None and not math.isnan(float(de_ratio if de_ratio else 0)):
        if float(de_ratio) > DE_EXIT_THRESHOLD:
            status = "EXIT"
            flags.append(f"D/E={de_ratio:.1f} > {DE_EXIT_THRESHOLD}")

    # 2. Score drop — thesis broken
    if score < SCORE_EXIT:
        status = "EXIT"
        flags.append(f"score {score:.1f} < {SCORE_EXIT}")

    # 3. Score watch band
    elif SCORE_WATCH_LO <= score < SCORE_WATCH_HI and status != "EXIT":
        status = "WATCH"
        flags.append(f"score {score:.1f} in watch band")

    # 4. Revenue growth turned negative
    if rev_growth is not None:
        try:
            rg = float(rev_growth)
            if rg < 0:
                if status == "HOLD":
                    status = "WATCH"
                flags.append(f"rev_growth_3y={rg:.1%}")
        except (ValueError, TypeError):
            pass

    # 5. Price vs fair value (only when exit not already triggered)
    if fair_val and price > 0 and status != "EXIT":
        ratio = price / fair_val
        if ratio > FV_EXIT_PCT:
            status = "EXIT"
            flags.append(f"price {ratio:.0%} of FV (fully priced)")
        elif ratio > FV_TRIM_PCT:
            status = "TRIM"
            flags.append(f"price {ratio:.0%} of FV (extended)")

    # 6. Default: score intact
    if status == "HOLD" and score >= SCORE_HOLD and fair_val and price < fair_val:
        status = "HOLD"   # explicitly re-confirm

    h["fund_score_prev"] = prev_score
    h["fund_score"]      = round(score, 1)
    h["fair_value"]      = fair_val
    h["thesis_status"]   = status
    h["flags"]           = flags
    h["last_screened"]   = datetime.now().strftime(DATE_FMT)

    return h


# ── --scan ────────────────────────────────────────────────────────────────────

def _build_candidates(force_refresh: bool = False) -> list[dict]:
    """Return sorted list of LT candidates (score >= MIN_FUND_SCORE) with live prices."""
    fund_data = load_or_refresh_fundamentals(DEFAULT_US, force=force_refresh)
    candidates = []
    for ticker, row in fund_data.items():
        score  = float(row.get("total_score", 0))
        rating = str(row.get("rating", ""))
        if score >= MIN_FUND_SCORE and "Avoid" not in rating:
            yf_d  = get_yf_fundamentals(ticker)
            price = yf_d.get("current_price") or 0
            if price <= 0:
                continue
            fv_data  = fair_value_estimate(yf_d, row)
            candidates.append({
                "ticker":   ticker,
                "name":     yf_d.get("name", ticker),
                "score":    round(score, 1),
                "price":    price,
                "fair_val": fv_data.get("fair_value"),
                "upside":   fv_data.get("upside_pct"),
                "pe":       yf_d.get("trailing_pe") or yf_d.get("forward_pe"),
                "currency": yf_d.get("currency", "USD"),
                # V3 quality cross-checks (None when data was unavailable)
                "piotroski_f":   row.get("piotroski_f"),
                "piotroski_max": row.get("piotroski_max"),
                "accruals_ratio": row.get("accruals_ratio"),
                "peer_val_pct":  row.get("peer_valuation_percentile"),
            })
    candidates.sort(key=lambda x: -x["score"])
    return candidates


def cmd_scan(args):
    candidates = _build_candidates(getattr(args, "force_refresh", False))


    port     = load_portfolio()
    holdings = port.get("holdings", {})

    for _i, c in enumerate(candidates, 1):
        sym      = currency_sym(c["currency"])
        f"{sym}{c['price']:,.2f}"
        f"{sym}{c['fair_val']:,.2f}" if c["fair_val"] else "   —"
        f"{c['upside']*100:+.1f}%" if c["upside"] is not None else "   —"
        f"{c['pe']:.0f}x" if c["pe"] else "  —"

        in_port   = c["ticker"] in holdings
        tranches  = len(holdings.get(c["ticker"], {}).get("tranches", []))
        if in_port:
            status_hint = "FULL POSITION" if tranches >= MAX_TRANCHES else f"ADD T{tranches + 1}"
        else:
            status_hint = "BUY T1"

        f_max = c.get("piotroski_max")
        if c.get("piotroski_f") is not None and f_max:
            status_hint += f"  ·  F {c['piotroski_f']}/{f_max}"
        acc = c.get("accruals_ratio")
        if acc is not None and not (isinstance(acc, float) and math.isnan(acc)) and acc > 0.10:
            status_hint += "  ⚠ accruals"


    return candidates


# ── --add ─────────────────────────────────────────────────────────────────────

def cmd_add(args):
    ticker  = args.add.upper()
    tranche = getattr(args, "tranche", 1)

    port     = load_portfolio()
    meta     = port["meta"]
    holdings = port["holdings"]

    total_capital    = meta["total_capital"]
    position_capital = total_capital * POSITION_PCT
    tranche_capital  = position_capital / MAX_TRANCHES

    # Validate tranche number
    existing = holdings.get(ticker, {})
    n_existing = len(existing.get("tranches", []))

    if tranche is None:
        tranche = n_existing + 1

    if tranche > MAX_TRANCHES:
        return

    if tranche <= n_existing:
        return

    if tranche != n_existing + 1:
        return

    # Fetch live price
    yf_d  = get_yf_fundamentals(ticker)
    price = yf_d.get("current_price") or 0
    if price <= 0:
        return

    # Check cash
    if meta["cash"] < tranche_capital:
        return

    # Build tranche record
    shares   = round(tranche_capital / price, 4)
    invested = round(shares * price, 2)
    date_str = datetime.now().strftime(DATE_FMT)

    tranche_rec = {
        "date":     date_str,
        "price":    round(price, 2),
        "shares":   shares,
        "invested": invested,
    }

    # Fetch fundamentals for scoring
    fund_data = load_or_refresh_fundamentals([ticker])
    fund_row  = fund_data.get(ticker)
    score     = float(fund_row.get("total_score", 0)) if fund_row else 0.0
    fv_data   = fair_value_estimate(yf_d, fund_row)
    fair_val  = fv_data.get("fair_value")

    if not existing:
        # New position
        holdings[ticker] = {
            "name":           yf_d.get("name", ticker),
            "sector":         yf_d.get("sector", ""),
            "currency":       yf_d.get("currency", "USD"),
            "tranches":       [tranche_rec],
            "avg_cost":       round(price, 2),
            "total_shares":   shares,
            "total_invested": invested,
            "thesis_status":  "HOLD",
            "fund_score":     round(score, 1),
            "fund_score_prev": None,
            "fair_value":     fair_val,
            "last_screened":  date_str,
            "flags":          [],
            "exit_history":   [],
        }
    else:
        # Add tranche to existing
        existing["tranches"].append(tranche_rec)
        all_tranches   = existing["tranches"]
        total_shares   = sum(t["shares"] for t in all_tranches)
        total_invested = sum(t["invested"] for t in all_tranches)
        avg_cost       = total_invested / total_shares if total_shares > 0 else 0

        existing["total_shares"]   = round(total_shares, 4)
        existing["total_invested"] = round(total_invested, 2)
        existing["avg_cost"]       = round(avg_cost, 2)
        existing["fund_score"]     = round(score, 1)
        existing["fair_value"]     = fair_val
        existing["last_screened"]  = date_str
        holdings[ticker] = existing

    # Deduct cash
    meta["cash"] = round(meta["cash"] - invested, 2)
    port["meta"]     = meta
    port["holdings"] = holdings
    save_portfolio(port)

    currency_sym(yf_d.get("currency", "USD"))


# ── --rescreen ────────────────────────────────────────────────────────────────

def cmd_rescreen(args):
    port     = load_portfolio()
    meta     = port["meta"]
    holdings = port["holdings"]

    if not holdings:
        return

    force = getattr(args, "force_refresh", False)
    tickers = list(holdings.keys())


    fund_data = load_or_refresh_fundamentals(tickers, force=force)

    changes = []
    for ticker, holding in holdings.items():
        fund_row = fund_data.get(ticker)
        yf_d     = get_yf_fundamentals(ticker)
        price    = yf_d.get("current_price") or 0

        prev_score  = holding.get("fund_score")
        prev_status = holding.get("thesis_status", "HOLD")

        updated = _apply_rescreen_rules(ticker, holding, fund_row, yf_d, price)
        holdings[ticker] = updated

        new_score  = updated.get("fund_score")
        new_status = updated.get("thesis_status", "HOLD")

        if new_status != prev_status:
            pass
        elif new_score is not None and prev_score is not None:
            delta = new_score - prev_score
            if abs(delta) >= 3:
                pass

        "  [" + ", ".join(updated.get("flags", [])) + "]" if updated.get("flags") else ""

        if new_status in ("EXIT", "TRIM"):
            changes.append((ticker, new_status, updated.get("flags", [])))

    meta["last_rescreen"] = datetime.now().strftime(DATE_FMT)
    port["meta"]     = meta
    port["holdings"] = holdings
    save_portfolio(port)

    if changes:
        for ticker, status, _flags in changes:
            if status == "EXIT" or status == "TRIM":
                pass
    else:
        pass



# ── --status ──────────────────────────────────────────────────────────────────

def cmd_status(args):
    port     = load_portfolio()
    meta     = port["meta"]
    holdings = port["holdings"]

    today    = datetime.now().strftime(DATE_FMT)
    meta["total_capital"]
    meta["cash"]

    if not holdings:
        save_portfolio(port)
        return

    # Fetch live prices

    rows    = []
    total_invested    = 0.0
    total_port_value  = 0.0

    for ticker, h in holdings.items():
        price = get_live_price(ticker) or h["avg_cost"]
        sym   = currency_sym(h.get("currency", "USD"))

        n_tranches    = len(h.get("tranches", []))
        avg_cost      = h.get("avg_cost", 0)
        total_shares  = h.get("total_shares", 0)
        inv           = h.get("total_invested", 0)
        curr_val      = total_shares * price
        gain_pct      = (curr_val - inv) / inv if inv > 0 else 0
        fair_val      = h.get("fair_value")
        to_fv         = ((fair_val - price) / price) if fair_val and price else None
        score         = h.get("fund_score", 0)
        status        = h.get("thesis_status", "HOLD")

        total_invested   += inv
        total_port_value += curr_val

        # Action hint
        if status == "HOLD" and n_tranches < MAX_TRANCHES:
            action = f"Add T{n_tranches + 1}"
        elif status == "HOLD":
            action = "Full position"
        elif status == "WATCH":
            action = "No new tranches"
        elif status == "TRIM":
            action = "Sell 50%"
        elif status == "EXIT":
            action = "Close position"
        else:
            action = status

        rows.append({
            "ticker":    ticker,
            "name":      h.get("name", ticker)[:20],
            "tranches":  f"{n_tranches}/{MAX_TRANCHES}",
            "avg_cost":  avg_cost,
            "price":     price,
            "gain_pct":  gain_pct,
            "fair_val":  fair_val,
            "to_fv":     to_fv,
            "score":     score,
            "status":    status,
            "action":    action,
            "sym":       sym,
        })

    total_gain_pct = (total_port_value - total_invested) / total_invested if total_invested > 0 else 0


    for r in rows:
        sym      = r["sym"]
        f"{sym}{r['avg_cost']:,.2f}"
        f"{sym}{r['price']:,.2f}"
        f"{r['gain_pct']*100:+.1f}%"
        f"{sym}{r['fair_val']:,.2f}" if r["fair_val"] else "   —"
        f"{r['to_fv']*100:+.1f}%" if r["to_fv"] is not None else "   —"
        f"{r['score']:.1f}"


    f"{total_gain_pct*100:+.2f}%"

    # ── write JSON for dashboard ───────────────────────────────────────────────
    # Build enriched holdings for dashboard
    dash_holdings = {}
    for ticker, h in holdings.items():
        r = next(x for x in rows if x["ticker"] == ticker)
        dash_holdings[ticker] = {
            **h,
            "current_price":   round(r["price"], 2),
            "current_value":   round(r["price"] * h.get("total_shares", 0), 2),
            "gain_pct":        round(r["gain_pct"], 4),
            "to_fv_pct":       round(r["to_fv"], 4) if r["to_fv"] is not None else None,
            "action_hint":     r["action"],
            "n_tranches":      len(h.get("tranches", [])),
        }

    dash_data = {
        "meta": {
            **meta,
            "total_invested":   round(total_invested, 2),
            "portfolio_value":  round(total_port_value, 2),
            "total_gain_pct":   round(total_gain_pct, 4),
            "as_of":            today,
        },
        "holdings": dash_holdings,
    }

    save_portfolio(port)   # ensure holding data is saved
    os.makedirs("reports", exist_ok=True)
    os.makedirs("dashboard", exist_ok=True)
    payload = json.dumps(dash_data, indent=2, default=str)
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        f.write(payload)
    with open("dashboard/lt_portfolio.json", "w", encoding="utf-8") as f:
        f.write(payload)


# ── --exit ────────────────────────────────────────────────────────────────────

def cmd_exit(args):
    ticker = args.exit.upper()
    port   = load_portfolio()
    meta   = port["meta"]
    holdings = port["holdings"]

    if ticker not in holdings:
        return

    h     = holdings[ticker]
    price = get_live_price(ticker) or h["avg_cost"]
    currency_sym(h.get("currency", "USD"))

    total_shares  = h.get("total_shares", 0)
    total_invested = h.get("total_invested", 0)
    curr_val      = total_shares * price
    gain_pct      = (curr_val - total_invested) / total_invested if total_invested > 0 else 0

    # Record in exit history
    {
        "exit_date":       datetime.now().strftime(DATE_FMT),
        "exit_price":      round(price, 2),
        "shares_sold":     total_shares,
        "proceeds":        round(curr_val, 2),
        "invested":        round(total_invested, 2),
        "gain_loss":       round(curr_val - total_invested, 2),
        "gain_pct":        round(gain_pct, 4),
        "reason":          getattr(args, "reason", "MANUAL"),
        "thesis_status":   h.get("thesis_status", "HOLD"),
    }

    # Return cash
    meta["cash"] = round(meta["cash"] + curr_val, 2)

    # Save exit to history in file (optional: keep as closed log)
    # Remove from active holdings
    del holdings[ticker]

    port["meta"]     = meta
    port["holdings"] = holdings
    save_portfolio(port)

    f"{gain_pct*100:+.2f}%"
    f"{curr_val - total_invested:+,.2f}"


# ── programmatic helpers (called by pipeline) ─────────────────────────────────

def add_ticker(ticker: str, tranche: int | None = None, force_refresh: bool = False) -> bool:
    """Programmatic version of --add. Returns True on success."""
    import types
    args = types.SimpleNamespace(add=ticker, tranche=tranche, force_refresh=force_refresh)
    try:
        cmd_add(args)
        return True
    except SystemExit:
        return False


def exit_ticker(ticker: str, reason: str = "AUTO_EXIT") -> bool:
    """Programmatic version of --exit. Returns True on success."""
    import types
    args = types.SimpleNamespace(exit=ticker, reason=reason)
    try:
        cmd_exit(args)
        return True
    except SystemExit:
        return False


def auto_manage(force_refresh: bool = False) -> dict:
    """
    Fully automated portfolio management — called by the pipeline.

    Steps:
      1. Scan for LT candidates (score >= MIN_FUND_SCORE)
      2. Auto-add top candidates into empty position slots (up to MAX_POSITIONS)
      3. Rescreen existing holdings; auto-exit any marked EXIT
      4. Write status JSON for dashboard
    Returns summary dict.
    """
    import types

    # ── 1. Scan ───────────────────────────────────────────────────────────────
    candidates = _build_candidates(force_refresh)

    # ── 2. Auto-add ───────────────────────────────────────────────────────────
    port     = load_portfolio()
    holdings = port.get("holdings", {})
    open_slots = MAX_POSITIONS - len(holdings)

    added = []
    if open_slots > 0:
        for c in candidates:
            if open_slots <= 0:
                break
            t = c["ticker"]
            if t in holdings:
                continue   # already held
            ok = add_ticker(t, tranche=1, force_refresh=force_refresh)
            if ok:
                added.append(t)
                open_slots -= 1
                # Reload after each add so cash is updated
                port     = load_portfolio()
                holdings = port.get("holdings", {})
    else:
        pass

    # ── 3. Rescreen + auto-exit ───────────────────────────────────────────────
    port = load_portfolio()
    if port.get("holdings"):
        rescreen_args = types.SimpleNamespace(force_refresh=force_refresh)
        cmd_rescreen(rescreen_args)

        # Auto-exit any positions the rescreen flagged EXIT
        port     = load_portfolio()
        exited   = []
        for t, h in list(port.get("holdings", {}).items()):
            if h.get("thesis_status") == "EXIT":
                exit_ticker(t, reason="FUND_DETERIORATION")
                exited.append(t)
    else:
        exited = []

    # ── 4. Write dashboard JSON ───────────────────────────────────────────────
    status_args = types.SimpleNamespace(force_refresh=force_refresh)
    cmd_status(status_args)

    return {"added": added, "exited": exited, "candidates": len(candidates)}


# ── --capital ─────────────────────────────────────────────────────────────────

def cmd_capital(args):
    new_cap = float(args.capital)
    port    = load_portfolio()
    port["meta"]["total_capital"]

    # Adjust cash proportionally only if portfolio is new (no holdings)
    if not port["holdings"]:
        port["meta"]["cash"] = new_cap

    port["meta"]["total_capital"] = new_cap
    save_portfolio(port)
    if not port["holdings"]:
        pass


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Long-term portfolio management — fundamental-only exit rules",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--scan",       action="store_true",
                       help="Screen DEFAULT_US for long-term candidates (default)")
    group.add_argument("--add",        type=str, metavar="TICKER",
                       help="Add a tranche to a position")
    group.add_argument("--rescreen",   action="store_true",
                       help="Re-run fundamentals on all holdings, apply exit rules")
    group.add_argument("--status",     action="store_true",
                       help="Print portfolio table and write reports/lt_portfolio.json")
    group.add_argument("--exit",       type=str, metavar="TICKER",
                       help="Manually close a position")
    group.add_argument("--capital",    type=float, metavar="N",
                       help="Set total capital (default 100000)")

    p.add_argument("--tranche",        type=int, default=None,
                   help="Tranche number for --add (1, 2, or 3; auto-detected if omitted)")
    p.add_argument("--force-refresh",  action="store_true",
                   help="Bypass fundamental cache during --rescreen or --scan")
    p.add_argument("--reason",         type=str, default="MANUAL",
                   help="Exit reason tag for --exit (default: MANUAL)")
    return p.parse_args()


def main():
    args = parse_args()

    # Ensure reports dir exists
    os.makedirs("reports", exist_ok=True)

    if args.capital:
        cmd_capital(args)
    elif args.add:
        cmd_add(args)
    elif args.rescreen:
        cmd_rescreen(args)
    elif args.status:
        cmd_status(args)
    else:
        # Default: --scan
        cmd_scan(args)


if __name__ == "__main__":
    main()
