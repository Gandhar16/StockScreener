import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

def check_red_flags(
    metrics: dict[str, Any],
    sector: str
) -> tuple[bool, float, list[str]]:
    """
    Checks for structural, financial, and accounting red flags.
    Returns:
        is_disqualified: True if the risk is severe enough to exclude the stock.
        total_penalty: The sum of score penalties to apply.
        flags: A list of descriptive warning flags.
    """
    is_disqualified = False
    total_penalty = 0.0
    flags = []

    is_financial = "bank" in sector.lower() or "financial" in sector.lower()

    # 1. Going Concern Risk (Negative Equity and Negative Operating Cash Flow)
    assets = metrics.get("assets_ttm", 1.0)
    liabilities = metrics.get("liabilities_ttm", 0.0)
    ocf_ttm = metrics.get("ocf_ttm", 1.0)

    if not pd.isna(assets) and not pd.isna(liabilities) and assets <= liabilities:
        if is_financial:
            # Financials have unique balance sheets - negative equity is bad, but cash flow check is skipped
            total_penalty += 30.0
            flags.append("Going Concern warning: Negative Equity (Liabilities exceed Assets)")
        else:
            if not pd.isna(ocf_ttm) and ocf_ttm < 0:
                is_disqualified = True
                flags.append("Going Concern: Negative Equity and Negative Operating Cash Flow")
            else:
                total_penalty += 30.0
                flags.append("Going Concern warning: Negative Equity (Liabilities exceed Assets)")

    # 2. Persistent Negative Operating Cash Flow (Skip for Financials/Banks)
    if not is_financial:
        ocf_3y = metrics.get("ocf_3y_avg", 0.0)
        if not pd.isna(ocf_3y) and ocf_3y < 0:
            total_penalty += 20.0
            flags.append("Persistent cash outflow: 3-year average Operating Cash Flow is negative")

    # 3. Dangerous Leverage
    if is_financial:
        equity_mult = metrics.get("equity_multiplier_ttm", 1.0)
        if not pd.isna(equity_mult) and equity_mult > 20.0:
            is_disqualified = True
            flags.append(f"Dangerous Bank Leverage: Equity Multiplier of {equity_mult:.2f} exceeds 20.0")
        elif not pd.isna(equity_mult) and equity_mult > 15.0:
            total_penalty += 20.0
            flags.append(f"High Bank Leverage: Equity Multiplier of {equity_mult:.2f} exceeds 15.0")
    else:
        de = metrics.get("debt_to_equity_ttm", 0.0)
        net_debt_ebitda = metrics.get("net_debt_to_ebitda_ttm", 0.0)

        if not pd.isna(de) and de > 3.0:
            is_disqualified = True
            flags.append(f"Dangerous Leverage: Debt-to-Equity of {de:.2f} exceeds 3.0")
        elif not pd.isna(de) and de > 2.0:
            total_penalty += 15.0
            flags.append(f"High Leverage: Debt-to-Equity of {de:.2f} exceeds 2.0")

        if not pd.isna(net_debt_ebitda) and net_debt_ebitda > 5.0:
            total_penalty += 20.0
            flags.append(f"High Net Debt/EBITDA: leverage ratio of {net_debt_ebitda:.2f} exceeds 5.0")

    # 4. Weak Interest Coverage (only for non-financials)
    if not is_financial:
        interest_cov = metrics.get("interest_coverage_ttm", 10.0)
        if not pd.isna(interest_cov) and interest_cov < 1.5:
            if interest_cov < 0:
                total_penalty += 25.0
                flags.append("Severe Interest Coverage: Negative operating income relative to interest costs")
            else:
                total_penalty += 20.0
                flags.append(f"Weak Interest Coverage: Interest coverage of {interest_cov:.2f} is under 1.5")

    # 5. Accounting Quality / Earnings Quality (Skip for Financials/Banks)
    if not is_financial:
        fcf_net_inc_3y = metrics.get("fcf_to_net_income_3y_avg", 1.0)
        net_inc_3y = metrics.get("net_income_3y_avg", 1.0)
        if not pd.isna(fcf_net_inc_3y) and fcf_net_inc_3y < 0.3 and not pd.isna(net_inc_3y) and net_inc_3y > 0:
            total_penalty += 15.0
            flags.append(f"Poor Earnings Quality: 3-year FCF/Net Income of {fcf_net_inc_3y:.2f} suggests net income not backed by cash flow")

    # 5b. High Accruals (Skip for Financials/Banks): earnings far ahead of
    # operating cash relative to the asset base — classic Sloan-accruals risk.
    if not is_financial:
        accruals = metrics.get("accruals_ratio", float("nan"))
        if not pd.isna(accruals) and accruals > 0.10:
            total_penalty += 15.0
            flags.append(f"High Accruals: (NI - OCF)/Assets of {accruals:.2f} exceeds 0.10 — earnings not cash-backed")

    # 6. Excessive Dilution
    shares_growth = metrics.get("shares_growth_3y", 0.0)
    if not pd.isna(shares_growth) and shares_growth > 0.15: # >15% over 3 years (~5% CAGR)
        total_penalty += 15.0
        flags.append(f"Excessive Dilution: Outstanding shares increased by {shares_growth*100:.1f}% over 3 years")

    # 7. Liquidity Stress / Maturity (only for non-financials)
    if not is_financial:
        curr_ratio = metrics.get("current_ratio_ttm", 1.5)
        if not pd.isna(curr_ratio) and curr_ratio < 0.8:
            total_penalty += 15.0
            flags.append(f"Liquidity Stress: Current ratio of {curr_ratio:.2f} is below 0.8")

    return is_disqualified, total_penalty, flags
