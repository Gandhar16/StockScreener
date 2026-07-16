import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.config import ScannerConfig

@pytest.fixture
def sample_config():
    return ScannerConfig(
        mode="market_scan",
        tickers=["AAPL", "MSFT", "RISK"],
        filters={
            "min_market_cap": 1_000_000,
            "min_price": 5.0,
            "min_volume": 100_000,
            "min_current_ratio": 1.0,
            "max_debt_to_equity": 2.0
        }
    )

@pytest.fixture
def mock_toolkit():
    # Helper to mock Toolkit behavior
    mock_tk = MagicMock()
    
    # Mock current ratio: AAPL=1.5, MSFT=2.0, RISK=0.5
    current_ratio_df = pd.DataFrame({
        "2023": [1.5, 2.0, 0.5],
        "2024": [1.6, 2.1, 0.4]
    }, index=["AAPL", "MSFT", "RISK"])
    mock_tk.ratios.get_current_ratio.return_value = current_ratio_df

    # Mock debt to equity: AAPL=1.2, MSFT=0.8, RISK=3.0
    debt_equity_df = pd.DataFrame({
        "2023": [1.2, 0.8, 3.0],
        "2024": [1.1, 0.7, 3.2]
    }, index=["AAPL", "MSFT", "RISK"])
    mock_tk.ratios.get_debt_to_equity_ratio.return_value = debt_equity_df

    # Mock PE ratio: AAPL=25, MSFT=20, RISK=15
    pe_df = pd.DataFrame({
        "2023": [25.0, 20.0, 15.0],
        "2024": [24.0, 19.0, 14.0]
    }, index=["AAPL", "MSFT", "RISK"])
    mock_tk.ratios.get_price_to_earnings_ratio.return_value = pe_df

    # Mock ROIC: AAPL=18%, MSFT=22%, RISK=5%
    roic_df = pd.DataFrame({
        "2022": [0.16, 0.20, 0.04],
        "2023": [0.17, 0.21, 0.05],
        "2024": [0.18, 0.22, 0.05]
    }, index=["AAPL", "MSFT", "RISK"])
    mock_tk.ratios.get_return_on_invested_capital.return_value = roic_df

    # Mock Operating Margin: AAPL=25%, MSFT=30%, RISK=8%
    op_margin_df = pd.DataFrame({
        "2023": [0.24, 0.29, 0.07],
        "2024": [0.25, 0.30, 0.08]
    }, index=["AAPL", "MSFT", "RISK"])
    mock_tk.ratios.get_operating_margin.return_value = op_margin_df

    # Mock other V2 ratios as empty or mocked
    mock_tk.ratios.get_price_to_book_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_ev_to_ebitda_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_gross_margin.return_value = pd.DataFrame()
    mock_tk.ratios.get_return_on_equity.return_value = pd.DataFrame()
    mock_tk.ratios.get_equity_multiplier.return_value = pd.DataFrame()
    mock_tk.ratios.get_interest_coverage_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_net_debt_to_ebitda_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_dividend_payout_ratio.return_value = pd.DataFrame()
    mock_tk.ratios.get_price_to_free_cash_flow_ratio.return_value = pd.DataFrame()

    # Mock income statement for Revenue, R&D Expenses, Net Income
    income_idx = ["Revenue", "Research and Development Expenses", "Net Income"]
    
    aapl_inc = pd.DataFrame({
        "2022": [100.0, 10.0, 20.0],
        "2023": [110.0, 11.0, 22.0],
        "2024": [120.0, 12.0, 24.0]
    }, index=income_idx)
    
    msft_inc = pd.DataFrame({
        "2022": [200.0, 20.0, 40.0],
        "2023": [220.0, 22.0, 44.0],
        "2024": [240.0, 24.0, 48.0]
    }, index=income_idx)
    
    risk_inc = pd.DataFrame({
        "2022": [50.0, 1.0, 2.0],
        "2023": [52.0, 1.0, 2.0],
        "2024": [54.0, 1.0, 2.0]
    }, index=income_idx)
    
    columns = pd.MultiIndex.from_product([["AAPL", "MSFT", "RISK"], ["2022", "2023", "2024"]])
    combined_inc = pd.DataFrame(index=income_idx, columns=columns)
    for ticker, df in [("AAPL", aapl_inc), ("MSFT", msft_inc), ("RISK", risk_inc)]:
        for year in ["2022", "2023", "2024"]:
            combined_inc[(ticker, year)] = df[year]
            
    mock_tk.get_income_statement.return_value = combined_inc

    # Mock Cash Flow statement for FCF calculation
    cf_idx = ["Operating Cash Flow", "Capital Expenditure"]
    aapl_cf = pd.DataFrame({
        "2022": [25.0, -5.0],
        "2023": [27.0, -5.0],
        "2024": [30.0, -6.0]
    }, index=cf_idx)
    
    msft_cf = pd.DataFrame({
        "2022": [50.0, -10.0],
        "2023": [55.0, -10.0],
        "2024": [60.0, -12.0]
    }, index=cf_idx)
    
    risk_cf = pd.DataFrame({
        "2022": [3.0, -2.5],
        "2023": [3.0, -2.5],
        "2024": [3.0, -2.5]
    }, index=cf_idx)
    
    combined_cf = pd.DataFrame(index=cf_idx, columns=columns)
    for ticker, df in [("AAPL", aapl_cf), ("MSFT", msft_cf), ("RISK", risk_cf)]:
        for year in ["2022", "2023", "2024"]:
            combined_cf[(ticker, year)] = df[year]
            
    mock_tk.get_cash_flow_statement.return_value = combined_cf
    mock_tk.get_balance_sheet_statement.return_value = pd.DataFrame()
    
    return mock_tk

