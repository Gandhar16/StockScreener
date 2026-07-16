import logging
import math
import time
import pandas as pd
import yfinance as yf
import financetoolkit as ft
from typing import List, Dict, Any, Tuple, Optional

from stock_scanner.config import ScannerConfig
from stock_scanner.engine.sector_config import get_sector_config
from stock_scanner.engine.risk_flags import check_red_flags
from stock_scanner.engine.scoring import calculate_factor_scores
from stock_scanner.engine.explanation import generate_decision

logger = logging.getLogger(__name__)

# Helper functions for robust data extraction
def get_metric_series(df: pd.DataFrame, ticker: str, metric_name: str) -> pd.Series:
    """
    Robustly extracts a metric time series for a ticker from FinanceToolkit DataFrames.
    Supports MultiIndex indices (Ticker, Metric) and MultiIndex columns (Ticker, Year).
    """
    if df.empty:
        return pd.Series(dtype=float)
    
    t_lower = ticker.lower()
    m_lower = metric_name.lower()
    
    # Case 1: Index is a MultiIndex where first level is ticker and second is metric
    if isinstance(df.index, pd.MultiIndex):
        try:
            first_level_vals = [str(x).lower() for x in df.index.levels[0]]
            if t_lower in first_level_vals:
                ticker_df = df.xs(ticker, level=0)
                # Find matching metric row
                for idx in ticker_df.index:
                    if str(idx).lower() == m_lower:
                        return ticker_df.loc[idx]
        except Exception:
            pass
            
    # Case 2: Index contains metric names and columns are MultiIndex of (Ticker, Year)
    found_metric = None
    for idx in df.index:
        if isinstance(idx, tuple):
            if len(idx) == 2 and str(idx[0]).lower() == t_lower and str(idx[1]).lower() == m_lower:
                return df.loc[idx]
        elif str(idx).lower() == m_lower:
            found_metric = idx
            break
            
    if found_metric is not None:
        row = df.loc[found_metric]
        if isinstance(row.index, pd.MultiIndex):
            try:
                return row.xs(ticker, level=0)
            except KeyError:
                pass
        return row
        
    return pd.Series(dtype=float)

def get_ratio_series(df: pd.DataFrame, ticker: str) -> pd.Series:
    """
    Robustly extracts a ratio time series for a ticker.
    """
    if df.empty:
        return pd.Series(dtype=float)
        
    t_lower = ticker.lower()
    
    # Case 1: Simple index of tickers
    for idx in df.index:
        if isinstance(idx, str) and idx.lower() == t_lower:
            return df.loc[idx]
            
    # Case 2: MultiIndex index where first level is ticker
    if isinstance(df.index, pd.MultiIndex):
        try:
            ticker_df = df.xs(ticker, level=0)
            if not ticker_df.empty:
                return ticker_df.iloc[0]
        except Exception:
            pass
            
    # Case 3: Columns are MultiIndex of (Ticker, Year)
    if isinstance(df.columns, pd.MultiIndex):
        try:
            return df.xs(ticker, axis=1, level=0).iloc[0]
        except Exception:
            pass
            
    return pd.Series(dtype=float)

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
            # Handle string or period indices (e.g. "2023" or 2023)
            y = int(str(idx).split('-')[0])
            if y <= as_of_year:
                valid_years.append((y, idx))
        except ValueError:
            pass
            
    if not valid_years:
        return float('nan')
        
    # Pick the closest year <= as_of_year
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

def _get_latest_val(series: pd.Series, as_of_year: Optional[int] = None) -> float:
    return _get_val_as_of_year(series, as_of_year)

def _get_avg_val(series: pd.Series, n: int, as_of_year: Optional[int] = None) -> float:
    return _get_avg_val_as_of_year(series, n, as_of_year)

