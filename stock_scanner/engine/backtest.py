import logging
from typing import Any

import pandas as pd
import yfinance as yf

from stock_scanner.engine.fundamental import FundamentalEngine

logger = logging.getLogger(__name__)

def get_bulk_historical_returns(
    tickers: list[str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    benchmark: str = "^GSPC"
) -> dict[str, float]:
    """
    Downloads historical daily prices for all tickers (including the benchmark)
    in a single request, then computes holding period returns.
    """
    all_symbols = list({*tickers, benchmark})
    start_search = start_date - pd.Timedelta(days=5)
    end_search = end_date + pd.Timedelta(days=10)

    logger.info(f"Downloading bulk historical prices for {len(all_symbols)} tickers...")
    try:
        df = yf.download(
            all_symbols,
            start=start_search.strftime('%Y-%m-%d'),
            end=end_search.strftime('%Y-%m-%d'),
            progress=False
        )
    except Exception as e:
        logger.error(f"Failed to download bulk historical prices: {e}")
        return {}

    if df.empty:
        logger.warning("Bulk download returned empty DataFrame.")
        return {}

    returns = {}
    for sym in all_symbols:
        try:
            # Check if columns are MultiIndex or single index
            if isinstance(df.columns, pd.MultiIndex):
                if 'Adj Close' in df.columns.levels[0]:
                    series = df['Adj Close'][sym]
                elif 'Close' in df.columns.levels[0]:
                    series = df['Close'][sym]
                else:
                    continue
            else:
                # If only one ticker was returned and columns is not a MultiIndex
                if 'Adj Close' in df.columns:
                    series = df['Adj Close']
                elif 'Close' in df.columns:
                    series = df['Close']
                else:
                    continue

            series = series.dropna()
            if series.empty:
                continue

            # Find start price (first available on or after start_date)
            start_prices = series.loc[start_date:]
            start_price = series.iloc[0] if start_prices.empty else start_prices.iloc[0]

            # Find end price (last available on or before end_date)
            end_prices = series.loc[:end_date]
            end_price = series.iloc[-1] if end_prices.empty else end_prices.iloc[-1]

            if pd.isna(start_price) or pd.isna(end_price) or start_price == 0:
                continue

            returns[sym] = float((end_price - start_price) / start_price)
        except Exception as e:
            logger.warning(f"Failed to calculate return for {sym}: {e}")

    return returns

class Backtester:
    """
    Simulates historical stock selection using FundamentalEngine
    and calculates portfolio holding period return compared to a benchmark.
    """
    def __init__(self, engine: FundamentalEngine, benchmark_ticker: str = "^GSPC"):
        self.engine = engine
        self.benchmark_ticker = benchmark_ticker

    def run_backtest(
        self,
        tickers: list[str],
        start_date: str,
        holding_period_months: int = 12,
        top_n: int = 5
    ) -> dict[str, Any]:
        """
        Runs the backtest simulation.

        Args:
            tickers: List of ticker symbols to scan.
            start_date: Historical screening date (e.g. '2023-06-15').
            holding_period_months: Number of months to simulate holding the portfolio.
            top_n: Number of top-scoring stocks to select.

        Returns:
            A dictionary containing portfolio return, benchmark return, outperformance,
            the list of selected stocks, and returns by stock.
        """
        start_ts = pd.Timestamp(start_date)
        end_ts = start_ts + pd.DateOffset(months=holding_period_months)

        # Screen using prior year's statements to avoid lookahead bias
        as_of_year = start_ts.year - 1
        logger.info(f"Running historical screen for {start_date} using statements as of {as_of_year}...")

        scored_df = self.engine.analyze_tickers(tickers, as_of_year=as_of_year)
        if scored_df.empty:
            logger.warning("No tickers scored during backtest.")
            return {
                "portfolio_return": 0.0,
                "benchmark_return": 0.0,
                "outperformance": 0.0,
                "selected_stocks": [],
                "stock_returns": {},
                "all_scores": pd.DataFrame()
            }

        # Exclude disqualified stocks (red flags)
        eligible_df = scored_df[~scored_df.get("is_disqualified", False)]
        top_stocks_df = eligible_df.head(top_n)
        selected_tickers = top_stocks_df["ticker"].tolist()

        if not selected_tickers:
            logger.warning("No qualifying stocks found after screening.")
            return {
                "portfolio_return": 0.0,
                "benchmark_return": 0.0,
                "outperformance": 0.0,
                "selected_stocks": [],
                "stock_returns": {},
                "all_scores": scored_df
            }

        # Get bulk historical returns
        all_returns = get_bulk_historical_returns(
            selected_tickers,
            start_ts,
            end_ts,
            self.benchmark_ticker
        )

        portfolio_returns = []
        stock_returns_dict = {}
        for ticker in selected_tickers:
            ret = all_returns.get(ticker, float('nan'))
            stock_returns_dict[ticker] = ret
            if not pd.isna(ret):
                portfolio_returns.append(ret)

        portfolio_return = sum(portfolio_returns) / len(portfolio_returns) if portfolio_returns else 0.0
        benchmark_return = all_returns.get(self.benchmark_ticker, 0.0)
        outperformance = portfolio_return - benchmark_return

        logger.info(
            f"Backtest results: Portfolio={portfolio_return:.2%}, "
            f"Benchmark={benchmark_return:.2%}, Outperformance={outperformance:+.2%}"
        )

        return {
            "portfolio_return": portfolio_return,
            "benchmark_return": benchmark_return,
            "outperformance": outperformance,
            "selected_stocks": selected_tickers,
            "stock_returns": stock_returns_dict,
            "all_scores": scored_df
        }
