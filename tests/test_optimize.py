import pytest
from unittest.mock import patch, MagicMock
import sys
import os
import pandas as pd
from stock_scanner.config import load_config_from_yaml

# Import functions to test
from optimize import random_weights, sample_config_params, get_config_params_from_model, main

def test_random_weights():
    w = random_weights(3)
    assert len(w) == 3
    assert abs(sum(w) - 1.0) < 1e-5
    assert all(x >= 0 for x in w)

def test_sample_config_params():
    params = sample_config_params()
    assert "category_weights" in params
    assert "graham_safety" in params
    assert "scoring_ranges" in params
    assert len(params["scoring_ranges"]) == 7
    pe = params["scoring_ranges"]["pe_ratio"]
    assert pe[0] < pe[1]

@patch("yfinance.download")
@patch("financetoolkit.Toolkit")
@patch("yfinance.Ticker")
def test_optimize_main(mock_yf_ticker, mock_toolkit_class, mock_download, tmp_path):
    # Mock yfinance download
    columns = pd.MultiIndex.from_product([['Adj Close'], ['AAPL', 'MSFT', '^GSPC']])
    dates = pd.date_range(start="2022-06-10", end="2024-06-25")
    mock_df = pd.DataFrame(index=dates, columns=columns)
    mock_df[('Adj Close', 'AAPL')] = 100.0
    mock_df.loc[pd.Timestamp('2024-06-15'):, ('Adj Close', 'AAPL')] = 120.0
    mock_df[('Adj Close', 'MSFT')] = 200.0
    mock_df.loc[pd.Timestamp('2024-06-15'):, ('Adj Close', 'MSFT')] = 260.0
    mock_df[('Adj Close', '^GSPC')] = 4000.0
    mock_df.loc[pd.Timestamp('2024-06-15'):, ('Adj Close', '^GSPC')] = 4400.0
    mock_download.return_value = mock_df

    # Mock Toolkit
    mock_tk = MagicMock()
    mock_toolkit_class.return_value = mock_tk
    
    mock_tk.get_income_statement.return_value = pd.DataFrame()
    mock_tk.get_balance_sheet_statement.return_value = pd.DataFrame()
    mock_tk.get_cash_flow_statement.return_value = pd.DataFrame()
    mock_tk.ratios.get_current_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_debt_to_equity_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_price_to_earnings_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_return_on_invested_capital.return_value = pd.DataFrame()
    mock_tk.ratios.get_operating_margin.return_value = pd.DataFrame()
    mock_tk.ratios.get_price_to_book_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_ev_to_ebitda_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_gross_margin.return_value = pd.DataFrame()
    mock_tk.ratios.get_return_on_equity.return_value = pd.DataFrame()
    mock_tk.ratios.get_equity_multiplier.return_value = pd.DataFrame()
    mock_tk.ratios.get_interest_coverage_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_net_debt_to_ebitda_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_dividend_payout_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_price_to_free_cash_flow_ratio.return_value = pd.DataFrame()

    # Mock yfinance Ticker info
    mock_ticker_inst = MagicMock()
    mock_ticker_inst.info = {"sector": "Technology", "industry": "Software"}
    mock_yf_ticker.return_value = mock_ticker_inst

    # Create temporary config file
    config_file = tmp_path / "scanner_config.yaml"
    config_content = """
    mode: market_scan
    tickers: ["AAPL", "MSFT"]
    weights:
      category_weights:
        graham_safety: 0.35
        fisher_growth: 0.30
        buffett_quality: 0.35
      graham_safety:
        current_ratio: 0.3
        debt_to_equity: 0.3
        pe_ratio: 0.4
      fisher_growth:
        revenue_growth_yoy: 0.5
        eps_growth_yoy: 0.5
        rd_intensity: 0.0
      buffett_quality:
        roic: 0.4
        operating_margin: 0.3
        fcf_to_net_income: 0.3
    """
    config_file.write_text(config_content)

    test_args = [
        "optimize.py",
        "--config", str(config_file),
        "--tickers", "AAPL,MSFT",
        "--start-date", "2023-06-15",
        "--holding-months", "12",
        "--iterations", "5",
        "--refine-steps", "2",
        "--top-n", "2"
    ]
    with patch.object(sys, "argv", test_args):
        main()

    # Check updated config
    updated_config = load_config_from_yaml(config_file.read_text())
    assert updated_config.weights.category_weights.graham_safety is not None
