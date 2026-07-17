import logging
import math
import time
import pandas as pd
import yfinance as yf
from typing import List, Dict, Any, Optional

from stock_scanner.config import ScannerConfig
from stock_scanner.data.provider import DataProvider
from stock_scanner.engine.sector_config import get_sector_config
from stock_scanner.engine.risk_flags import check_red_flags
from stock_scanner.engine.scoring import calculate_factor_scores
from stock_scanner.engine.explanation import generate_decision

logger = logging.getLogger(__name__)


def _get_val_as_of_year(series: pd.Series, as_of_year: Optional[int]) -> float:
    if series.empty:
        return float('nan')
    series = series.dropna()
    if series.empty:
        return float('nan')
    if as_of_year is None:
        return float(series.iloc[-1])
    valid_years = []
    for idx in series.index:
        try:
            y = int(str(idx).split('-')[0])
            if y <= as_of_year:
                valid_years.append((y, idx))
        except ValueError:
            pass
    if not valid_years:
        return float('nan')
    best_y, best_idx = max(valid_years, key=lambda x: x[0])
    return float(series.loc[best_idx])


def _get_avg_val_as_of_year(series: pd.Series, n: int, as_of_year: Optional[int]) -> float:
    if series.empty:
        return float('nan')
    series = series.dropna()
    if series.empty:
        return float('nan')
    if as_of_year is not None:
        valid_indices = []
        for idx in series.index:
            try:
                y = int(str(idx).split('-')[0])
                if y <= as_of_year:
                    valid_indices.append(idx)
            except ValueError:
                pass
        series = series.loc[valid_indices]
        if series.empty:
            return float('nan')
    return float(series.iloc[-n:].mean())


