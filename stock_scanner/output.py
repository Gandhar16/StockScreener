import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

def save_to_csv(df: pd.DataFrame, filepath: str) -> None:
    """
    Saves the scanner results DataFrame to a CSV file.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        clean_df = df.copy()

        # Drop dictionary/list columns to keep CSV clean
        cols_to_drop = [
            "graham_details", "fisher_details", "buffett_details",
            "business_quality_details", "valuation_details",
            "financial_risk_details", "growth_details", "capital_allocation_details",
            "strengths", "weaknesses", "risks", "red_flags",
            "support_zones", "resistance_zones", "support_trendlines", "resistance_trendlines", "technical_context",
            "long_term_support_trendlines", "long_term_resistance_trendlines",
            "short_term_support_trendlines", "short_term_resistance_trendlines"
        ]
        for col in cols_to_drop:
            if col in clean_df.columns:
                clean_df = clean_df.drop(columns=[col])

        clean_df.to_csv(filepath, index=False)
        logger.info(f"Results successfully saved to CSV: {filepath}")
    except Exception as e:
        logger.error(f"Failed to save CSV to {filepath}: {e}")

def generate_markdown_report(df: pd.DataFrame, mode: str) -> str:
    """
    Generates a beautifully formatted Markdown report with rating indicators and summaries.
    """
    if df.empty:
        return "# Stock Scanner Report\n\nNo stocks matched the criteria or data could not be fetched."

    md = []
    md.append("# 📊 US Stock Fundamental Scanner V2 Report")
    md.append(f"**Execution Mode:** {mode.upper()}")
    md.append("")
    md.append("## 🏆 Scan Summary Table")
    md.append("")

    # Table headers
    headers = [
        "Rank", "Ticker", "Sector", "Price ($)",
        "Quality", "Value", "Risk", "Growth", "Cap Alloc", "Total", "Rating", "Technical Context"
    ]
    md.append("| " + " | ".join(headers) + " |")
    md.append("|" + "|".join(["---"] * len(headers)) + "|")

    for i, (_, row) in enumerate(df.iterrows(), 1):
        ticker = row["ticker"]
        sector = row.get("sector", "General")
        price = f"{row.get('last_price', 0.0):.2f}"

        q_score = f"{row.get('business_quality_score', 50.0):.1f}"
        v_score = f"{row.get('valuation_score', 50.0):.1f}"
        r_score = f"{row.get('financial_risk_score', 50.0):.1f}"
        g_score = f"{row.get('growth_score', 50.0):.1f}"
        c_score = f"{row.get('capital_allocation_score', 50.0):.1f}"
        total = f"{row.get('total_score', 0.0):.1f}"

        # Determine rating emoji based on the rating bucket
        r_bucket = row.get("rating", "Hold / Neutral")
        if r_bucket == "Strong Buy":
            rating_str = "🟢 Strong Buy"
        elif r_bucket == "Buy":
            rating_str = "🟢 Buy"
        elif r_bucket == "Watchlist":
            rating_str = "🟡 Watchlist"
        elif r_bucket == "Hold / Neutral":
            rating_str = "🟡 Hold"
        elif r_bucket == "Avoid":
            rating_str = "🔴 Avoid"
        else:
            rating_str = "⚠️ High Risk"

        tech_context = row.get("technical_context", "N/A")

        row_data = [
            str(i), f"**{ticker}**", sector, price, q_score, v_score, r_score, g_score, c_score, f"**{total}**", rating_str, tech_context
        ]
        md.append("| " + " | ".join(row_data) + " |")

    md.append("")
    md.append("## 🔍 Deep-Dive Stock Analysis")
    md.append("")

    for _, row in df.iterrows():
        ticker = row["ticker"]
        sector = row.get("sector", "General")
        industry = row.get("industry", "N/A")
        rating = row.get("rating", "Hold / Neutral")
        category = row.get("category", "Average business, fair valuation")

        md.append(f"### 📈 {ticker} ({sector} - {industry})")
        md.append("")
        md.append(f"- **Current Price:** ${row.get('last_price', 0.0):.2f}")
        md.append(f"- **Final Score:** **{row.get('total_score', 0.0):.1f}/100**")
        md.append(f"- **Rating Recommendation:** **{rating}** ({category})")

        tech_context = row.get("technical_context", "N/A")
        md.append(f"- **Technical Context:** **{tech_context}**")
        md.append("")
        md.append("#### 🗺️ Market Structure & Horizontal Levels")

        supports = row.get("support_zones", [])
        if supports:
            md.append("- **Horizontal Support Zones (Top 3):**")
            for s in supports[:3]:
                md.append(f"  - Price Range: ${s['zone'][0]:.2f} - ${s['zone'][1]:.2f} (Touches: {s['touch_count']}, Recency: {s['recency']} days, Score: {s['strength_score']:.1f})")
        else:
            md.append("- **Horizontal Support Zones:** None detected")

        resistances = row.get("resistance_zones", [])
        if resistances:
            md.append("- **Horizontal Resistance Zones (Top 3):**")
            for r in resistances[:3]:
                md.append(f"  - Price Range: ${r['zone'][0]:.2f} - ${r['zone'][1]:.2f} (Touches: {r['touch_count']}, Recency: {r['recency']} days, Score: {r['strength_score']:.1f})")
        else:
            md.append("- **Horizontal Resistance Zones:** None detected")

        lt_s = row.get("long_term_support_trendlines", [])
        st_s = row.get("short_term_support_trendlines", [])
        if lt_s or st_s:
            md.append("- **Support Trendlines:**")
            for st in lt_s[:2]:
                md.append(f"  - Long-term: y = {st['slope']:.4f} * x + {st['intercept']:.2f} (Current Value: ${st['current_value']:.2f}, Touches: {st['touch_count']}, Score: {st['strength_score']:.1f})")
            for st in st_s[:2]:
                md.append(f"  - Short-term: y = {st['slope']:.4f} * x + {st['intercept']:.2f} (Current Value: ${st['current_value']:.2f}, Touches: {st['touch_count']}, Score: {st['strength_score']:.1f})")

        lt_r = row.get("long_term_resistance_trendlines", [])
        st_r = row.get("short_term_resistance_trendlines", [])
        if lt_r or st_r:
            md.append("- **Resistance Trendlines:**")
            for rt in lt_r[:2]:
                md.append(f"  - Long-term: y = {rt['slope']:.4f} * x + {rt['intercept']:.2f} (Current Value: ${rt['current_value']:.2f}, Touches: {rt['touch_count']}, Score: {rt['strength_score']:.1f})")
            for rt in st_r[:2]:
                md.append(f"  - Short-term: y = {rt['slope']:.4f} * x + {rt['intercept']:.2f} (Current Value: ${rt['current_value']:.2f}, Touches: {rt['touch_count']}, Score: {rt['strength_score']:.1f})")
        md.append("")

        # Sub-scores summary table
        md.append("#### 📊 Factor Scores Breakdown")
        md.append("| Quality | Valuation | Financial Risk | Growth | Capital Allocation |")
        md.append("| --- | --- | --- | --- | --- |")
        md.append(f"| {row.get('business_quality_score', 50.0):.1f}/100 | {row.get('valuation_score', 50.0):.1f}/100 | {row.get('financial_risk_score', 50.0):.1f}/100 | {row.get('growth_score', 50.0):.1f}/100 | {row.get('capital_allocation_score', 50.0):.1f}/100 |")
        md.append("")

        # Strengths & Weaknesses
        md.append("#### 🔑 Key Findings")
        md.append("")
        md.append("**Strengths:**")
        for strength in row.get("strengths", []):
            md.append(f"- {strength}")
        if not row.get("strengths"):
            md.append("- No major strengths noted.")

        md.append("")
        md.append("**Weaknesses / Risks:**")
        for weakness in row.get("weaknesses", []):
            md.append(f"- {weakness}")
        for risk in row.get("risks", []):
            md.append(f"- Risk: {risk}")
        if not row.get("weaknesses") and not row.get("risks"):
            md.append("- No major weaknesses or risks noted.")

        # V1 metrics (for quick reference / verification)
        md.append("")
        md.append("#### 🛡️ Reference Metrics")
        md.append(f"- Current Ratio: {row.get('current_ratio', 0.0):.2f}")
        md.append(f"- Debt-to-Equity: {row.get('debt_to_equity', 0.0):.2f}")
        md.append(f"- P/E Ratio: {row.get('pe_ratio', 0.0):.2f}")
        md.append(f"- ROIC: {row.get('roic_3y', 0.0)*100:.2f}%")
        md.append(f"- Operating Margin: {row.get('operating_margin', 0.0)*100:.2f}%")

        md.append("")
        md.append("---")
        md.append("")

    return "\n".join(md)

def save_to_markdown(df: pd.DataFrame, filepath: str, mode: str) -> None:
    """
    Generates and saves the Markdown report to a file.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        report = generate_markdown_report(df, mode)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info(f"Results successfully saved to Markdown: {filepath}")
    except Exception as e:
        logger.error(f"Failed to save Markdown to {filepath}: {e}")