@patch("financetoolkit.Toolkit")
@patch("yfinance.Ticker")
def test_fundamental_engine_scoring(mock_yf_ticker, mock_toolkit_class, mock_toolkit, sample_config):
    mock_toolkit_class.return_value = mock_toolkit
    
    # Mock yfinance Ticker info for sectors
    mock_ticker_inst = MagicMock()
    mock_ticker_inst.info = {
        "sector": "Technology",
        "industry": "Software - Infrastructure",
        "forwardPE": 20.0,
        "pegRatio": 1.2
    }
    mock_yf_ticker.return_value = mock_ticker_inst
    
    engine = FundamentalEngine(sample_config)
    results = engine.analyze_tickers(["AAPL", "MSFT", "RISK"])
    
    passed_tickers = results["ticker"].tolist()
    assert "AAPL" in passed_tickers
    assert "MSFT" in passed_tickers
    # RISK is filtered out because in market_scan mode, we drop disqualified stocks.
    # RISK has debt-to-equity = 3.2 > 3.0 which triggers check_red_flags leverage disqualification.
    assert "RISK" not in passed_tickers

    # MSFT should score higher than AAPL because:
    # - current ratio is higher (2.1 vs 1.6)
    # - debt to equity is lower (0.7 vs 1.1)
    # - PE is lower (19.0 vs 24.0)
    # - ROIC is higher (0.22 vs 0.18)
    # - Operating margin is higher (0.30 vs 0.25)
    row_msft = results[results["ticker"] == "MSFT"].iloc[0]
    row_aapl = results[results["ticker"] == "AAPL"].iloc[0]
    assert row_msft["total_score"] > row_aapl["total_score"]
    
    # Check individual V1 category scores exist for backward compatibility
    assert "graham_score" in row_msft
    assert "fisher_score" in row_msft
    assert "buffett_score" in row_msft
    assert row_msft["total_score"] > 0
    
    # Check V2 scores and explanations
    assert "business_quality_score" in row_msft
    assert "valuation_score" in row_msft
    assert "financial_risk_score" in row_msft
    assert "growth_score" in row_msft
    assert "capital_allocation_score" in row_msft
    assert "rating" in row_msft
    assert "category" in row_msft
    assert len(row_msft["strengths"]) > 0

    # V3 additive columns present
    for col in ("accruals_ratio", "rev_cagr_stability", "piotroski_f",
                "piotroski_max", "peer_valuation_percentile"):
        assert col in results.columns, f"missing {col}"
    assert "_w_valuation" not in results.columns  # internal, dropped

    # Accruals for MSFT: NI 48, OCF 60 → negative accruals (cash-rich) — but
    # balance sheet is empty in this mock so assets are NaN → accruals NaN.
    assert pd.isna(row_msft["accruals_ratio"])

    # Piotroski: NI>0, OCF>0, OCF>NI computable from mocked statements plus
    # current-ratio trend → at least 4 signals computable, score ≥ 3
    assert row_msft["piotroski_max"] >= 4
    assert row_msft["piotroski_f"] >= 3


class TestPeerPercentiles:
    def test_cheapest_gets_highest_percentile(self):
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D"],
            "sector": ["Tech"] * 4,
            "pe_ratio": [10.0, 20.0, 30.0, 40.0],
            "ev_to_ebitda": [5.0, 10.0, 15.0, 20.0],
        })
        pct = FundamentalEngine.compute_peer_percentiles(df)
        assert pct.iloc[0] > pct.iloc[1] > pct.iloc[2] > pct.iloc[3]

    def test_small_group_is_nan(self):
        df = pd.DataFrame({
            "ticker": ["A", "B"],
            "sector": ["Tech", "Tech"],
            "pe_ratio": [10.0, 20.0],
            "ev_to_ebitda": [5.0, 10.0],
        })
        pct = FundamentalEngine.compute_peer_percentiles(df)
        assert pct.isna().all()

    def test_groups_ranked_independently(self):
        df = pd.DataFrame({
            "ticker": list("ABCDEFGH"),
            "sector": ["Tech"] * 4 + ["Energy"] * 4,
            "pe_ratio": [10, 20, 30, 40, 5, 8, 12, 16],
            "ev_to_ebitda": [None] * 8,
        })
        pct = FundamentalEngine.compute_peer_percentiles(df)
        # cheapest in each sector gets that sector's top rank
        assert pct.iloc[0] == pct.iloc[4]

    def test_negative_multiples_ignored(self):
        df = pd.DataFrame({
            "ticker": ["A", "B", "C", "D", "E"],
            "sector": ["Tech"] * 5,
            "pe_ratio": [-5.0, 10.0, 20.0, 30.0, 40.0],
            "ev_to_ebitda": [None] * 5,
        })
        pct = FundamentalEngine.compute_peer_percentiles(df)
        assert pd.isna(pct.iloc[0])       # loss-maker: no meaningful P/E rank
        assert pct.iloc[1] > pct.iloc[4]
