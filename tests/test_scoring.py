"""Unit tests for scoring engine and core modules."""

import pytest
import pandas as pd
import numpy as np
from stock_scanner.engine.scoring import (
    calculate_factor_scores,
    linear_scale,
)
from stock_scanner.engine.risk_flags import check_red_flags
from stock_scanner.engine.fundamental import FundamentalEngine


class TestLinearScale:
    """Test the linear_scale function."""

    def test_higher_is_better_basic(self):
        """Test basic higher-is-better scaling."""
        assert linear_scale(50, 0, 100, True) == 50
        assert linear_scale(0, 0, 100, True) == 0
        assert linear_scale(100, 0, 100, True) == 100
        assert linear_scale(150, 0, 100, True) == 100
        assert linear_scale(-50, 0, 100, True) == 0

    def test_lower_is_better_basic(self):
        """Test basic lower-is-better scaling."""
        assert linear_scale(50, 0, 100, False) == 50
        assert linear_scale(0, 0, 100, False) == 100
        assert linear_scale(100, 0, 100, False) == 0
        assert linear_scale(-50, 0, 100, False) == 100

    def test_nan_handling(self):
        """Test NaN handling returns neutral score."""
        assert linear_scale(float("nan"), 0, 100, True) == 50
        assert linear_scale(None, 0, 100, True) == 50
        assert linear_scale(10, 10, 10) == 100


class TestRiskFlags:
    """Test red flag detection."""

    def test_dangerous_leverage_flag(self):
        """Test dangerous leverage (>3.0) triggers disqualification."""
        metrics = {
            "debt_to_equity_ttm": 5.0,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert is_disq is True
        assert any("Dangerous Leverage" in f for f in flags)

    def test_high_leverage_flag(self):
        """Test high leverage (2.0-3.0) triggers penalty."""
        metrics = {
            "debt_to_equity_ttm": 2.5,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Technology")
        assert is_disq is False
        assert penalty >= 15
        assert any("High Leverage" in f for f in flags)

    def test_liquidity_stress_flag(self):
        """Test low current ratio triggers liquidity stress."""
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
        assert any("Liquidity Stress" in f for f in flags)

    def test_bank_leverage(self):
        """Test bank leverage uses equity multiplier."""
        metrics = {
            "equity_multiplier_ttm": 25.0,
            "debt_to_equity_ttm": 1.0,
            "current_ratio_ttm": 1.5,
            "pe_ratio_ttm": 15,
            "net_debt_to_ebitda_ttm": 2.0,
            "interest_coverage_ttm": 5.0,
            "rev_cagr_stability": 0.2,
            "piotroski_f": 7,
            "piotroski_max": 9,
        }
        is_disq, penalty, flags = check_red_flags(metrics, "Financial Services")
        assert is_disq is True
        assert any("Dangerous Bank Leverage" in f for f in flags)


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
            "relevant_metrics": ["current_ratio", "debt_to_equity", "pe_ratio", "revenue_growth_yoy", "eps_growth_yoy", "rd_intensity", "roic", "operating_margin", "fcf_to_net_income"],
            "irrelevant_metrics": [],
            "preferred_valuation_methods": ["price_to_earnings"],
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
        # total_score is computed by caller, not returned by calculate_factor_scores
        
        for key, value in scores.items():
            if key != "total_score":
                assert 0 <= value <= 100, f"{key} = {value} out of range"
        
        # total_score is computed by the caller (e.g., FundamentalEngine), not returned by calculate_factor_scores
        assert "business_quality_details" in details
        assert "valuation_details" in details
        assert "financial_risk_details" in details
        assert "growth_details" in details
        assert "capital_allocation_details" in details


class TestFactorScoresEdgeCases:
    """Test edge cases in factor scoring."""

    def test_missing_metrics(self):
        """Test handling of missing metrics."""
        metrics = {
            "current_ratio_ttm": 2.0,
            "debt_to_equity_ttm": 0.5,
            # Missing many metrics
        }
        
        config = {
            "relevant_metrics": ["current_ratio", "debt_to_equity", "pe_ratio", "revenue_growth_yoy", "eps_growth_yoy", "rd_intensity", "roic", "operating_margin", "fcf_to_net_income"],
            "irrelevant_metrics": [],
            "preferred_valuation_methods": ["price_to_earnings"],
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
        # total_score is computed by caller, not returned by calculate_factor_scores


class TestFundamentalEngine:
    """Test fundamental engine integration."""

    def test_extract_ticker_metrics(self):
        """Test metric extraction (requires mocked data)."""
        pass