def save_buys_to_excel(df: pd.DataFrame, filepath: str) -> None:
    """
    Filters the results for 'Buy' and 'Strong Buy' recommendations
    and saves them to an Excel spreadsheet.
    """
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if "rating" not in df.columns:
            logger.warning("No rating column found in dataframe; cannot filter buys for Excel.")
            return

        buy_df = df[df["rating"].isin(["Buy", "Strong Buy"])].copy()

        if buy_df.empty:
            logger.info("No 'Buy' or 'Strong Buy' recommendations to save to Excel.")
            empty_df = pd.DataFrame({"Message": ["No 'Buy' or 'Strong Buy' recommendations found in this scan."]})
            empty_df.to_excel(filepath, index=False, engine='openpyxl')
            return

        # Drop detail columns to keep the spreadsheet clean
        cols_to_drop = [
            "graham_details", "fisher_details", "buffett_details",
            "business_quality_details", "valuation_details",
            "financial_risk_details", "growth_details", "capital_allocation_details",
            "strengths", "weaknesses", "risks", "red_flags",
            "support_zones", "resistance_zones", "support_trendlines", "resistance_trendlines", "technical_context",
            "long_term_support_trendlines", "long_term_resistance_trendlines",
            "short_term_support_trendlines", "short_term_resistance_trendlines"
        ]
        for col in cols_to_drop:
            if col in buy_df.columns:
                buy_df = buy_df.drop(columns=[col])

        buy_df.to_excel(filepath, index=False, engine='openpyxl')
        logger.info(f"Buy recommendations successfully saved to Excel: {filepath}")
    except Exception as e:
        logger.error(f"Failed to save Excel to {filepath}: {e}")
