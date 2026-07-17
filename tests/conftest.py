"""Pytest configuration and fixtures."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_metrics():
    """Sample metrics for testing."""
    return {
        "current_ratio_ttm": 2.0,
        "debt_to_equity_ttm": 0.5,
        "pe_ratio_ttm": 15.0,
        "revenue_growth_3y_avg": 0.15,
        "eps_growth_3y_avg": 0.12,
        "rd_intensity": 0.05,
        "roic_3y_avg": 0.20,
        "operating_margin_ttm": 0.20,
        "fcf_to_net_income_ttm": 1.2,
        "operating_margin_3y_avg": 0.18,
        "forward_pe": 14.0,
        "peg_ratio": 1.1,
        "price_to_book": 3.0,
        "ev_to_ebitda": 12.0,
        "price_to_sales": 4.0,
        "price_to_fcf": 20.0,
        "dividend_yield": 0.015,
        "gross_margin_ttm": 0.40,
        "roe_ttm": 0.22,
        "roe_3y_avg": 0.21,
        "equity_multiplier_ttm": 2.0,
        "interest_coverage_ttm": 10.0,
        "net_debt_to_ebitda_ttm": 1.5,
        "dividend_payout_ratio": 0.3,
        "ocf_ttm": 100_000_000,
        "ocf_3y_avg": 90_000_000,
        "assets_ttm": 500_000_000,
        "liabilities_ttm": 200_000_000,
        "net_income_3y_avg": 80_000_000,
        "shares_growth_3y": 0.02,
        "fcf_to_net_income_3y_avg": 1.1,
        "revenue_growth_ttm": 0.10,
        "eps_growth_ttm": 0.12,
        "margin_expansion": 0.02,
        "accruals_ratio": 0.01,
        "rev_cagr_stability": 0.15,
        "piotroski_f": 8,
        "piotroski_max": 9,
    }


@pytest.fixture
def sample_config():
    """Sample scanner configuration."""
    return {
        "weights": {
            "business_quality": 0.25,
            "valuation": 0.25,
            "financial_risk": 0.25,
            "growth": 0.25,
            "capital_allocation": 0.0,
        },
        "scoring_ranges": {
            "pe_ratio": [8.0, 36.0],
            "current_ratio": [1.0, 2.5],
            "debt_to_equity": [0.5, 2.0],
            "revenue_growth_yoy": [0.03, 0.21],
            "eps_growth_yoy": [-0.05, 0.165],
            "rd_intensity": [0.0, 0.1],
            "roic": [0.02, 0.29],
            "operating_margin": [0.07, 0.32],
            "fcf_to_net_income": [0.5, 1.5],
        }
    }


@pytest.fixture
def sample_ohlcv():
    """Sample OHLCV data for technical analysis tests."""
    dates = pd.date_range("2023-01-01", periods=252, freq="D")
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, 252)
    close = 100 * (1 + returns).cumprod()

    df = pd.DataFrame({
        "Open": close * (1 + np.random.normal(0, 0.002, 252)),
        "High": close * (1 + np.abs(np.random.normal(0, 0.01, 252))),
        "Low": close * (1 - np.abs(np.random.normal(0, 0.01, 252))),
        "Close": close,
        "Volume": np.random.lognormal(15, 0.5, 252).astype(int),
    }, index=dates)

    # Ensure High >= Close >= Low
    df["High"] = df[["High", "Close"]].max(axis=1)
    df["Low"] = df[["Low", "Close"]].min(axis=1)

    return df