class FundamentalEngine:
    def __init__(self, config: ScannerConfig):
        self.config = config
        self.provider = DataProvider(config)

    def analyze_tickers(self, tickers: List[str], as_of_year: Optional[int] = None) -> pd.DataFrame:
        if not tickers:
            logger.warning("No tickers passed to fundamental engine.")
            return pd.DataFrame()
        batch_size = self.config.batch.size
        delay = self.config.batch.delay_seconds
        all_dfs = []
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i : i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1}: {batch_tickers} (As Of: {as_of_year})")
            try:
                batch_df = self._analyze_batch(batch_tickers, as_of_year=as_of_year)
                if not batch_df.empty:
                    all_dfs.append(batch_df)
            except Exception as e:
                logger.error(f"Error processing fundamental batch {batch_tickers}: {e}", exc_info=True)
            if i + batch_size < len(tickers) and delay > 0:
                logger.info(f"Sleeping for {delay} seconds to stay under rate limits...")
                time.sleep(delay)
        if not all_dfs:
            return pd.DataFrame()
        combined_df = pd.concat(all_dfs, ignore_index=True)
        if not combined_df.empty:
            combined_df = self._apply_peer_percentiles(combined_df)
            combined_df = combined_df.sort_values(by="total_score", ascending=False).reset_index(drop=True)
        return combined_df

    def _analyze_batch(self, tickers: List[str], as_of_year: Optional[int] = None) -> pd.DataFrame:
        logger.info(f"Fetching yfinance data for {len(tickers)} tickers...")
        try:
            tk = yf.Tickers(tickers)
        except Exception as e:
            logger.error(f"Failed to initialize yfinance for {tickers}: {e}")
            return pd.DataFrame()
        records = []
        for ticker in tickers:
            try:
                yf_ticker = yf.Ticker(ticker)
                yf_info = yf_ticker.info or {}
                sector = yf_info.get("sector", "General")
                industry = yf_info.get("industry", "")
                metrics = self._extract_ticker_metrics(ticker=ticker, yf_info=yf_info, as_of_year=as_of_year)
                sect_config = None
                if self.config.sector_profiles and sector in self.config.sector_profiles:
                    prof = self.config.sector_profiles[sector]
                    is_fin = "financial" in sector.lower() or "bank" in sector.lower()
                    if is_fin:
                        relevant_metrics = ["roe", "equity_multiplier", "price_to_book", "dividend_yield", "operating_margin"]
                        irrelevant_metrics = ["current_ratio", "debt_to_equity", "fcf_to_net_income", "ev_to_ebitda", "price_to_sales", "gross_margin"]
                        pref_val_methods = ["price_to_book", "price_to_earnings"]
                    else:
                        relevant_metrics = list(self.config.scoring_ranges.model_fields.keys())
                        irrelevant_metrics = []
                        pref_val_methods = ["price_to_earnings"]
                    sect_config = {
                        "relevant_metrics": relevant_metrics,
                        "irrelevant_metrics": irrelevant_metrics,
                        "preferred_valuation_methods": pref_val_methods,
                        "weights": {
                            "business_quality": self.config.weights.buffett_quality,
                            "valuation": self.config.weights.graham_safety * 0.6,
                            "financial_risk": self.config.weights.graham_safety * 0.4,
                            "growth": self.config.weights.fisher_growth,
                            "capital_allocation": 0.0
                        },
                        "scoring_ranges": self.config.scoring_ranges.model_dump() if hasattr(self.config.scoring_ranges, "model_dump") else self.config.scoring_ranges
                    }
                if not sect_config:
                    sect_config = get_sector_config(sector, industry)
                    if hasattr(self.config, "scoring_ranges") and self.config.scoring_ranges:
                        sect_config["scoring_ranges"] = self.config.scoring_ranges.model_dump() if hasattr(self.config.scoring_ranges, "model_dump") else self.config.scoring_ranges
                    if hasattr(self.config, "weights") and self.config.weights:
                        sect_config["weights"] = {
                            "business_quality": self.config.weights.buffett_quality,
                            "valuation": self.config.weights.graham_safety * 0.6,
                            "financial_risk": self.config.weights.graham_safety * 0.4,
                            "growth": self.config.weights.fisher_growth,
                            "capital_allocation": 0.0
                        }
                is_disq, penalty, flags = check_red_flags(metrics, sector)
                if is_disq and self.config.mode == "market_scan":
                    logger.info(f"{ticker} disqualified due to red flags: {flags}")
                    continue
                scores, details = calculate_factor_scores(metrics, sect_config)
                for key in scores:
                    scores[key] = max(0.0, scores[key] - penalty)
                w = sect_config.get("weights", {})
                total_score = (
                    scores.get("business_quality", 50.0) * w.get("business_quality", 0.25) +
                    scores.get("valuation", 50.0) * w.get("valuation", 0.25) +
                    scores.get("financial_risk", 50.0) * w.get("financial_risk", 0.20) +
                    scores.get("growth", 50.0) * w.get("growth", 0.20) +
                    scores.get("capital_allocation", 50.0) * w.get("capital_allocation", 0.10)
                )
                rating, category, strengths, weaknesses, risks = generate_decision(
                    scores=scores, red_flags=flags, is_disqualified=is_disq, metrics=metrics, sector=sector
                )
                graham_score = (scores.get("valuation", 50.0) + scores.get("financial_risk", 50.0)) / 2.0
                fisher_score = scores.get("growth", 50.0)
                buffett_score = scores.get("business_quality", 50.0)
                graham_details = {
                    "current_ratio_score": details["financial_risk_details"].get("current_ratio_score", 50.0),
                    "debt_to_equity_score": details["financial_risk_details"].get("debt_to_equity_score", 50.0),
                    "pe_score": details["valuation_details"].get("pe_score", 50.0)
                }
                fisher_details = {
                    "revenue_growth_score": details["growth_details"].get("revenue_growth_score", 50.0),
                    "eps_growth_score": details["growth_details"].get("eps_growth_score", 50.0),
                    "rd_intensity_score": details["capital_allocation_details"].get("reinvestment_score", 50.0)
                }
                buffett_details = {
                    "roic_score": details["business_quality_details"].get("roic_score", 50.0),
                    "operating_margin_score": details["business_quality_details"].get("operating_margin_score", 50.0),
                    "fcf_net_income_score": details["business_quality_details"].get("earnings_quality_score", 50.0)
                }
                records.append({
                    "ticker": ticker,
                    "current_ratio": metrics.get("current_ratio_ttm"),
                    "debt_to_equity": metrics.get("debt_to_equity_ttm"),
                    "pe_ratio": metrics.get("pe_ratio_ttm"),
                    "revenue_growth_3y": metrics.get("revenue_growth_3y_avg"),
                    "eps_growth_3y": metrics.get("eps_growth_3y_avg"),
                    "rd_intensity": metrics.get("rd_intensity"),
                    "roic_3y": metrics.get("roic_3y_avg"),
                    "operating_margin": metrics.get("operating_margin_ttm"),
                    "fcf_to_net_income": metrics.get("fcf_to_net_income_ttm"),
                    "graham_score": graham_score,
                    "fisher_score": fisher_score,
                    "buffett_score": buffett_score,
                    "graham_details": graham_details,
                    "fisher_details": fisher_details,
                    "buffett_details": buffett_details,
                    "business_quality_score": scores.get("business_quality", 50.0),
                    "valuation_score": scores.get("valuation", 50.0),
                    "financial_risk_score": scores.get("financial_risk", 50.0),
                    "growth_score": scores.get("growth", 50.0),
                    "capital_allocation_score": scores.get("capital_allocation", 50.0),
                    "total_score": total_score,
                    "rating": rating,
                    "category": category,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "risks": risks,
                    "red_flags": flags,
                    "is_disqualified": is_disq,
                    "sector": sector,
                    "industry": industry,
                    "accruals_ratio": metrics.get("accruals_ratio"),
                    "rev_cagr_stability": metrics.get("rev_cagr_stability"),
                    "piotroski_f": metrics.get("piotroski_f"),
                    "piotroski_max": metrics.get("piotroski_max"),
                    "ev_to_ebitda": metrics.get("ev_to_ebitda"),
                    "_w_valuation": 0.25,
                })
            except Exception as e:
                logger.error(f"Error analyzing fundamentals for {ticker}: {e}", exc_info=True)
        result_df = pd.DataFrame(records)
        if not result_df.empty:
            result_df = result_df.sort_values(by="total_score", ascending=False).reset_index(drop=True)
        return result_df


    def _apply_peer_percentiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply peer group percentiles for sector-relative scoring."""
        if df.empty:
            return df
        # Add percentile columns for key metrics
        for col in ["pe_ratio", "price_to_book", "ev_to_ebitda", "price_to_sales", 
                    "roe_ttm", "roic_ttm", "operating_margin_ttm", "revenue_growth_ttm"]:
            if col in df.columns:
                df[f"{col}_pct"] = df[col].rank(pct=True) * 100
        return df


    def _extract_ticker_metrics(self, ticker: str, yf_info: dict, as_of_year: Optional[int] = None) -> Dict[str, Any]:
        metrics = {}
        def latest(series: pd.Series) -> float:
            return _get_val_as_of_year(series, as_of_year)
        def avg(series: pd.Series, n: int) -> float:
            return _get_avg_val_as_of_year(series, n, as_of_year)
        try:
            yf_ticker = yf.Ticker(ticker)
            inc_df = yf_ticker.income_stmt
            bal_df = yf_ticker.balance_sheet
            cf_df = yf_ticker.cashflow
            def get_series(df: pd.DataFrame, metric_name: str) -> pd.Series:
                if df is None or df.empty:
                    return pd.Series(dtype=float)
                if metric_name in df.index:
                    return df.loc[metric_name].dropna()
                for idx in df.index:
                    if metric_name.lower() in idx.lower():
                        return df.loc[idx].dropna()
                return pd.Series(dtype=float)
            def get_latest(series: pd.Series) -> float:
                return _get_val_as_of_year(series, as_of_year)
            def get_avg(series: pd.Series, n: int) -> float:
                return _get_avg_val_as_of_year(series, n, as_of_year)
            # 1. Ratio Data from yfinance info
            metrics["current_ratio_ttm"] = yf_info.get("currentRatio", float("nan"))
            metrics["debt_to_equity_ttm"] = yf_info.get("debtToEquity", float("nan"))
            metrics["pe_ratio_ttm"] = yf_info.get("trailingPE", float("nan"))
            metrics["forward_pe"] = yf_info.get("forwardPE", float("nan"))
            metrics["peg_ratio"] = yf_info.get("pegRatio", float("nan"))
            metrics["price_to_book"] = yf_info.get("priceToBook", float("nan"))
            metrics["ev_to_ebitda"] = yf_info.get("enterpriseToEbitda", float("nan"))
            metrics["price_to_sales"] = yf_info.get("priceToSalesTrailing12Months", float("nan"))
            metrics["price_to_fcf"] = yf_info.get("marketCap", 0) / max(yf_info.get("freeCashflow", 1), 1) if yf_info.get("freeCashflow") else float("nan")
            metrics["dividend_yield"] = yf_info.get("dividendYield", float("nan"))
            metrics["operating_margin_ttm"] = yf_info.get("operatingMargins", float("nan"))
            metrics["gross_margin_ttm"] = yf_info.get("grossMargins", float("nan"))
            metrics["roe_ttm"] = yf_info.get("returnOnEquity", float("nan"))
            metrics["roe_3y_avg"] = yf_info.get("returnOnEquity", float("nan"))
            metrics["roic_ttm"] = yf_info.get("returnOnInvestedCapital", float("nan"))
            metrics["roic_3y_avg"] = yf_info.get("returnOnInvestedCapital", float("nan"))
            metrics["equity_multiplier_ttm"] = float("nan")
            metrics["interest_coverage_ttm"] = float("nan")
            metrics["net_debt_to_ebitda_ttm"] = float("nan")
            metrics["dividend_payout_ratio"] = yf_info.get("payoutRatio", float("nan"))
            metrics["fcf_to_net_income_ttm"] = float("nan")
            return metrics
        except Exception as e:
            logger.warning(f"Failed to extract metrics for {ticker}: {e}")
            return {}
