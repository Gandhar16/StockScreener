import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

DEFAULT_SECTOR_CONFIGS: Dict[str, Dict[str, Any]] = {
    "Software/SaaS": {
        "relevant_metrics": ["revenue_growth", "gross_margin", "fcf_margin", "shares_growth", "rule_of_40"],
        "irrelevant_metrics": ["current_ratio", "debt_to_equity", "price_to_book"],
        "preferred_valuation_methods": ["price_to_sales", "price_to_fcf", "ev_to_sales", "ev_to_fcf"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 1.0, "max_net_debt_to_ebitda": 2.0},
        "cycle_sensitivity": 0.1,
        "weights": {
            "business_quality": 0.35,
            "valuation": 0.25,
            "financial_risk": 0.15,
            "growth": 0.20,
            "capital_allocation": 0.05
        }
    },
    "Semiconductors": {
        "relevant_metrics": ["normalized_margins", "capex_intensity", "inventory_turnover", "forward_pe", "revenue_growth"],
        "irrelevant_metrics": ["price_to_sales", "current_ratio"],
        "preferred_valuation_methods": ["forward_pe", "ev_to_ebitda", "price_to_fcf"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 1.2, "max_net_debt_to_ebitda": 2.5},
        "cycle_sensitivity": 0.9,
        "weights": {
            "business_quality": 0.30,
            "valuation": 0.25,
            "financial_risk": 0.15,
            "growth": 0.15,
            "capital_allocation": 0.15
        }
    },
    "Banks/Financials": {
        "relevant_metrics": ["roe", "equity_multiplier", "price_to_book", "dividend_yield", "operating_margin"],
        "irrelevant_metrics": ["current_ratio", "debt_to_equity", "fcf_to_net_income", "ev_to_ebitda", "price_to_sales", "gross_margin"],
        "preferred_valuation_methods": ["price_to_book", "price_to_earnings"],
        "acceptable_leverage_framework": {"max_equity_multiplier": 15.0},
        "cycle_sensitivity": 0.5,
        "weights": {
            "business_quality": 0.35,
            "valuation": 0.30,
            "financial_risk": 0.20,
            "growth": 0.10,
            "capital_allocation": 0.05
        }
    },
    "Utilities": {
        "relevant_metrics": ["interest_coverage", "roic_stability", "dividend_payout", "debt_to_equity"],
        "irrelevant_metrics": ["revenue_growth", "rd_intensity", "price_to_sales"],
        "preferred_valuation_methods": ["ev_to_ebitda", "price_to_earnings", "dividend_yield"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 3.0, "min_interest_coverage": 1.5},
        "cycle_sensitivity": 0.1,
        "weights": {
            "business_quality": 0.25,
            "valuation": 0.25,
            "financial_risk": 0.30,
            "growth": 0.05,
            "capital_allocation": 0.15
        }
    },
    "Consumer Staples": {
        "relevant_metrics": ["gross_margin", "operating_margin", "roic", "fcf_conversion", "revenue_growth"],
        "irrelevant_metrics": ["rd_intensity", "price_to_sales"],
        "preferred_valuation_methods": ["price_to_earnings", "ev_to_ebitda", "price_to_fcf"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 1.8},
        "cycle_sensitivity": 0.2,
        "weights": {
            "business_quality": 0.35,
            "valuation": 0.25,
            "financial_risk": 0.15,
            "growth": 0.15,
            "capital_allocation": 0.10
        }
    },
    "Industrials": {
        "relevant_metrics": ["roic", "operating_margin", "capex_intensity", "revenue_growth", "debt_to_equity"],
        "irrelevant_metrics": ["rd_intensity", "price_to_sales"],
        "preferred_valuation_methods": ["ev_to_ebitda", "price_to_earnings", "price_to_fcf"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 1.5, "min_interest_coverage": 2.5},
        "cycle_sensitivity": 0.7,
        "weights": {
            "business_quality": 0.30,
            "valuation": 0.25,
            "financial_risk": 0.20,
            "growth": 0.15,
            "capital_allocation": 0.10
        }
    },
    "Energy/Commodities": {
        "relevant_metrics": ["normalized_margins", "capex_intensity", "net_debt_to_ebitda", "dividend_yield", "debt_to_equity"],
        "irrelevant_metrics": ["rd_intensity", "price_to_sales", "current_ratio"],
        "preferred_valuation_methods": ["ev_to_ebitda", "price_to_cash_flow", "price_to_book"],
        "acceptable_leverage_framework": {"max_net_debt_to_ebitda": 2.5, "max_debt_to_equity": 1.5},
        "cycle_sensitivity": 1.0,
        "weights": {
            "business_quality": 0.25,
            "valuation": 0.25,
            "financial_risk": 0.25,
            "growth": 0.10,
            "capital_allocation": 0.15
        }
    },
    "Healthcare/Pharma": {
        "relevant_metrics": ["rd_intensity", "gross_margin", "operating_margin", "revenue_growth", "roic"],
        "irrelevant_metrics": ["debt_to_equity"],
        "preferred_valuation_methods": ["forward_pe", "ev_to_ebitda", "price_to_earnings"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 1.2},
        "cycle_sensitivity": 0.3,
        "weights": {
            "business_quality": 0.30,
            "valuation": 0.25,
            "financial_risk": 0.15,
            "growth": 0.20,
            "capital_allocation": 0.10
        }
    },
    "General": {
        "relevant_metrics": ["revenue_growth", "eps_growth", "current_ratio", "debt_to_equity", "pe_ratio", "roic", "operating_margin", "fcf_to_net_income"],
        "irrelevant_metrics": [],
        "preferred_valuation_methods": ["price_to_earnings", "ev_to_ebitda", "price_to_fcf"],
        "acceptable_leverage_framework": {"max_debt_to_equity": 2.0},
        "cycle_sensitivity": 0.4,
        "weights": {
            "business_quality": 0.35,
            "valuation": 0.30,
            "financial_risk": 0.20,
            "growth": 0.15,
            "capital_allocation": 0.00 # Subsumed in others for backward compatibility
        }
    }
}

def get_sector_config(sector_name: str, industry_name: str = "") -> Dict[str, Any]:
    """
    Resolves the sector and industry details to the best-matching sector config.
    """
    if not sector_name:
        return DEFAULT_SECTOR_CONFIGS["General"]
        
    s_clean = str(sector_name).strip().lower()
    ind_clean = str(industry_name).strip().lower() if industry_name else ""
    
    # Check technology sector specifically to distinguish Software from Semiconductors
    if "technology" in s_clean:
        if "semiconductor" in ind_clean:
            return DEFAULT_SECTOR_CONFIGS["Semiconductors"]
        else:
            return DEFAULT_SECTOR_CONFIGS["Software/SaaS"]
            
    if "financial" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Banks/Financials"]
        
    if "utilities" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Utilities"]
        
    if "consumer defensive" in s_clean or "consumer staple" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Consumer Staples"]
        
    if "industrials" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Industrials"]
        
    if "energy" in s_clean or "commodity" in s_clean or "basic materials" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Energy/Commodities"]
        
    if "healthcare" in s_clean:
        return DEFAULT_SECTOR_CONFIGS["Healthcare/Pharma"]
        
    # Fallbacks based on string matching
    for key in DEFAULT_SECTOR_CONFIGS:
        if key.lower() in s_clean or s_clean in key.lower():
            return DEFAULT_SECTOR_CONFIGS[key]
            
    return DEFAULT_SECTOR_CONFIGS["General"]
