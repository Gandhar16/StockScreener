"""Unit tests for scoring engine and core modules."""

import pytest
import pandas as pd
import numpy as np
from stock_scanner.engine.scoring import (
    calculate_factor_scores,
    _score_current_ratio,
    _score_debt_to_equity,
    _score_pe_ratio,
    _score_revenue_growth,
    _score_eps_growth,
    _score_rd_intensity,
    _score_roic,
    _score_operating_margin,
    _score_fcf_to_net_income,
)
from stock_scanner.engine.risk_flags import check_red_flags
from stock_scanner.engine.fundamental import FundamentalEngine


class TestScoringFunctions:
    """Test individual scoring functions."""

    def test_score_current_ratio(self):
        """Test current ratio scoring."""
        # Below minimum -> 0
        assert _score_current_ratio(0.5, {"min": 1.0, "max": 2.5}) == 0
        # At minimum -> 0
        assert _score_current_ratio(1.0, {"min": 1.0, "max": 2.5}) == 0
        # At maximum -> 100
        assert _score_current_ratio(2.5, {"min": 1.0, "max": 2.5}) == 100
        # Midpoint -> 50
        assert _score_current_ratio(1.75, {"min": 1.0, "max": 2.5}) == 50
        # Above maximum -> 100
        assert _score_current_ratio(3.0, {"min": 1.0, "max": 2.5}) == 100
        # NaN -> 50
        assert _score_current_ratio(float("nan"), {"min": 1.0, "max": 2.5}) == 50

    def test_score_debt_to_equity(self):
        """Test debt-to-equity scoring (lower is better)."""
        # Above maximum -> 0
        assert _score_debt_to_equity(3.0, {"min": 0.5, "max": 2.0}) == 0
        # At maximum -> 0
        assert _score_debt_to_equity(2.0, {"min": 0.5, "max": 2.0}) == 0
        # At minimum -> 100
        assert _score_debt_to_equity(0.5, {"min": 0.5, "max": 2.0}) == 100
        # Midpoint -> 50
        assert _score_debt_to_equity(1.25, {"min": 0.5, "max": 2.0}) == 50
        # Below minimum -> 100
        assert _score_debt_to_equity(0.2, {"min": 0.5, "max": 2.0}) == 100

    def test_score_pe_ratio(self):
        """Test P/E ratio scoring."""
        # Negative P/E -> 0
        assert _score_pe_ratio(-5, {"min": 8.0, "max": 36.0}) == 0
        # Below minimum -> 100
        assert _score_pe_ratio(5, {"min": 8.0, "max": 36.0}) == 100
        # At minimum -> 100
        assert _score_pe_ratio(8, {"min": 8.0, "max": 36.0}) == 100
        # At maximum -> 0
        assert _score_pe_ratio(36, {"min": 8.0, "max": 36.0}) == 0
        # Midpoint -> 50
        assert _score_pe_ratio(22, {"min": 8.0, "max": 36.0}) == 50
        # Above maximum -> 0
        assert _score_pe_ratio(50, {"min": 8.0, "max": 36.0}) == 0

    def test_score_revenue_growth(self):
        """Test revenue growth scoring."""
        # Negative growth -> 0
        assert _score_revenue_growth(-0.1, {"min": 0.03, "max": 0.21}) == 0
        # At minimum -> 0
        assert _score_revenue_growth(0.03, {"min": 0.03, "max": 0.21}) == 0
        # At maximum -> 100
        assert _score_revenue_growth(0.21, {"min": 0.03, "max": 0.21}) == 100
        # Midpoint -> 50
        assert _score_revenue_growth(0.12, {"min": 0.03, "max": 0.21}) == 50
        # Above maximum -> 100
        assert _score_revenue_growth(0.30, {"min": 0.03, "max": 0.21}) == 100

    def test_score_eps_growth(self):
        """Test EPS growth scoring."""
        assert _score_eps_growth(-0.05, {"min": -0.05, "max": 0.165}) == 0
        assert _score_eps_growth(0.165, {"min": -0.05, "max": 0.165}) == 100
        assert _score_eps_growth(0.0575, {"min": -0.05, "max": 0.165}) == 50

    def test_score_rd_intensity(self):
        """Test R&D intensity scoring."""
        assert _score_rd_intensity(0.0, {"min": 0.0, "max": 0.1}) == 0
        assert _score_rd_intensity(0.1, {"min": 0.0, "max": 0.1}) == 100
        assert _score_rd_intensity(0.05, {"min": 0.0, "max": 0.1}) == 50
        assert _score_rd_intensity(0.15, {"min": 0.0, "max": 0.1}) == 100

    def test_score_roic(self):
        """Test ROIC scoring."""
        assert _score_roic(0.01, {"min": 0.02, "max": 0.29}) == 0
        assert _score_roic(0.29, {"min": 0.02, "max": 0.29}) == 100
        assert _score_roic(0.155, {"min": 0.02, "max": 0.29}) == 50

    def test_score_operating_margin(self):
        """Test operating margin scoring."""
        assert _score_operating_margin(0.05, {"min": 0.07, "max": 0.32}) == 0
        assert _score_operating_margin(0.32, {"min": 0.07, "max": 0.32}) == 100
        assert _score_operating_margin(0.195, {"min": 0.07, "max": 0.32}) == 50

    def test_score_fcf_to_net_income(self):
        """Test FCF to Net Income scoring."""
        assert _score_fcf_to_net_income(-0.5, {"min": 0.5, "max": 1.5}) == 0
        assert _score_fcf_to_net_income(1.0, {"min": 0.5, "max": 1.5}) == 50
        assert _score_fcf_to_net_income(1.5, {"min": 0.5, "max": 1.5}) == 100
        assert _score_fcf_to_net_income(2.0, {"min": 0.5, "max": 1.5}) == 100


class TestRiskFlags:
    """Test red flag detection."""

    def test_high_debt_flag(self):
        """Test high debt-to-equity flag."""
        metrics = {
            "debt_to_equity_ttm": 3.0,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert any("High leverage" in f for f in flags)
        assert penalty > 0

    def test_low_current_ratio_flag(self):
        """Test low current ratio flag."""
        metrics = {
            "debt_to_equity_ttm": 1.0,
            "current_ratio_ttm": 0.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert any("Low liquidity" in f for f in flags)

    def test_negative_pe_flag(self):
        """Test negative P/E flag."""
        metrics = {
            "debt_to_equity_ttm": 1.0,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": -5.0,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert any("Negative P/E" in f for f in flags)

    def test_piotroski_low_flag(self):
        """Test low Piotroski F-score flag."""
        metrics = {
            "debt_to_equity_ttm": 1.0,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 3,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert any("Piotroski F-score" in f for f in flags)


class TestFactorScores:
    """Test combined factor scoring."""

    def test_calculate_factor_scores_basic(self):
        """Test basic factor score calculation."""
        metrics = {
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
        }
        
        config = {
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
        
        scores, details = calculate_factor_scores(metrics, config)
        
        assert "business_quality" in scores
        assert "valuation" in scores
        assert "financial_risk" in scores
        assert "growth" in scores
        assert "capital_allocation" in scores
        assert "total_score" in scores
        
        # All scores should be in valid range
        for key, value in scores.items():
            assert 0 <= value <= 100, f"{key} = {value} out of range"


class TestFundamentalEngine:
    """Test fundamental engine integration."""

    def test_extract_ticker_metrics(self):
        """Test metric extraction (requires mocked data)."""
        # This would require extensive mocking - skip for now
        pass
