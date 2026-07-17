import logging
import math
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

def linear_scale(val: float, min_val: float, max_val: float, higher_is_better: bool = True) -> float:
    """
    Normalizes a metric value between 0.0 and 100.0.
    """
    if pd.isna(val) or val is None or math.isnan(val):
        return 50.0  # Return neutral score for missing data

    if min_val == max_val:
        return 100.0 if (val >= min_val if higher_is_better else val <= min_val) else 0.0

    if higher_is_better:
        if val >= max_val:
            return 100.0
        if val <= min_val:
            return 0.0
        return (val - min_val) / (max_val - min_val) * 100.0
    else:
        if val <= min_val:
            return 100.0
        if val >= max_val:
            return 0.0
        return (max_val - val) / (max_val - min_val) * 100.0

def calculate_factor_scores(
    metrics: dict[str, Any],
    config: dict[str, Any],
    qualitative: dict[str, Any] | None = None,
    peer_percentiles: dict[str, float] | None = None
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """
    Calculates sub-scores from 0 to 100 for the five investment factors:
    1. Business Quality
    2. Valuation
    3. Financial Risk
    4. Growth
    5. Capital Allocation

    Returns:
        scores: Dict of factor scores (e.g. {"business_quality": 85.0, ...})
        details: Dict of individual metric scores for explainability
    """
    details = {}
    scores = {}

    relevant = config.get("relevant_metrics", [])
    irrelevant = config.get("irrelevant_metrics", [])
    pref_val = config.get("preferred_valuation_methods", ["price_to_earnings"])
    scoring_ranges = config.get("scoring_ranges", {})

    def get_range(metric_name: str, default_range: list) -> tuple[float, float]:
        r = scoring_ranges.get(metric_name, default_range)
        if isinstance(r, (list, tuple)) and len(r) == 2:
            return float(r[0]), float(r[1])
        return float(default_range[0]), float(default_range[1])

    # ----------------------------------------------------
    # 1. BUSINESS QUALITY SCORE
    # ----------------------------------------------------
    quality_scores = {}

    # ROIC or ROE
    is_financial = "roe" in relevant or "equity_multiplier" in relevant
    if is_financial:
        roe = metrics.get("roe_3y_avg", metrics.get("roe_ttm"))
        roe_range = get_range("roic", [0.05, 0.15])
        quality_scores["roe_score"] = linear_scale(roe, roe_range[0], roe_range[1], higher_is_better=True)
    else:
        roic = metrics.get("roic_3y_avg", metrics.get("roic_ttm"))
        roic_range = get_range("roic", [0.05, 0.20])
        quality_scores["roic_score"] = linear_scale(roic, roic_range[0], roic_range[1], higher_is_better=True)

    # Margins
    op_margin = metrics.get("operating_margin_ttm")
    default_op_margin = [0.10, 0.30] if "operating_margin" in relevant and "software" in str(config).lower() else [0.05, 0.25]
    op_margin_range = get_range("operating_margin", default_op_margin)
    quality_scores["operating_margin_score"] = linear_scale(op_margin, op_margin_range[0], op_margin_range[1], higher_is_better=True)

    if "gross_margin" not in irrelevant:
        gross_margin = metrics.get("gross_margin_ttm")
        gross_margin_range = get_range("gross_margin", [0.20, 0.70])
        quality_scores["gross_margin_score"] = linear_scale(gross_margin, gross_margin_range[0], gross_margin_range[1], higher_is_better=True)

    # Earnings Quality
    if "fcf_to_net_income" not in irrelevant:
        fcf_net_inc = metrics.get("fcf_to_net_income_ttm")
        if pd.isna(fcf_net_inc) or math.isnan(fcf_net_inc):
            fcf_s = 50.0
        elif fcf_net_inc >= 1.0:
            fcf_s = 100.0
        elif fcf_net_inc <= 0.0:
            fcf_s = 0.0
        else:
            fcf_s = fcf_net_inc * 100.0
        # Blend in accruals when available: high (NI - OCF)/assets means paper
        # earnings; low/negative accruals confirm cash-backed earnings.
        accruals = metrics.get("accruals_ratio")
        if accruals is not None and not pd.isna(accruals):
            accruals_s = linear_scale(accruals, -0.05, 0.15, higher_is_better=False)
            fcf_s = 0.6 * fcf_s + 0.4 * accruals_s
            quality_scores["accruals_score"] = accruals_s
        quality_scores["earnings_quality_score"] = fcf_s

    # Piotroski F-score as a quality cross-check (only when enough of the 9
    # signals were computable to be meaningful).
    piotroski = metrics.get("piotroski_f")
    piotroski_max = metrics.get("piotroski_max", 0)
    if piotroski is not None and piotroski_max and piotroski_max >= 5:
        quality_scores["piotroski_score"] = piotroski / piotroski_max * 100.0

    # Qualitative Moat & Management Quality (if provided)
    if qualitative:
        if "moat_score" in qualitative and qualitative["moat_score"] is not None:
            quality_scores["moat_score"] = qualitative["moat_score"] * 10.0 # scale 0-10 to 0-100
        if "management_quality" in qualitative and qualitative["management_quality"] is not None:
            quality_scores["management_score"] = qualitative["management_quality"] * 10.0

    # Calculate average
    scores["business_quality"] = sum(quality_scores.values()) / len(quality_scores) if quality_scores else 50.0
    details["business_quality_details"] = quality_scores

    # ----------------------------------------------------
    # 2. VALUATION SCORE
    # ----------------------------------------------------
    val_scores = {}

    # Candidate methods
    pe = metrics.get("pe_ratio_ttm")
    forward_pe = metrics.get("forward_pe")
    peg = metrics.get("peg_ratio")
    ev_ebitda = metrics.get("ev_to_ebitda")
    pb = metrics.get("price_to_book")
    ps = metrics.get("price_to_sales")
    p_fcf = metrics.get("price_to_fcf")

    pe_range = get_range("pe_ratio", [10.0, 30.0])

    # PE ratio score
    if not pd.isna(pe) and pe > 0:
        val_scores["pe_score"] = linear_scale(pe, pe_range[0], pe_range[1], higher_is_better=False)
    elif not pd.isna(pe) and pe <= 0:
        val_scores["pe_score"] = 0.0

    # Forward PE score
    if not pd.isna(forward_pe) and forward_pe > 0:
        val_scores["forward_pe_score"] = linear_scale(forward_pe, pe_range[0], pe_range[1], higher_is_better=False)
    elif not pd.isna(forward_pe) and forward_pe <= 0:
        val_scores["forward_pe_score"] = 0.0

    # PEG score
    if not pd.isna(peg):
        peg_range = get_range("peg_ratio", [0.5, 2.0])
        val_scores["peg_score"] = linear_scale(peg, peg_range[0], peg_range[1], higher_is_better=False)

    # EV/EBITDA score
    if not pd.isna(ev_ebitda) and ev_ebitda > 0:
        ev_ebitda_range = get_range("ev_to_ebitda", [6.0, 18.0])
        val_scores["ev_ebitda_score"] = linear_scale(ev_ebitda, ev_ebitda_range[0], ev_ebitda_range[1], higher_is_better=False)

    # Price to Book score
    if not pd.isna(pb):
        pb_range = get_range("price_to_book", [0.8, 3.5])
        val_scores["pb_score"] = linear_scale(pb, pb_range[0], pb_range[1], higher_is_better=False)

    # Price to Sales score
    if not pd.isna(ps):
        ps_range = get_range("price_to_sales", [1.5, 8.0])
        val_scores["ps_score"] = linear_scale(ps, ps_range[0], ps_range[1], higher_is_better=False)

    # Price to FCF score
    if not pd.isna(p_fcf) and p_fcf > 0:
        p_fcf_range = get_range("price_to_fcf", [10.0, 30.0])
        val_scores["p_fcf_score"] = linear_scale(p_fcf, p_fcf_range[0], p_fcf_range[1], higher_is_better=False)

    # Use preferred methods first, then fallback to whatever exists
    preferred_scores = {k: v for k, v in val_scores.items() if any(method in k for method in pref_val)}
    if preferred_scores:
        scores["valuation"] = sum(preferred_scores.values()) / len(preferred_scores)
    elif val_scores:
        scores["valuation"] = sum(val_scores.values()) / len(val_scores)
    else:
        scores["valuation"] = 50.0

    # Sector-relative blend: when peer percentiles are supplied (percentile of
    # cheapness vs same-sector peers in the scanned batch, 0-100 where 100 is
    # cheapest), blend 50/50 with the absolute-range score. "Cheap for its
    # sector" matters as much as "cheap in absolute terms".
    if peer_percentiles:
        peer_vals = [v for v in peer_percentiles.values()
                     if v is not None and not pd.isna(v)]
        if peer_vals:
            peer_score = sum(peer_vals) / len(peer_vals)
            val_scores["peer_relative_score"] = peer_score
            scores["valuation"] = 0.5 * scores["valuation"] + 0.5 * peer_score

    details["valuation_details"] = val_scores

    # ----------------------------------------------------
    # 3. FINANCIAL RISK SCORE
    # ----------------------------------------------------
    risk_scores = {}

    if "current_ratio" not in irrelevant:
        cr = metrics.get("current_ratio_ttm")
        cr_range = get_range("current_ratio", [1.0, 2.5])
        risk_scores["current_ratio_score"] = linear_scale(cr, cr_range[0], cr_range[1], higher_is_better=True)

    if "debt_to_equity" not in irrelevant:
        de = metrics.get("debt_to_equity_ttm")
        de_range = get_range("debt_to_equity", [0.5, 2.0])
        risk_scores["debt_to_equity_score"] = linear_scale(de, de_range[0], de_range[1], higher_is_better=False)

    if "equity_multiplier" in relevant:
        em = metrics.get("equity_multiplier_ttm")
        em_range = get_range("equity_multiplier", [5.0, 15.0])
        risk_scores["equity_multiplier_score"] = linear_scale(em, em_range[0], em_range[1], higher_is_better=False)

    if "interest_coverage" in relevant or not is_financial:
        interest_cov = metrics.get("interest_coverage_ttm")
        if not pd.isna(interest_cov):
            ic_range = get_range("interest_coverage", [1.5, 6.0])
            risk_scores["interest_coverage_score"] = linear_scale(interest_cov, ic_range[0], ic_range[1], higher_is_better=True)

    if "net_debt_to_ebitda" in relevant:
        nd_ebitda = metrics.get("net_debt_to_ebitda_ttm")
        nd_range = get_range("net_debt_to_ebitda", [1.0, 4.0])
        risk_scores["net_debt_ebitda_score"] = linear_scale(nd_ebitda, nd_range[0], nd_range[1], higher_is_better=False)

    scores["financial_risk"] = sum(risk_scores.values()) / len(risk_scores) if risk_scores else 50.0
    details["financial_risk_details"] = risk_scores

    # ----------------------------------------------------
    # 4. GROWTH SCORE
    # ----------------------------------------------------
    growth_scores = {}

    rev_g = metrics.get("revenue_growth_3y_avg", metrics.get("revenue_growth_ttm"))
    rev_range = get_range("revenue_growth_yoy", [0.0, 0.15])
    growth_scores["revenue_growth_score"] = linear_scale(rev_g, rev_range[0], rev_range[1], higher_is_better=True)

    eps_g = metrics.get("eps_growth_3y_avg", metrics.get("eps_growth_ttm"))
    eps_range = get_range("eps_growth_yoy", [0.0, 0.15])
    growth_scores["eps_growth_score"] = linear_scale(eps_g, eps_range[0], eps_range[1], higher_is_better=True)

    fcf_g = metrics.get("fcf_growth_3y_avg")
    if not pd.isna(fcf_g):
        growth_scores["fcf_growth_score"] = linear_scale(fcf_g, 0.0, 0.15, higher_is_better=True)

    margin_exp = metrics.get("margin_expansion")
    if not pd.isna(margin_exp):
        growth_scores["margin_expansion_score"] = linear_scale(margin_exp, -0.05, 0.05, higher_is_better=True)

    # Growth durability: coefficient of variation of YoY revenue growth —
    # steady compounding (CV < 0.5) beats one-year spikes (CV > 2).
    stability = metrics.get("rev_cagr_stability")
    if stability is not None and not pd.isna(stability):
        growth_scores["growth_durability_score"] = linear_scale(
            stability, 0.3, 2.0, higher_is_better=False)

    scores["growth"] = sum(growth_scores.values()) / len(growth_scores) if growth_scores else 50.0
    details["growth_details"] = growth_scores

    # ----------------------------------------------------
    # 5. CAPITAL ALLOCATION SCORE
    # ----------------------------------------------------
    cap_scores = {}

    # Dilution (shares growth: lower or negative is better)
    shares_growth = metrics.get("shares_growth_3y")
    cap_scores["dilution_score"] = linear_scale(shares_growth, 0.0, 0.05, higher_is_better=False)

    # Dividend safety (safety: target range, yield)
    div_yield = metrics.get("dividend_yield")
    if not pd.isna(div_yield):
        cap_scores["dividend_yield_score"] = linear_scale(div_yield, 0.0, 0.05, higher_is_better=True)

    div_payout = metrics.get("dividend_payout_ratio")
    if not pd.isna(div_payout):
        # Sweet spot is 20% to 60%. Above 80% is risky, below 0 is negative.
        if div_payout >= 0.20 and div_payout <= 0.60:
            payout_s = 100.0
        elif div_payout > 0.80 or div_payout < 0:
            payout_s = 0.0
        else:
            payout_s = linear_scale(abs(div_payout - 0.40), 0.0, 0.40, higher_is_better=False)
        cap_scores["payout_safety_score"] = payout_s

    # Reinvestment (ROIC proxy)
    roic = metrics.get("roic_3y_avg", metrics.get("roic_ttm"))
    if not pd.isna(roic):
        cap_scores["reinvestment_score"] = linear_scale(roic, 0.05, 0.15, higher_is_better=True)

    # Qualitative capital discipline
    if qualitative and "capital_allocation" in qualitative and qualitative["capital_allocation"] is not None:
        cap_scores["allocation_discipline_score"] = qualitative["capital_allocation"] * 10.0

    scores["capital_allocation"] = sum(cap_scores.values()) / len(cap_scores) if cap_scores else 50.0
    details["capital_allocation_details"] = cap_scores

    return scores, details
