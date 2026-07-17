import json
import logging
import os

import pandas as pd
import yfinance as yf

from stock_scanner.config import load_config_from_file
from stock_scanner.engine.fundamental import FundamentalEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_simulation():
    # 1. Load config and engine
    config_path = "config/scanner_config.yaml"
    if not os.path.exists(config_path):
        logger.error("Config file not found.")
        return
    config = load_config_from_file(config_path)
    engine = FundamentalEngine(config)

    # We will run a 3-year simulation with annual rebalancing
    # Phase 1: 2023-06-15 to 2024-06-15 (as_of_year = 2022)
    # Phase 2: 2024-06-15 to 2025-06-15 (as_of_year = 2023)
    # Phase 3: 2025-06-15 to 2026-06-15 (as_of_year = 2024)

    phases = [
        {"start": "2023-06-15", "end": "2024-06-15", "as_of": 2022},
        {"start": "2024-06-15", "end": "2025-06-15", "as_of": 2023},
        {"start": "2025-06-15", "end": "2026-06-15", "as_of": 2024},
    ]

    tickers = [
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
        "BAC",
        "V",
        "JNJ",
        "LLY",
        "UNH",
        "WMT",
        "PG",
        "KO",
    ]
    logger.info(f"Starting portfolio simulation for 20 tickers: {tickers}")

    # Download daily history for all tickers + S&P 500 benchmark
    all_symbols = list({*tickers, "^GSPC"})
    start_date = "2023-06-10"
    end_date = "2026-06-20"
    logger.info(f"Downloading daily prices from {start_date} to {end_date}...")
    price_df = yf.download(all_symbols, start=start_date, end=end_date, progress=False)

    if price_df.empty:
        logger.error("Failed to download historical prices.")
        return

    # Extract Adj Close or Close series
    if isinstance(price_df.columns, pd.MultiIndex):
        if "Adj Close" in price_df.columns.levels[0]:
            price_df = price_df["Adj Close"]
        else:
            price_df = price_df["Close"]

    # Fill missing values
    price_df = price_df.ffill().bfill()

    initial_capital = 100000.0
    current_cash = initial_capital
    portfolio_history = []
    trade_logs = []

    # Benchmark tracking
    benchmark_shares = 0.0

    for phase_idx, phase in enumerate(phases):
        p_start = pd.Timestamp(phase["start"])
        p_end = pd.Timestamp(phase["end"])
        as_of = phase["as_of"]

        logger.info(
            f"Simulating Phase {phase_idx+1}: {phase['start']} to {phase['end']} (As Of: {as_of})"
        )

        # 1. Run the fundamental screen
        scored_df = engine.analyze_tickers(tickers, as_of_year=as_of)
        if scored_df.empty:
            logger.warning(f"No tickers scored for phase {phase['start']}. Skipping.")
            continue

        # Filter out disqualified
        eligible_df = scored_df[~scored_df.get("is_disqualified", False)]
        top_stocks = eligible_df.head(20)["ticker"].tolist()  # Select top 20 stocks

        if not top_stocks:
            logger.warning(f"No eligible stocks for phase {phase['start']}. Skipping.")
            continue

        logger.info(f"Selected portfolio for phase: {top_stocks}")

        # 2. Buy on start date (or first available trading day)
        trading_days = price_df.loc[p_start:p_end].index
        if len(trading_days) == 0:
            continue

        phase_start_day = trading_days[0]
        phase_end_day = trading_days[-1]

        # Allocate cash equally
        allocation = current_cash / len(top_stocks)
        holdings = {}
        for ticker in top_stocks:
            buy_price = float(price_df.loc[phase_start_day, ticker])
            shares = allocation / buy_price
            holdings[ticker] = {
                "buy_price": buy_price,
                "shares": shares,
                "buy_date": phase_start_day.strftime("%Y-%m-%d") + " 09:30:00",
            }

        # Setup benchmark on start date if first phase
        if phase_idx == 0:
            benchmark_buy_price = float(price_df.loc[phase_start_day, "^GSPC"])
            benchmark_shares = initial_capital / benchmark_buy_price

        # Track daily value
        for day in trading_days:
            # Portfolio value calculation
            port_val = 0.0
            for ticker, info in holdings.items():
                current_price = float(price_df.loc[day, ticker])
                port_val += info["shares"] * current_price

            # Benchmark value calculation
            bench_val = benchmark_shares * float(price_df.loc[day, "^GSPC"])

            portfolio_history.append(
                {
                    "date": day.strftime("%Y-%m-%d"),
                    "portfolio_value": port_val,
                    "benchmark_value": bench_val,
                }
            )

        # 3. Sell on end date
        next_cash = 0.0
        for ticker, info in holdings.items():
            sell_price = float(price_df.loc[phase_end_day, ticker])
            final_val = info["shares"] * sell_price
            next_cash += final_val

            profit_loss = final_val - allocation
            profit_loss_pct = (sell_price - info["buy_price"]) / info["buy_price"]

            trade_logs.append(
                {
                    "ticker": ticker,
                    "entry_date": info["buy_date"],
                    "exit_date": phase_end_day.strftime("%Y-%m-%d") + " 16:00:00",
                    "entry_price": info["buy_price"],
                    "exit_price": sell_price,
                    "shares": info["shares"],
                    "profit_loss": profit_loss,
                    "profit_loss_pct": profit_loss_pct,
                    "status": "WIN" if profit_loss > 0 else "LOSS",
                }
            )

        current_cash = next_cash

    # 4. Calculate Drawdowns
    max_portfolio_value = initial_capital
    max_benchmark_value = initial_capital

    for record in portfolio_history:
        # Portfolio DD
        max_portfolio_value = max(max_portfolio_value, record["portfolio_value"])
        record["portfolio_drawdown"] = (
            record["portfolio_value"] - max_portfolio_value
        ) / max_portfolio_value

        # Benchmark DD
        max_benchmark_value = max(max_benchmark_value, record["benchmark_value"])
        record["benchmark_drawdown"] = (
            record["benchmark_value"] - max_benchmark_value
        ) / max_benchmark_value

    # Prepare output JSON structure
    output_data = {
        "initial_capital": initial_capital,
        "final_capital": portfolio_history[-1]["portfolio_value"]
        if portfolio_history
        else initial_capital,
        "total_return": (portfolio_history[-1]["portfolio_value"] - initial_capital)
        / initial_capital
        if portfolio_history
        else 0.0,
        "benchmark_return": (portfolio_history[-1]["benchmark_value"] - initial_capital)
        / initial_capital
        if portfolio_history
        else 0.0,
        "max_drawdown": min([r["portfolio_drawdown"] for r in portfolio_history])
        if portfolio_history
        else 0.0,
        "benchmark_max_drawdown": min([r["benchmark_drawdown"] for r in portfolio_history])
        if portfolio_history
        else 0.0,
        "equity_curve": portfolio_history,
        "trade_logs": trade_logs,
    }

    # Save to dashboard directory
    os.makedirs("dashboard", exist_ok=True)
    with open("dashboard/data.json", "w") as f:
        json.dump(output_data, f, indent=4)

    logger.info("Simulation complete. Saved results to dashboard/data.json.")


if __name__ == "__main__":
    run_simulation()
