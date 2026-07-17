from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_scanner.engine.backtest import Backtester, get_bulk_historical_returns


@patch("yfinance.download")
def test_get_bulk_historical_returns(mock_download):
    # MultiIndex columns (Metric, Ticker)
    columns = pd.MultiIndex.from_product([["Adj Close"], ["AAPL", "MSFT"]])
    dates = pd.date_range(start="2023-06-10", end="2024-06-25")
    mock_df = pd.DataFrame(index=dates, columns=columns)

    # AAPL: price goes from 100 to 150
    mock_df[("Adj Close", "AAPL")] = 100.0
    mock_df.loc[pd.Timestamp("2024-06-15") :, ("Adj Close", "AAPL")] = 150.0

    # MSFT: price goes from 200 to 180
    mock_df[("Adj Close", "MSFT")] = 200.0
    mock_df.loc[pd.Timestamp("2024-06-15") :, ("Adj Close", "MSFT")] = 180.0

    mock_download.return_value = mock_df

    returns = get_bulk_historical_returns(
        ["AAPL", "MSFT"], pd.Timestamp("2023-06-15"), pd.Timestamp("2024-06-15"), benchmark="^GSPC"
    )

    assert "AAPL" in returns
    assert "MSFT" in returns
    assert returns["AAPL"] == pytest.approx(0.50)
    assert returns["MSFT"] == pytest.approx(-0.10)


@patch("yfinance.download")
def test_backtester_run(mock_download):
    # MultiIndex columns (Metric, Ticker)
    columns = pd.MultiIndex.from_product([["Adj Close"], ["AAPL", "MSFT", "^GSPC"]])
    dates = pd.date_range(start="2023-06-10", end="2024-06-25")
    mock_df = pd.DataFrame(index=dates, columns=columns)

    # AAPL return = +20%
    mock_df[("Adj Close", "AAPL")] = 100.0
    mock_df.loc[pd.Timestamp("2024-06-15") :, ("Adj Close", "AAPL")] = 120.0

    # MSFT return = +30%
    mock_df[("Adj Close", "MSFT")] = 200.0
    mock_df.loc[pd.Timestamp("2024-06-15") :, ("Adj Close", "MSFT")] = 260.0

    # ^GSPC return = +10%
    mock_df[("Adj Close", "^GSPC")] = 4000.0
    mock_df.loc[pd.Timestamp("2024-06-15") :, ("Adj Close", "^GSPC")] = 4400.0

    mock_download.return_value = mock_df

    # Mock FundamentalEngine
    mock_engine = MagicMock()
    mock_scored = pd.DataFrame(
        [
            {"ticker": "MSFT", "total_score": 90.0, "is_disqualified": False},
            {"ticker": "AAPL", "total_score": 85.0, "is_disqualified": False},
        ]
    )
    mock_engine.analyze_tickers.return_value = mock_scored

    backtester = Backtester(mock_engine, benchmark_ticker="^GSPC")
    results = backtester.run_backtest(
        tickers=["AAPL", "MSFT"], start_date="2023-06-15", holding_period_months=12, top_n=2
    )

    assert results["portfolio_return"] == pytest.approx(0.25)
    assert results["benchmark_return"] == pytest.approx(0.10)
    assert results["outperformance"] == pytest.approx(0.15)
    assert results["selected_stocks"] == ["MSFT", "AAPL"]
