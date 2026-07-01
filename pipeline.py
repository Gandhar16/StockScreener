"""
pipeline.py
===========
Master pipeline — single command to run all analysis stages and refresh dashboard.

  Stage 1  Fundamental screen   (50-ticker universe)
  Stage 2  Equity calls          → reports/equity_calls.json
  Stage 3  Technical charts      → reports/<ticker>_<period>.png
  Stage 4  Backtest simulation   → dashboard/data.json
  Stage 5  LT portfolio          → reports/lt_portfolio.json

Usage:
    python pipeline.py                   # full run
    python pipeline.py --fast            # skip backtest + charts (quickest refresh)
    python pipeline.py --skip-backtest   # skip backtest only
    python pipeline.py --skip-charts     # skip chart PNG generation
    python pipeline.py --force-refresh   # bypass 24h fundamental cache
"""

import os, sys, time, json, argparse, traceback, socket, subprocess, webbrowser
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── helpers ────────────────────────────────────────────────────────────────────

def _hdr(title: str):
    w = 70
    print(f"\n{'─' * w}")
    print(f"  {title}")
    print(f"{'─' * w}")

def _ok(msg: str):  print(f"  [OK]  {msg}")
def _err(msg: str): print(f"  [!!]  {msg}")
def _info(msg: str):print(f"        {msg}")

def _elapsed(t0: float) -> str:
    s = time.time() - t0
    return f"{s:.1f}s" if s < 60 else f"{s/60:.1f}min"

# ── stage runners ──────────────────────────────────────────────────────────────

def stage_equity_calls(args) -> bool:
    """Stage 1-3: fundamentals + equity calls + optional charts (one pass)."""
    save_charts = not (args.skip_charts or args.fast)
    label = "STAGE 1-3  Fundamental screen + Equity calls + Charts"
    if not save_charts:
        label = "STAGE 1-2  Fundamental screen + Equity calls"
    _hdr(label)
    t0 = time.time()
    try:
        from generate_calls import generate_calls, print_calls, DEFAULT_US, DEFAULT_INDIA
        tickers = DEFAULT_US + DEFAULT_INDIA
        _info(f"{len(tickers)} tickers  |  charts={'yes' if save_charts else 'no'}  |  "
              f"force_refresh={args.force_refresh}")

        calls = generate_calls(
            tickers,
            period="1y",
            run_fundamentals=True,
            save_charts=save_charts,
            force_refresh=args.force_refresh,
        )
        print_calls(calls)

        os.makedirs("reports", exist_ok=True)
        os.makedirs("dashboard", exist_ok=True)
        payload = json.dumps(calls, indent=2, default=str)
        with open("reports/equity_calls.json", "w", encoding="utf-8") as f:
            f.write(payload)
        with open("dashboard/equity_calls.json", "w", encoding="utf-8") as f:
            f.write(payload)

        lt  = len(calls.get("long_term_calls", []))
        sw  = len(calls.get("swing_calls", []))
        sl  = len(calls.get("sell_calls", []))
        _ok(f"Equity calls → dashboard/equity_calls.json  [{lt} LT | {sw} swing | {sl} sell]  ({_elapsed(t0)})")
        return True
    except Exception:
        _err(f"Equity calls stage failed  ({_elapsed(t0)})")
        traceback.print_exc()
        return False


def stage_charts(args) -> bool:
    return True   # merged into stage_equity_calls


def stage_backtest(args) -> bool:
    """Stage 4: swing backtest + long-term backtest."""
    _hdr("STAGE 4  Backtest simulation (swing + long-term)")
    if args.skip_backtest or args.fast:
        _info("Skipped  (--skip-backtest / --fast)")
        return True
    t0 = time.time()
    try:
        import run_pipeline as rp

        # 4a — swing strategy backtest
        _info("Running swing strategy backtest ...")
        sw_result = rp.run()
        fc  = sw_result.get("final_capital", 0)
        _ok(f"Swing backtest → ${fc:,.0f}  ({_elapsed(t0)})")

        # 4b — long-term no-SL backtest
        t1 = time.time()
        _info("Running long-term (no stop-loss) backtest ...")
        lt_result = rp.run_lt()
        fc_lt = lt_result.get("final_capital", 0)
        _ok(f"LT backtest    → ${fc_lt:,.0f}  ({_elapsed(t1)})")

        return True
    except Exception:
        _err(f"Backtest stage failed  ({_elapsed(t0)})")
        traceback.print_exc()
        return False


def stage_lt_portfolio(args) -> bool:
    """Stage 5: fully automated LT portfolio — scan, auto-add, rescreen, auto-exit, dashboard JSON."""
    _hdr("STAGE 5  Long-term portfolio (auto-managed)")
    t0 = time.time()
    try:
        from long_term_portfolio import auto_manage
        result = auto_manage(force_refresh=args.force_refresh)
        added  = result.get("added", [])
        exited = result.get("exited", [])
        cands  = result.get("candidates", 0)
        _ok(f"LT portfolio → {cands} candidates | +{len(added)} added | -{len(exited)} exited  ({_elapsed(t0)})")
        return True
    except Exception:
        _err(f"LT portfolio stage failed  ({_elapsed(t0)})")
        traceback.print_exc()
        return False


# ── dashboard launcher ─────────────────────────────────────────────────────────

def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def launch_dashboard():
    """Start HTTP server on port 8000 (if not already running) and open browser."""
    dash_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
    if not _port_open(8000):
        _info("Starting dashboard server on http://localhost:8000 ...")
        subprocess.Popen(
            [sys.executable, "-m", "http.server", "8000", "--directory", dash_dir],
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)   # give server a moment to bind
    else:
        _info("Dashboard server already running on port 8000")
    webbrowser.open("http://localhost:8000")
    _ok("Dashboard → http://localhost:8000")


# ── summary ────────────────────────────────────────────────────────────────────

def print_summary(results: dict, t_total: float):
    w = 70
    print(f"\n{'═' * w}")
    print(f"  PIPELINE COMPLETE  ({_elapsed(t_total)})")
    print(f"{'═' * w}")
    labels = {
        "calls":    "Equity calls + charts → reports/equity_calls.json + reports/*.png",
        "backtest": "Backtest              → dashboard/data.json",
        "lt":       "LT portfolio          → reports/lt_portfolio.json",
    }
    for key, label in labels.items():
        icon = "✓" if results.get(key) else "✗" if results.get(key) is False else "—"
        print(f"  {icon}  {label}")

    print(f"\n  Dashboard: open dashboard/index.html in a browser")
    print(f"             (serve with: python -m http.server 8000 --directory dashboard)")
    print()


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="StockCalls master pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--fast",           action="store_true",
                   help="Skip backtest and charts — fastest dashboard refresh")
    p.add_argument("--skip-backtest",  action="store_true",
                   help="Skip Stage 4 backtest simulation")
    p.add_argument("--skip-charts",    action="store_true",
                   help="Skip Stage 3 chart PNG generation")
    p.add_argument("--force-refresh",  action="store_true",
                   help="Bypass 24h fundamental data cache")
    return p.parse_args()


def main():
    args    = parse_args()
    t_total = time.time()
    now     = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"\n{'═' * 70}")
    print(f"  STOCKCALLS PIPELINE  —  {now}")
    if args.fast:
        print(f"  Mode: FAST  (no backtest, no charts)")
    print(f"{'═' * 70}")

    results = {}
    results["calls"]    = stage_equity_calls(args)
    results["backtest"] = stage_backtest(args)
    results["lt"]       = stage_lt_portfolio(args)

    print_summary(results, t_total)
    launch_dashboard()


if __name__ == "__main__":
    main()
