import logging
from typing import Dict, Any, List, Tuple
import pandas as pd

logger = logging.getLogger(__name__)

def generate_decision(
    scores: Dict[str, float],
    red_flags: List[str],
    is_disqualified: bool,
    metrics: Dict[str, Any],
    sector: str
) -> Tuple[str, str, List[str], List[str], List[str]]:
    """
    Generates rating, category classification (e.g., "Great business, poor price"),
    key strengths, key weaknesses, and primary risks.
    """
    bq = scores.get("business_quality", 50.0)
    val = scores.get("valuation", 50.0)
    risk = scores.get("financial_risk", 50.0)
    growth = scores.get("growth", 50.0)
    
    strengths = []
    weaknesses = []
    risks = []
    
    # 1. Determine Rating and Category
    if is_disqualified:
        rating = "Avoid"
        category = "Disqualified due to high structural risk / Avoid"
    elif bq >= 70.0 and val >= 65.0 and risk >= 55.0:
        rating = "Strong Buy"
        category = "High-quality and attractively valued"
    elif bq >= 70.0 and val < 45.0:
        rating = "Watchlist"
        category = "Great business, poor price"
    elif bq >= 50.0 and val >= 60.0 and risk >= 50.0:
        rating = "Buy"
        category = "Average business, attractive valuation"
    elif bq < 45.0 and val < 45.0:
        rating = "Avoid"
        category = "Low-quality and expensive / Avoid"
    elif risk < 45.0:
        rating = "High Risk / Special Situation"
        category = "High financial/leverage risk"
    else:
        rating = "Hold / Neutral"
        category = "Average business, fair valuation"
        
    # 2. Extract Strengths and Weaknesses
    # Quality indicators
    roe = metrics.get("roe_3y_avg", 0.0)
    roic = metrics.get("roic_3y_avg", 0.0)
    op_margin = metrics.get("operating_margin_ttm", 0.0)
    gross_margin = metrics.get("gross_margin_ttm", 0.0)
    
    if bq >= 70.0:
        strengths.append(f"Exceptional business quality: ROIC/ROE of {max(roic, roe)*100:.1f}% and strong operating margins of {op_margin*100:.1f}%.")
    elif bq < 45.0:
        weaknesses.append(f"Subpar profitability: Low ROIC/ROE of {max(roic, roe)*100:.1f}% and thin margins.")
        
    # Valuation indicators
    pe = metrics.get("pe_ratio_ttm", 0.0)
    forward_pe = metrics.get("forward_pe", 0.0)
    if val >= 70.0:
        strengths.append(f"Highly attractive valuation: Trading at a reasonable P/E of {pe:.1f} (Forward P/E of {forward_pe:.1f}).")
    elif val < 40.0:
        weaknesses.append(f"Premium valuation: Stock is priced for perfection with P/E of {pe:.1f} (Forward P/E of {forward_pe:.1f}).")
        
    # Financial risk indicators
    de = metrics.get("debt_to_equity_ttm", 0.0)
    curr_ratio = metrics.get("current_ratio_ttm", 0.0)
    if risk >= 75.0:
        strengths.append("Robust balance sheet: Low debt levels and strong short-term liquidity.")
    elif risk < 50.0:
        weaknesses.append(f"Leverage concerns: Debt-to-Equity is elevated at {de:.2f} and liquidity margins are thin.")
        
    # Growth indicators
    rev_g = metrics.get("revenue_growth_3y_avg", 0.0)
    eps_g = metrics.get("eps_growth_3y_avg", 0.0)
    if growth >= 70.0:
        strengths.append(f"Strong, durable growth profile: 3-year revenue growth average is {rev_g*100:.1f}% and EPS growth is {eps_g*100:.1f}%.")
    elif growth < 45.0:
        weaknesses.append("Stagnant growth profile: Revenue and earnings growth rates are low or negative.")
        
    # 3. Identify Risks
    if red_flags:
        risks.extend(red_flags)
    else:
        if risk < 55.0:
            risks.append("Debt levels are slightly elevated and could present risk in an economic downturn.")
        if growth < 50.0 and val > 60.0:
            risks.append("Slowing growth may lead to multiple contraction.")
        if "utility" in sector.lower() or "energy" in sector.lower():
            risks.append("Regulated returns or commodity prices represent major macro sensitivities.")
        if not risks:
            risks.append("Standard market risks and potential execution delays in new product initiatives.")

    # 4. Fill in placeholders if empty
    if not strengths:
        strengths.append("Stable operational performance in line with peer group averages.")
    if not weaknesses:
        weaknesses.append("No material operational or balance sheet weaknesses identified.")
        
    return rating, category, strengths, weaknesses, risks