class FundamentalEngine:
    """
    FundamentalEngine V2: Sector-aware, risk-aware, factor-style equity scoring.
    Supports point-in-time historical backtesting via as_of_year.
    """
    def __init__(self, config: ScannerConfig):
        self.config = config

    def analyze_tickers(self, tickers: List[str], as_of_year: Optional[int] = None) -> pd.DataFrame:
        """
        Runs full fundamental scoring and filtering on the given tickers in batches.
        Returns a sorted DataFrame of qualifying stocks.
        """
        if not tickers:
            logger.warning("No tickers passed to fundamental engine.")
            return pd.DataFrame()

        batch_size = self.config.batch.size
        delay = self.config.batch.delay_seconds

        all_dfs = []
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i : i + batch_size]
            logger.info(f"Processing V2 batch {i//batch_size + 1} of {(len(tickers) + batch_size - 1)//batch_size}: {batch_tickers} (As Of: {as_of_year})")
            
            try:
                batch_df = self._analyze_batch(batch_tickers, as_of_year=as_of_year)
                if not batch_df.empty:
                    all_dfs.append(batch_df)
            except Exception as e:
                logger.error(f"Error processing fundamental batch {batch_tickers}: {e}", exc_info=True)

            # Sleep between batches if this is not the last batch
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

    @staticmethod
    def compute_peer_percentiles(df: pd.DataFrame,
                                 min_group: int = 4) -> pd.Series:
        """
        Percentile of cheapness vs same-sector peers in the scanned batch,
        0-100 where 100 = cheapest. Averages the P/E and EV/EBITDA percentile
        ranks (lower multiple = higher percentile). NaN where the sector group
        is smaller than min_group or both multiples are missing.
        No extra data fetches — uses columns already in the results frame.
        """
        out = pd.Series(float("nan"), index=df.index)
        if "sector" not in df.columns:
            return out
        for _, group_idx in df.groupby("sector").groups.items():
            group = df.loc[group_idx]
            if len(group) < min_group:
                continue
            ranks = []
            for col in ("pe_ratio", "ev_to_ebitda"):
                if col not in group.columns:
                    continue
                vals = pd.to_numeric(group[col], errors="coerce")
                vals = vals.where(vals > 0)  # negative multiples = not meaningful
                if vals.notna().sum() < min_group:
                    continue
                # ascending=False percentile of expensiveness → invert so
                # cheaper gets closer to 100
                pct = (1.0 - vals.rank(pct=True)) * 100.0
                ranks.append(pct)
            if ranks:
                combined = pd.concat(ranks, axis=1).mean(axis=1)
                out.loc[combined.index] = combined
        return out

    def _apply_peer_percentiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Second pass over the combined results: blend each stock's absolute
        valuation score 50/50 with its sector-relative cheapness percentile
        and propagate the delta into total_score.
        """
        try:
            peer_pct = self.compute_peer_percentiles(df)
            df["peer_valuation_percentile"] = peer_pct.round(1)
            has_peer = peer_pct.notna() & df["valuation_score"].notna()
            if has_peer.any():
                old_val = df.loc[has_peer, "valuation_score"].astype(float)
                new_val = 0.5 * old_val + 0.5 * peer_pct[has_peer]
                w_val = pd.to_numeric(
                    df.loc[has_peer].get("_w_valuation", 0.25), errors="coerce"
                ).fillna(0.25)
                df.loc[has_peer, "valuation_score"] = new_val
                df.loc[has_peer, "total_score"] = (
                    df.loc[has_peer, "total_score"].astype(float)
                    + w_val * (new_val - old_val)
                )
        except Exception as e:
            logger.warning(f"Peer percentile pass skipped: {e}")
        if "_w_valuation" in df.columns:
            df = df.drop(columns=["_w_valuation"])
        return df

    def _analyze_batch(self, tickers: List[str], as_of_year: Optional[int] = None) -> pd.DataFrame:
        """
        Performs fundamental analysis on a single batch of tickers.
        """
        logger.info(f"Initializing FinanceToolkit for {len(tickers)} tickers...")
        try:
            tk = ft.Toolkit(tickers, api_key='')
        except Exception as e:
            logger.error(f"Failed to initialize FinanceToolkit: {e}")
            return pd.DataFrame()

        # Fetch statement data
        logger.info("Retrieving financial statement data...")
        inc_df = self._safe_toolkit_call(tk.get_income_statement)
        bal_df = self._safe_toolkit_call(tk.get_balance_sheet_statement)
        cf_df = self._safe_toolkit_call(tk.get_cash_flow_statement)

        # Fetch ratio data
        logger.info("Retrieving ratios...")
        current_ratio_df = self._safe_toolkit_call(tk.ratios.get_current_ratio)
        debt_to_equity_df = self._safe_toolkit_call(tk.ratios.get_debt_to_equity_ratio)
        pe_ratio_df = self._safe_toolkit_call(tk.ratios.get_price_to_earnings_ratio)
        roic_df = self._safe_toolkit_call(tk.ratios.get_return_on_invested_capital)
        op_margin_df = self._safe_toolkit_call(tk.ratios.get_operating_margin)
        
        # New V2 ratio data
        pb_df = self._safe_toolkit_call(tk.ratios.get_price_to_book_ratio)
        ev_ebitda_df = self._safe_toolkit_call(tk.ratios.get_ev_to_ebitda_ratio)
        gross_margin_df = self._safe_toolkit_call(tk.ratios.get_gross_margin)
        roe_df = self._safe_toolkit_call(tk.ratios.get_return_on_equity)
        equity_multiplier_df = self._safe_toolkit_call(tk.ratios.get_equity_multiplier)
        interest_cov_df = self._safe_toolkit_call(tk.ratios.get_interest_coverage_ratio)
        net_debt_ebitda_df = self._safe_toolkit_call(tk.ratios.get_net_debt_to_ebitda_ratio)
        dividend_payout_df = self._safe_toolkit_call(tk.ratios.get_dividend_payout_ratio)
        p_fcf_df = self._safe_toolkit_call(tk.ratios.get_price_to_free_cash_flow_ratio)

        records = []
        for ticker in tickers:
            try:
                # 1. Fetch yfinance info (sector, industry, PEG, forward PE)
                logger.info(f"Fetching yfinance info for {ticker}...")
                try:
                    yf_ticker = yf.Ticker(ticker)
                    yf_info = yf_ticker.info or {}
                except Exception as e:
                    logger.warning(f"Failed to fetch yfinance info for {ticker}: {e}")
                    yf_info = {}

                sector = yf_info.get("sector", "General")
                industry = yf_info.get("industry", "")
                
                # 2. Extract metrics dictionary
                metrics = self._extract_ticker_metrics(
                    ticker=ticker,
                    yf_info=yf_info,
                    inc_df=inc_df,
                    bal_df=bal_df,
                    cf_df=cf_df,
                    current_ratio_df=current_ratio_df,
                    debt_to_equity_df=debt_to_equity_df,
                    pe_ratio_df=pe_ratio_df,
                    roic_df=roic_df,
                    op_margin_df=op_margin_df,
                    pb_df=pb_df,
                    ev_ebitda_df=ev_ebitda_df,
                    gross_margin_df=gross_margin_df,
                    roe_df=roe_df,
                    equity_multiplier_df=equity_multiplier_df,
                    interest_cov_df=interest_cov_df,
                    net_debt_ebitda_df=net_debt_ebitda_df,
                    dividend_payout_df=dividend_payout_df,
                    p_fcf_df=p_fcf_df,
                    as_of_year=as_of_year
                )

                # 3. Resolve sector config
                sect_config = None
                if self.config.sector_profiles and sector in self.config.sector_profiles:
                    prof = self.config.sector_profiles[sector]
                    is_fin = "financial" in sector.lower() or "bank" in sector.lower() or prof.weights.graham_safety.current_ratio == 0.0
                    
                    if is_fin:
                        relevant_metrics = ["roe", "equity_multiplier", "price_to_book", "dividend_yield", "operating_margin"]
                        irrelevant_metrics = ["current_ratio", "debt_to_equity", "fcf_to_net_income", "ev_to_ebitda", "price_to_sales", "gross_margin"]
                        pref_val_methods = ["price_to_book", "price_to_earnings"]
                    else:
                        relevant_metrics = list(prof.scoring_ranges.model_fields.keys())
                        irrelevant_metrics = []
                        pref_val_methods = ["price_to_earnings"]
                        
                    sect_config = {
                        "relevant_metrics": relevant_metrics,
                        "irrelevant_metrics": irrelevant_metrics,
                        "preferred_valuation_methods": pref_val_methods,
                        "weights": {
                            "business_quality": prof.weights.category_weights.buffett_quality,
                            "valuation": prof.weights.category_weights.graham_safety * 0.6,
                            "financial_risk": prof.weights.category_weights.graham_safety * 0.4,
                            "growth": prof.weights.category_weights.fisher_growth,
                            "capital_allocation": 0.0
                        },
                        "scoring_ranges": prof.scoring_ranges.model_dump() if hasattr(prof.scoring_ranges, "model_dump") else prof.scoring_ranges
                    }
                if not sect_config:
                    sect_config = get_sector_config(sector, industry)
                    if hasattr(self.config, "scoring_ranges") and self.config.scoring_ranges:
                        sect_config["scoring_ranges"] = self.config.scoring_ranges.model_dump() if hasattr(self.config.scoring_ranges, "model_dump") else self.config.scoring_ranges
                    if hasattr(self.config, "weights") and self.config.weights:
                        sect_config["weights"] = {
                            "business_quality": self.config.weights.category_weights.buffett_quality,
                            "valuation": self.config.weights.category_weights.graham_safety * 0.6,
                            "financial_risk": self.config.weights.category_weights.graham_safety * 0.4,
                            "growth": self.config.weights.category_weights.fisher_growth,
                            "capital_allocation": 0.0
                        }

                # 4. Red flag check
                is_disq, penalty, flags = check_red_flags(metrics, sector)
                
                if is_disq and self.config.mode == "market_scan":
                    logger.info(f"{ticker} disqualified due to red flags: {flags}")
                    continue

                # 5. Factor scoring
                scores, details = calculate_factor_scores(metrics, sect_config)
                
                # Apply red-flag penalty
                for key in scores:
                    scores[key] = max(0.0, scores[key] - penalty)

                # 6. Calculate total score
                w = sect_config.get("weights", {})
                total_score = (
                    scores.get("business_quality", 50.0) * w.get("business_quality", 0.25) +
                    scores.get("valuation", 50.0) * w.get("valuation", 0.25) +
                    scores.get("financial_risk", 50.0) * w.get("financial_risk", 0.20) +
                    scores.get("growth", 50.0) * w.get("growth", 0.20) +
                    scores.get("capital_allocation", 50.0) * w.get("capital_allocation", 0.10)
                )

                # 7. Generate qualitative analysis rating & text
                rating, category, strengths, weaknesses, risks = generate_decision(
                    scores=scores,
                    red_flags=flags,
                    is_disqualified=is_disq,
                    metrics=metrics,
                    sector=sector
                )

                # 8. Backward-compatible mapping for V1 tests/outputs
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
                    # V1 metrics
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
                    
                    # V2 sub-scores
                    "business_quality_score": scores.get("business_quality", 50.0),
                    "valuation_score": scores.get("valuation", 50.0),
                    "financial_risk_score": scores.get("financial_risk", 50.0),
                    "growth_score": scores.get("growth", 50.0),
                    "capital_allocation_score": scores.get("capital_allocation", 50.0),
                    "total_score": total_score,
                    
                    # V2 explanation & rating details
                    "rating": rating,
                    "category": category,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "risks": risks,
                    "red_flags": flags,
                    "is_disqualified": is_disq,
                    "sector": sector,
                    "industry": industry,

                    # V3 trader-grade additions (additive)
                    "accruals_ratio": metrics.get("accruals_ratio"),
                    "rev_cagr_stability": metrics.get("rev_cagr_stability"),
                    "piotroski_f": metrics.get("piotroski_f"),
                    "piotroski_max": metrics.get("piotroski_max"),
                    "ev_to_ebitda": metrics.get("ev_to_ebitda"),
                    "_w_valuation": w.get("valuation", 0.25),
                })
            except Exception as e:
                logger.error(f"Error analyzing fundamentals for {ticker}: {e}", exc_info=True)

        result_df = pd.DataFrame(records)
        if not result_df.empty:
            result_df = result_df.sort_values(by="total_score", ascending=False).reset_index(drop=True)
        return result_df

    def _safe_toolkit_call(self, method) -> pd.DataFrame:
        """
        Executes a FinanceToolkit call safely, returning an empty DataFrame if it fails.
        """
        try:
            return method()
        except Exception as e:
            logger.debug(f"FinanceToolkit method {method.__name__} failed or not supported: {e}")
            return pd.DataFrame()

    def fetch_raw_data(self, tickers: List[str], as_of_year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetches all financial statement and ratio DataFrames for the tickers batch,
        and returns a list of dictionaries containing raw metrics and metadata.
        """
        if not tickers:
            return []
            
        logger.info(f"Fetching raw data for optimization batch: {tickers} (As Of: {as_of_year})")
        try:
            tk = ft.Toolkit(tickers, api_key='')
        except Exception as e:
            logger.error(f"Failed to initialize FinanceToolkit: {e}")
            return []

        inc_df = self._safe_toolkit_call(tk.get_income_statement)
        bal_df = self._safe_toolkit_call(tk.get_balance_sheet_statement)
        cf_df = self._safe_toolkit_call(tk.get_cash_flow_statement)

        current_ratio_df = self._safe_toolkit_call(tk.ratios.get_current_ratio)
        debt_to_equity_df = self._safe_toolkit_call(tk.ratios.get_debt_to_equity_ratio)
        pe_ratio_df = self._safe_toolkit_call(tk.ratios.get_price_to_earnings_ratio)
        roic_df = self._safe_toolkit_call(tk.ratios.get_return_on_invested_capital)
        op_margin_df = self._safe_toolkit_call(tk.ratios.get_operating_margin)
        
        pb_df = self._safe_toolkit_call(tk.ratios.get_price_to_book_ratio)
        ev_ebitda_df = self._safe_toolkit_call(tk.ratios.get_ev_to_ebitda_ratio)
        gross_margin_df = self._safe_toolkit_call(tk.ratios.get_gross_margin)
        roe_df = self._safe_toolkit_call(tk.ratios.get_return_on_equity)
        equity_multiplier_df = self._safe_toolkit_call(tk.ratios.get_equity_multiplier)
        interest_cov_df = self._safe_toolkit_call(tk.ratios.get_interest_coverage_ratio)
        net_debt_ebitda_df = self._safe_toolkit_call(tk.ratios.get_net_debt_to_ebitda_ratio)
        dividend_payout_df = self._safe_toolkit_call(tk.ratios.get_dividend_payout_ratio)
        p_fcf_df = self._safe_toolkit_call(tk.ratios.get_price_to_free_cash_flow_ratio)

        results = []
        for ticker in tickers:
            try:
                try:
                    yf_ticker = yf.Ticker(ticker)
                    yf_info = yf_ticker.info or {}
                except Exception as e:
                    logger.warning(f"Failed to fetch yfinance info for {ticker}: {e}")
                    yf_info = {}

                sector = yf_info.get("sector", "General")
                industry = yf_info.get("industry", "")
                
                metrics = self._extract_ticker_metrics(
                    ticker=ticker,
                    yf_info=yf_info,
                    inc_df=inc_df,
                    bal_df=bal_df,
                    cf_df=cf_df,
                    current_ratio_df=current_ratio_df,
                    debt_to_equity_df=debt_to_equity_df,
                    pe_ratio_df=pe_ratio_df,
                    roic_df=roic_df,
                    op_margin_df=op_margin_df,
                    pb_df=pb_df,
                    ev_ebitda_df=ev_ebitda_df,
                    gross_margin_df=gross_margin_df,
                    roe_df=roe_df,
                    equity_multiplier_df=equity_multiplier_df,
                    interest_cov_df=interest_cov_df,
                    net_debt_ebitda_df=net_debt_ebitda_df,
                    dividend_payout_df=dividend_payout_df,
                    p_fcf_df=p_fcf_df,
                    as_of_year=as_of_year
                )
                
                # Check red flags
                is_disq, penalty, flags = check_red_flags(metrics, sector)
                
                results.append({
                    "ticker": ticker,
                    "sector": sector,
                    "industry": industry,
                    "metrics": metrics,
                    "is_disqualified": is_disq,
                    "red_flag_penalty": penalty,
                    "red_flags": flags
                })
            except Exception as e:
                logger.error(f"Error extracting raw data for {ticker}: {e}")
                
        return results

    def _extract_ticker_metrics(
        self,
        ticker: str,
        yf_info: dict,
        inc_df: pd.DataFrame,
        bal_df: pd.DataFrame,
        cf_df: pd.DataFrame,
        current_ratio_df: pd.DataFrame,
        debt_to_equity_df: pd.DataFrame,
        pe_ratio_df: pd.DataFrame,
        roic_df: pd.DataFrame,
        op_margin_df: pd.DataFrame,
        pb_df: pd.DataFrame,
        ev_ebitda_df: pd.DataFrame,
        gross_margin_df: pd.DataFrame,
        roe_df: pd.DataFrame,
        equity_multiplier_df: pd.DataFrame,
        interest_cov_df: pd.DataFrame,
        net_debt_ebitda_df: pd.DataFrame,
        dividend_payout_df: pd.DataFrame,
        p_fcf_df: pd.DataFrame,
        as_of_year: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Extracts and prepares all numerical metrics required for V2 scoring and red-flag checks.
        """
        metrics = {}
        
        # Local closures to automatically bind as_of_year
        def latest(series: pd.Series) -> float:
            return _get_val_as_of_year(series, as_of_year)
            
        def avg(series: pd.Series, n: int) -> float:
            return _get_avg_val_as_of_year(series, n, as_of_year)

        # 1. Ratio Data
        cr_series = get_ratio_series(current_ratio_df, ticker)
        de_series = get_ratio_series(debt_to_equity_df, ticker)
        pe_series = get_ratio_series(pe_ratio_df, ticker)
        roic_series = get_ratio_series(roic_df, ticker)
        op_margin_series = get_ratio_series(op_margin_df, ticker)
        
        # V2 specific ratios
        pb_series = get_ratio_series(pb_df, ticker)
        ev_ebitda_series = get_ratio_series(ev_ebitda_df, ticker)
        gross_margin_series = get_ratio_series(gross_margin_df, ticker)
        roe_series = get_ratio_series(roe_df, ticker)
        equity_mult_series = get_ratio_series(equity_multiplier_df, ticker)
        interest_cov_series = get_ratio_series(interest_cov_df, ticker)
        net_debt_ebitda_series = get_ratio_series(net_debt_ebitda_df, ticker)
        dividend_payout_series = get_ratio_series(dividend_payout_df, ticker)
        p_fcf_series = get_ratio_series(p_fcf_df, ticker)

        # 2. Extract latest and averages
        metrics["current_ratio_ttm"] = latest(cr_series)
        metrics["debt_to_equity_ttm"] = latest(de_series)
        metrics["pe_ratio_ttm"] = latest(pe_series)
        
        # Try yfinance fallback for values that might be missing in statements
        metrics["forward_pe"] = yf_info.get("forwardPE", float("nan"))
        metrics["peg_ratio"] = yf_info.get("pegRatio", float("nan"))
        metrics["price_to_book"] = latest(pb_series) or yf_info.get("priceToBook", float("nan"))
        metrics["ev_to_ebitda"] = latest(ev_ebitda_series) or yf_info.get("enterpriseToEbitda", float("nan"))
        metrics["price_to_sales"] = yf_info.get("priceToSalesTrailing12Months", float("nan"))
        metrics["price_to_fcf"] = latest(p_fcf_series)
        metrics["dividend_yield"] = yf_info.get("dividendYield", float("nan"))

        metrics["operating_margin_ttm"] = latest(op_margin_series)
        metrics["gross_margin_ttm"] = latest(gross_margin_series)
        
        metrics["roe_ttm"] = latest(roe_series)
        metrics["roe_3y_avg"] = avg(roe_series, 3)
        metrics["roic_ttm"] = latest(roic_series)
        metrics["roic_3y_avg"] = avg(roic_series, 3)
        
        metrics["equity_multiplier_ttm"] = latest(equity_mult_series)
        metrics["interest_coverage_ttm"] = latest(interest_cov_series)
        metrics["net_debt_to_ebitda_ttm"] = latest(net_debt_ebitda_series)
        metrics["dividend_payout_ratio"] = latest(dividend_payout_series)

        # 3. Financial Statement Data
        ocf_series = get_metric_series(cf_df, ticker, "Operating Cash Flow")
        if ocf_series.empty:
            ocf_series = get_metric_series(cf_df, ticker, "Cash Flow from Operations")
            
        capex_series = get_metric_series(cf_df, ticker, "Capital Expenditure")
        ni_series = get_metric_series(inc_df, ticker, "Net Income")
        
        metrics["ocf_ttm"] = latest(ocf_series)
        metrics["ocf_3y_avg"] = avg(ocf_series, 3)
        
        metrics["assets_ttm"] = latest(get_metric_series(bal_df, ticker, "Total Assets"))
        metrics["liabilities_ttm"] = latest(get_metric_series(bal_df, ticker, "Total Liabilities"))
        metrics["net_income_3y_avg"] = avg(ni_series, 3)

        # Share Dilution
        shares_series = get_metric_series(inc_df, ticker, "Weighted Average Shares Diluted")
        if shares_series.empty:
            shares_series = get_metric_series(inc_df, ticker, "Weighted Average Shares")
            
        # Dilution as of year
        if as_of_year is not None:
            valid_shares = []
            for idx in shares_series.index:
                try:
                    y = int(str(idx).split('-')[0])
                    if y <= as_of_year:
                        valid_shares.append((y, idx))
                except ValueError:
                    pass
            if len(valid_shares) >= 3:
                # Sort by year
                valid_shares.sort(key=lambda x: x[0])
                idx_latest = valid_shares[-1][1]
                idx_past = valid_shares[-3][1]
                metrics["shares_growth_3y"] = (shares_series.loc[idx_latest] - shares_series.loc[idx_past]) / shares_series.loc[idx_past]
            else:
                metrics["shares_growth_3y"] = 0.0
        else:
            if not shares_series.empty and len(shares_series) >= 3:
                metrics["shares_growth_3y"] = (shares_series.iloc[-1] - shares_series.iloc[-3]) / shares_series.iloc[-3]
            else:
                metrics["shares_growth_3y"] = 0.0

        # Earnings Quality (FCF / Net Income)
        if not ocf_series.empty and not capex_series.empty and not ni_series.empty:
            common_idx = ocf_series.index.intersection(capex_series.index).intersection(ni_series.index)
            if not common_idx.empty:
                fcf_series = ocf_series.loc[common_idx] - capex_series.loc[common_idx].abs()
                fcf_net_inc_series = fcf_series / ni_series.loc[common_idx]
                metrics["fcf_to_net_income_ttm"] = latest(fcf_net_inc_series)
                metrics["fcf_to_net_income_3y_avg"] = avg(fcf_net_inc_series, 3)
                
        if "fcf_to_net_income_ttm" not in metrics:
            metrics["fcf_to_net_income_ttm"] = float("nan")
            metrics["fcf_to_net_income_3y_avg"] = float("nan")

        # Revenue Growth
        rev_series = get_metric_series(inc_df, ticker, "Revenue")
        if not rev_series.empty:
            rev_growth_series = rev_series.pct_change()
            metrics["revenue_growth_ttm"] = latest(rev_growth_series)
            metrics["revenue_growth_3y_avg"] = avg(rev_growth_series, 3)
        else:
            metrics["revenue_growth_ttm"] = float("nan")
            metrics["revenue_growth_3y_avg"] = float("nan")

        # EPS Growth
        eps_series = get_metric_series(inc_df, ticker, "EPS Diluted")
        if eps_series.empty:
            eps_series = get_metric_series(inc_df, ticker, "EPS")
        if not eps_series.empty:
            eps_growth_series = eps_series.pct_change()
            metrics["eps_growth_ttm"] = latest(eps_growth_series)
            metrics["eps_growth_3y_avg"] = avg(eps_growth_series, 3)
        else:
            metrics["eps_growth_ttm"] = float("nan")
            metrics["eps_growth_3y_avg"] = float("nan")

        # R&D Intensity
        rd_series = get_metric_series(inc_df, ticker, "Research and Development Expenses")
        if not rd_series.empty and not rev_series.empty:
            common_idx = rd_series.index.intersection(rev_series.index)
            if not common_idx.empty:
                rd_intensity_series = rd_series.loc[common_idx] / rev_series.loc[common_idx]
                metrics["rd_intensity"] = latest(rd_intensity_series)
        if "rd_intensity" not in metrics:
            metrics["rd_intensity"] = 0.0

        # Margin Expansion
        if not op_margin_series.empty:
            metrics["margin_expansion"] = latest(op_margin_series) - avg(op_margin_series, 3)
        else:
            metrics["margin_expansion"] = 0.0

        # ── V3 trader-grade additions (all NaN-safe: sparse statements — common
        #    for NSE tickers — yield NaN, never a fake 0) ──────────────────────

        # Accruals ratio = (NI - OCF) / Total Assets. High accruals mean paper
        # earnings not backed by cash — a classic earnings-quality red flag.
        ni_ttm = latest(ni_series)
        ocf_ttm = metrics.get("ocf_ttm", float("nan"))
        assets_ttm = metrics.get("assets_ttm", float("nan"))
        if not (math.isnan(ni_ttm) or math.isnan(ocf_ttm) or
                math.isnan(assets_ttm)) and assets_ttm > 0:
            metrics["accruals_ratio"] = (ni_ttm - ocf_ttm) / assets_ttm
        else:
            metrics["accruals_ratio"] = float("nan")

        # Growth durability: coefficient of variation of YoY revenue growth
        # over up to 5 years. Low CV = steady compounding; high CV = spiky,
        # unreliable growth. NaN when < 3 growth observations.
        metrics["rev_cagr_stability"] = float("nan")
        if not rev_series.empty:
            g = rev_series.pct_change().dropna()
            if as_of_year is not None:
                g = g[[i for i in g.index
                       if str(i).split('-')[0].isdigit()
                       and int(str(i).split('-')[0]) <= as_of_year]]
            g = g.iloc[-5:]
            if len(g) >= 3:
                mean_g = float(g.mean())
                if abs(mean_g) > 1e-9:
                    metrics["rev_cagr_stability"] = float(g.std() / abs(mean_g))

        # Piotroski-style F-score (0-9) with graceful degradation:
        # piotroski_max counts how many of the 9 signals were computable.
        f_score, f_max = self._piotroski(
            ni_series=ni_series, ocf_series=ocf_series,
            assets_series=get_metric_series(bal_df, ticker, "Total Assets"),
            liabilities_series=get_metric_series(bal_df, ticker, "Total Liabilities"),
            cr_series=cr_series, shares_series=shares_series,
            gross_margin_series=gross_margin_series, rev_series=rev_series,
            as_of_year=as_of_year,
        )
        metrics["piotroski_f"] = f_score
        metrics["piotroski_max"] = f_max

        return metrics

    @staticmethod
    def _piotroski(ni_series, ocf_series, assets_series, liabilities_series,
                   cr_series, shares_series, gross_margin_series, rev_series,
                   as_of_year: Optional[int] = None):
        """
        Piotroski F-score adapted to available annual data. Returns
        (score, max_computable); each of the 9 signals is only counted in
        max_computable when the underlying data exists for both years.
        """
        def _tail2(series: pd.Series):
            """Latest two values respecting as_of_year; (prev, curr) or None."""
            if series is None or series.empty:
                return None
            s = series.dropna()
            if as_of_year is not None:
                keep = [i for i in s.index
                        if str(i).split('-')[0].isdigit()
                        and int(str(i).split('-')[0]) <= as_of_year]
                s = s.loc[keep]
            if len(s) < 2:
                return None
            return float(s.iloc[-2]), float(s.iloc[-1])

        def _roa(ni, assets):
            pair_ni, pair_a = _tail2(ni), _tail2(assets)
            if pair_ni is None or pair_a is None:
                return None
            prev = pair_ni[0] / pair_a[0] if pair_a[0] else None
            curr = pair_ni[1] / pair_a[1] if pair_a[1] else None
            if prev is None or curr is None:
                return None
            return prev, curr

        score, computable = 0, 0

        # 1. Positive net income
        ni2 = _tail2(ni_series)
        if ni2 is not None:
            computable += 1
            score += ni2[1] > 0
        # 2. Positive operating cash flow
        ocf2 = _tail2(ocf_series)
        if ocf2 is not None:
            computable += 1
            score += ocf2[1] > 0
        # 3. ROA improving
        roa = _roa(ni_series, assets_series)
        if roa is not None:
            computable += 1
            score += roa[1] > roa[0]
        # 4. OCF > net income (cash backs earnings)
        if ni2 is not None and ocf2 is not None:
            computable += 1
            score += ocf2[1] > ni2[1]
        # 5. Leverage decreasing (liabilities / assets)
        lia2, ast2 = _tail2(liabilities_series), _tail2(assets_series)
        if lia2 is not None and ast2 is not None and ast2[0] and ast2[1]:
            computable += 1
            score += (lia2[1] / ast2[1]) < (lia2[0] / ast2[0])
        # 6. Current ratio improving
        cr2 = _tail2(cr_series)
        if cr2 is not None:
            computable += 1
            score += cr2[1] > cr2[0]
        # 7. No dilution (share count flat or shrinking)
        sh2 = _tail2(shares_series)
        if sh2 is not None and sh2[0]:
            computable += 1
            score += sh2[1] <= sh2[0] * 1.005  # allow rounding noise
        # 8. Gross margin improving
        gm2 = _tail2(gross_margin_series)
        if gm2 is not None:
            computable += 1
            score += gm2[1] > gm2[0]
        # 9. Asset turnover improving (revenue / assets)
        rev2 = _tail2(rev_series)
        if rev2 is not None and ast2 is not None and ast2[0] and ast2[1]:
            computable += 1
            score += (rev2[1] / ast2[1]) > (rev2[0] / ast2[0])

        return int(score), int(computable)
