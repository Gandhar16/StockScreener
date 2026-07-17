from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stock_scanner.config import ScannerConfig
from stock_scanner.scanner import StockScanner


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    # Mock data provider filtering out LOWVOL and PENNY, leaving AAPL and MSFT
    provider.fetch_and_filter_prices.return_value = pd.DataFrame([
        {"ticker": "AAPL", "last_price": 150.0, "avg_volume": 1_000_000},
        {"ticker": "MSFT", "last_price": 300.0, "avg_volume": 2_000_000}
    ])

    # Mock historical daily prices for technical analysis
    dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
    mock_ohlc = pd.DataFrame({
        "Open": [100.0] * 100,
        "High": [105.0] * 100,
        "Low": [95.0] * 100,
        "Close": [100.0] * 100,
        "Volume": [200000] * 100
    }, index=dates)
    provider.fetch_historical_prices.return_value = mock_ohlc
    return provider

@pytest.fixture
def mock_engine():
    engine = MagicMock()
    # Mock fundamental analysis output
    engine.analyze_tickers.return_value = pd.DataFrame([
        {
            "ticker": "MSFT", "last_price": 300.0, "avg_volume": 2_000_000,
            "current_ratio": 2.0, "debt_to_equity": 0.8, "pe_ratio": 20.0,
            "roic_3y": 0.22, "operating_margin": 0.30, "fcf_to_net_income": 1.1,
            "graham_score": 85.0, "fisher_score": 75.0, "buffett_score": 90.0,
            "total_score": 83.5
        },
        {
            "ticker": "AAPL", "last_price": 150.0, "avg_volume": 1_000_000,
            "current_ratio": 1.5, "debt_to_equity": 1.1, "pe_ratio": 25.0,
            "roic_3y": 0.18, "operating_margin": 0.25, "fcf_to_net_income": 1.0,
            "graham_score": 70.0, "fisher_score": 70.0, "buffett_score": 80.0,
            "total_score": 73.5
        }
    ])
    return engine

@patch("stock_scanner.scanner.DataProvider")
@patch("stock_scanner.scanner.FundamentalEngine")
def test_scanner_market_scan_mode(mock_engine_cls, mock_provider_cls, mock_engine, mock_provider):
    mock_provider_cls.return_value = mock_provider
    mock_engine_cls.return_value = mock_engine

    config = ScannerConfig(mode="market_scan", tickers=["AAPL", "MSFT"])
    scanner = StockScanner(config)
    results = scanner.run()

    assert len(results) == 2
    assert results.iloc[0]["ticker"] == "MSFT"
    assert results.iloc[1]["ticker"] == "AAPL"

    mock_provider.fetch_and_filter_prices.assert_called_once_with(["AAPL", "MSFT"])
    mock_engine.analyze_tickers.assert_called_once()

@patch("stock_scanner.scanner.DataProvider")
@patch("stock_scanner.scanner.FundamentalEngine")
def test_scanner_single_stock_mode(mock_engine_cls, mock_provider_cls, mock_engine, mock_provider):
    mock_provider_cls.return_value = mock_provider
    mock_engine_cls.return_value = mock_engine

    # In single stock mode, we directly analyze fundamentals and fetch market details
    config = ScannerConfig(mode="single_stock", tickers=["AAPL"])
    scanner = StockScanner(config)
    results = scanner.run()

    assert len(results) == 2  # returns mocked engine results
    mock_provider.fetch_and_filter_prices.assert_called_once_with(["AAPL"])
    mock_engine.analyze_tickers.assert_called_once_with(["AAPL"])

@pytest.mark.skip(reason="Windows temp dir permission issue")
def test_save_buys_to_excel(tmp_path):
    import os

    from stock_scanner.output import save_buys_to_excel

    df = pd.DataFrame([
        {"ticker": "AAPL", "rating": "Strong Buy", "total_score": 85.0, "red_flags": []},
        {"ticker": "MSFT", "rating": "Buy", "total_score": 80.0, "red_flags": []},
        {"ticker": "GOOGL", "rating": "Hold / Neutral", "total_score": 60.0, "red_flags": []},
        {"ticker": "BAD", "rating": "Avoid", "total_score": 30.0, "red_flags": []}
    ])

    output_file = tmp_path / "buy_recommendations.xlsx"
    save_buys_to_excel(df, str(output_file))

    assert os.path.exists(output_file)

    reloaded_df = pd.read_excel(output_file, engine='openpyxl')
    tickers = reloaded_df["ticker"].tolist()
    assert "AAPL" in tickers
    assert "MSFT" in tickers
    assert "GOOGL" not in tickers
    assert "BAD" not in tickers
