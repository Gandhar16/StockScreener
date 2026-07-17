import logging
import time
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf

from stock_scanner.config import ScannerConfig
from stock_scanner.data.provider import DataProvider
from stock_scanner.engine.explanation import generate_decision
from stock_scanner.engine.risk_flags import check_red_flags
from stock_scanner.engine.scoring import calculate_factor_scores
from stock_scanner.engine.sector_config import get_sector_config

logger = logging.getLogger(__name__)


def _get_val_as_of_year(series: pd.Series, as_of_year: int | None) -> float:
    if series.empty:
        return float("nan")
    series = series.dropna()
    if series.empty:
        return float("nan")
    if as_of_year is None:
        return float(series.iloc[-1])

    valid_years = []
    for idx in series.index:
        try:
            y = int(str(idx).split("-")[0])
            if y <= as_of_year:
                valid_years.append((y, idx))
        except ValueError:
            pass

    if not valid_years:
        return float("nan")

    _best_y, best_idx = max(valid_years, key=lambda x: x[0])
    return float(series.loc[best_idx])


def _get_avg_val_as_of_year(series: pd.Series, n: int, as_of_year: int | None) -> float:
    if series.empty:
        return float("nan")
    series = series.dropna()
    if series.empty:
        return float("nan")
    if as_of_year is not None:
        valid_indices = []
        for idx in series.index:
            try:
                y = int(str(idx).split("-")[0])
                if y <= as_of_year:
                    valid_indices.append(idx)
            except ValueError:
                pass
        series = series.loc[valid_indices]
        if series.empty:
            return float("nan")
    return float(series.iloc[-n:].mean())


def _get_latest_val(series: pd.Series, as_of_year: int | None = None) -> float:
    return _get_val_as_of_year(series, as_of_year)


def _get_avg_val(series: pd.Series, n: int, as_of_year: int | None = None) -> float:
    return _get_avg_val_as_of_year(series, n, as_of_year)


class FundamentalEngine:
    """
    FundamentalEngine V2: Sector-aware, risk-aware, factor-style equity scoring.
    Uses yfinance for fundamental data extraction (no API key required).
    Supports point-in-time historical backtesting via as_of_year.
    """

    def __init__(self, config: ScannerConfig):
        self.config = config
        self.provider = DataProvider(config)

    def analyze_tickers(self, tickers: list[str], as_of_year: int | None = None) -> pd.DataFrame:
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
            logger.info(
                f"Processing batch {i//batch_size + 1} of {(len(tickers) + batch_size - 1)//batch_size}: {batch_tickers} (As Of: {as_of_year})"
            )

            try:
                batch_df = self._analyze_batch(batch_tickers, as_of_year=as_of_year)
                if not batch_df.empty:
                    all_dfs.append(batch_df)
            except Exception as e:
                logger.error(
                    f"Error processing fundamental batch {batch_tickers}: {e}", exc_info=True
                )

            # Sleep between batches if this is not the last batch
            if i + batch_size < len(tickers) and delay > 0:
                logger.info(f"Sleeping for {delay} seconds to stay under rate limits...")
                time.sleep(delay)

        if not all_dfs:
            return pd.DataFrame()

        combined_df = pd.concat(all_dfs, ignore_index=True)
        if not combined_df.empty:
            combined_df = self._apply_peer_percentiles(combined_df)
            combined_df = combined_df.sort_values(by="total_score", ascending=False).reset_index(
                drop=True
            )
        return combined_df

    def _analyze_batch(self, tickers: list[str], as_of_year: int | None = None) -> pd.DataFrame:
        """
        Performs fundamental analysis on a single batch of tickers using yfinance.
        """
        logger.info(f"Fetching yfinance data for {len(tickers)} tickers...")
        try:
            yf.Tickers(tickers)
        except Exception as e:
            logger.error(f"Failed to initialize yfinance for {tickers}: {e}")
            return pd.DataFrame()

        records = []
        for ticker in tickers:
            try:
                # 1. Fetch yfinance info
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
                    ticker=ticker, yf_info=yf_info, as_of_year=as_of_year
                )

                # 3. Resolve sector config
                sect_config = None
                if self.config.sector_profiles and sector in self.config.sector_profiles:
                    self.config.sector_profiles[sector]
                    is_fin = "financial" in sector.lower() or "bank" in sector.lower()

                    if is_fin:
                        relevant_metrics = [
                            "roe",
                            "equity_multiplier",
                            "price_to_book",
                            "dividend_yield",
                            "operating_margin",
                        ]
                        irrelevant_metrics = [
                            "current_ratio",
                            "debt_to_equity",
                            "fcf_to_net_income",
                            "ev_to_ebitda",
                            "price_to_sales",
                            "gross_margin",
                        ]
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
                            "capital_allocation": 0.0,
                        },
                        "scoring_ranges": self.config.scoring_ranges.model_dump()
                        if hasattr(self.config.scoring_ranges, "model_dump")
                        else self.config.scoring_ranges,
                    }
                if not sect_config:
                    sect_config = get_sector_config(sector, industry)
                    if hasattr(self.config, "scoring_ranges") and self.config.scoring_ranges:
                        sect_config["scoring_ranges"] = (
                            self.config.scoring_ranges.model_dump()
                            if hasattr(self.config.scoring_ranges, "model_dump")
                            else self.config.scoring_ranges
                        )
                    if hasattr(self.config, "weights") and self.config.weights:
                        sect_config["weights"] = {
                            "business_quality": self.config.weights.buffett_quality,
                            "valuation": self.config.weights.graham_safety * 0.6,
                            "financial_risk": self.config.weights.graham_safety * 0.4,
                            "growth": self.config.weights.fisher_growth,
                            "capital_allocation": 0.0,
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

                # Calculate total score
                w = sect_config.get("weights", {})
                total_score = (
                    scores.get("business_quality", 50.0) * w.get("business_quality", 0.25)
                    + scores.get("valuation", 50.0) * w.get("valuation", 0.25)
                    + scores.get("financial_risk", 50.0) * w.get("financial_risk", 0.20)
                    + scores.get("growth", 50.0) * w.get("growth", 0.20)
                    + scores.get("capital_allocation", 50.0) * w.get("capital_allocation", 0.10)
                )

                # 6. Generate qualitative analysis
                rating, category, strengths, weaknesses, risks = generate_decision(
                    scores=scores,
                    red_flags=flags,
                    is_disqualified=is_disq,
                    metrics=metrics,
                    sector=sector,
                )

                # 6. Backward-compatible mapping for V1 tests/outputs
                graham_score = (
                    scores.get("valuation", 50.0) + scores.get("financial_risk", 50.0)
                ) / 2.0
                fisher_score = scores.get("growth", 50.0)
                buffett_score = scores.get("business_quality", 50.0)

                graham_details = {
                    "current_ratio_score": details["financial_risk_details"].get(
                        "current_ratio_score", 50.0
                    ),
                    "debt_to_equity_score": details["financial_risk_details"].get(
                        "debt_to_equity_score", 50.0
                    ),
                    "pe_score": details["valuation_details"].get("pe_score", 50.0),
                }
                fisher_details = {
                    "revenue_growth_score": details["growth_details"].get(
                        "revenue_growth_score", 50.0
                    ),
                    "eps_growth_score": details["growth_details"].get("eps_growth_score", 50.0),
                    "rd_intensity_score": details["capital_allocation_details"].get(
                        "reinvestment_score", 50.0
                    ),
                }
                buffett_details = {
                    "roic_score": details["business_quality_details"].get("roic_score", 50.0),
                    "operating_margin_score": details["business_quality_details"].get(
                        "operating_margin_score", 50.0
                    ),
                    "fcf_net_income_score": details["business_quality_details"].get(
                        "earnings_quality_score", 50.0
                    ),
                }

                records.append(
                    {
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
                        "_w_valuation": 0.25,
                    }
                )
            except Exception as e:
                logger.error(f"Error analyzing fundamentals for {ticker}: {e}", exc_info=True)

        result_df = pd.DataFrame(records)
        if not result_df.empty:
            result_df = result_df.sort_values(by="total_score", ascending=False).reset_index(
                drop=True
            )
        return result_df

    def _apply_peer_percentiles(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply peer group percentiles for sector-relative scoring."""
        if df.empty:
            return df
        # Add percentile columns for key metrics
        for col in [
            "pe_ratio",
            "price_to_book",
            "ev_to_ebitda",
            "price_to_sales",
            "roe_ttm",
            "roic_ttm",
            "operating_margin_ttm",
            "revenue_growth_ttm",
        ]:
            if col in df.columns:
                df[f"{col}_pct"] = df[col].rank(pct=True) * 100
        return df

    def _extract_ticker_metrics(
        self, ticker: str, yf_info: dict, as_of_year: int | None = None
    ) -> dict[str, Any]:
        """
        Extracts and prepares all numerical metrics required for V2 scoring and red-flag checks.
        Uses yfinance for all data.
        """
        metrics = {}

        # Local closures to automatically bind as_of_year
        def latest(series: pd.Series) -> float:
            return _get_val_as_of_year(series, as_of_year)

        def avg(series: pd.Series, n: int) -> float:
            return _get_avg_val_as_of_year(series, n, as_of_year)

        # Get financial statements from yfinance
        try:
            yf_ticker = yf.Ticker(ticker)

            # Get financial statements
            inc_df = yf_ticker.income_stmt
            bal_df = yf_ticker.balance_sheet
            cf_df = yf_ticker.cashflow

            # Helper to get series from yfinance dataframes
            def get_series(df: pd.DataFrame, metric_name: str) -> pd.Series:
                if df is None or df.empty:
                    return pd.Series(dtype=float)
                if metric_name in df.index:
                    return df.loc[metric_name].dropna()
                # Try fuzzy match
                for idx in df.index:
                    if metric_name.lower() in idx.lower():
                        return df.loc[idx].dropna()
                return pd.Series(dtype=float)

            def get_latest(series: pd.Series) -> float:
                return _get_val_as_of_year(series, as_of_year)

            def get_avg(series: pd.Series, n: int) -> float:
                return _get_avg_val_as_of_year(series, n, as_of_year)

            # 1. Ratio Data from yfinance info (convert where needed)
            # yfinance debtToEquity is in PERCENTAGE (e.g., 79.55 = 79.55%), convert to ratio
            de_raw = yf_info.get("debtToEquity", float("nan"))
            metrics["debt_to_equity_ttm"] = de_raw / 100.0 if not pd.isna(de_raw) else float("nan")

            metrics["current_ratio_ttm"] = yf_info.get("currentRatio", float("nan"))
            metrics["pe_ratio_ttm"] = yf_info.get("trailingPE", float("nan"))
            metrics["forward_pe"] = yf_info.get("forwardPE", float("nan"))
            metrics["peg_ratio"] = yf_info.get("pegRatio", float("nan"))
            metrics["price_to_book"] = yf_info.get("priceToBook", float("nan"))
            metrics["ev_to_ebitda"] = yf_info.get("enterpriseToEbitda", float("nan"))
            metrics["price_to_sales"] = yf_info.get("priceToSalesTrailing12Months", float("nan"))
            metrics["price_to_fcf"] = (
                yf_info.get("marketCap", 0) / max(yf_info.get("freeCashflow", 1), 1)
                if yf_info.get("freeCashflow")
                else float("nan")
            )
            metrics["dividend_yield"] = yf_info.get("dividendYield", float("nan"))

            metrics["operating_margin_ttm"] = yf_info.get("operatingMargins", float("nan"))
            metrics["gross_margin_ttm"] = yf_info.get("grossMargins", float("nan"))

            metrics["roe_ttm"] = yf_info.get("returnOnEquity", float("nan"))
            metrics["roe_3y_avg"] = yf_info.get(
                "returnOnEquity", float("nan")
            )  # yfinance doesn't provide 3y avg

            # Try to get ROIC from yfinance, otherwise calculate from statements
            roic_yf = yf_info.get("returnOnInvestedCapital", float("nan"))

            # 2. Calculate ROIC from financial statements if not available
            if pd.isna(roic_yf):
                try:
                    # Get operating income (EBIT)
                    op_income_series = get_series(inc_df, "Operating Income")
                    if op_income_series.empty:
                        op_income_series = get_series(inc_df, "EBIT")
                    op_income = get_latest(op_income_series)

                    # Get tax rate
                    tax_series = get_series(inc_df, "Income Tax Expense")
                    pretax_series = get_series(inc_df, "Pretax Income")
                    if pretax_series.empty:
                        pretax_series = get_series(inc_df, "Income Before Tax")
                    pretax = get_latest(pretax_series)
                    tax = get_latest(tax_series)
                    tax_rate = tax / pretax if pretax and pretax != 0 else 0.21

                    # NOPAT
                    nopat = (
                        op_income * (1 - tax_rate)
                        if op_income and not pd.isna(op_income)
                        else float("nan")
                    )

                    # Invested Capital = Total Debt + Total Equity - Cash
                    total_debt_series = get_series(bal_df, "Total Debt")
                    if total_debt_series.empty:
                        total_debt_series = get_series(bal_df, "Long Term Debt")
                    total_debt = get_latest(total_debt_series)

                    total_equity_series = get_series(bal_df, "Total Equity")
                    if total_equity_series.empty:
                        total_equity_series = get_series(bal_df, "Stockholders Equity")
                    total_equity = get_latest(total_equity_series)

                    cash_series = get_series(bal_df, "Cash And Cash Equivalents")
                    if cash_series.empty:
                        cash_series = get_series(bal_df, "Cash")
                    cash = get_latest(cash_series)

                    invested_capital = (total_debt or 0) + (total_equity or 0) - (cash or 0)

                    if nopat and invested_capital and invested_capital > 0:
                        metrics["roic_ttm"] = nopat / invested_capital
                        metrics["roic_3y_avg"] = metrics["roic_ttm"]
                    else:
                        metrics["roic_ttm"] = float("nan")
                        metrics["roic_3y_avg"] = float("nan")
                except Exception as e:
                    logger.debug(f"Failed to calculate ROIC for {ticker}: {e}")
                    metrics["roic_ttm"] = float("nan")
                    metrics["roic_3y_avg"] = float("nan")
            else:
                metrics["roic_ttm"] = roic_yf
                metrics["roic_3y_avg"] = roic_yf

            # 3. Calculate FCF/Net Income from statements
            try:
                ocf_series = get_series(cf_df, "Operating Cash Flow")
                if ocf_series.empty:
                    ocf_series = get_series(cf_df, "Cash Flow From Operations")
                ocf = get_latest(ocf_series)

                capex_series = get_series(cf_df, "Capital Expenditure")
                if capex_series.empty:
                    capex_series = get_series(cf_df, "Capital Expenditures")
                capex = get_latest(capex_series)

                fcf = (ocf or 0) - abs(capex or 0)

                ni_series = get_series(inc_df, "Net Income")
                net_income = get_latest(ni_series)

                if fcf and net_income and net_income != 0:
                    metrics["fcf_to_net_income_ttm"] = fcf / net_income
                else:
                    metrics["fcf_to_net_income_ttm"] = float("nan")
            except Exception as e:
                logger.debug(f"Failed to calculate FCF/Net Income for {ticker}: {e}")
                metrics["fcf_to_net_income_ttm"] = float("nan")

            # 4. Additional metrics from statements
            try:
                # Equity Multiplier = Assets / Equity
                assets_series = get_series(bal_df, "Total Assets")
                equity_series = get_series(bal_df, "Total Equity")
                if equity_series.empty:
                    equity_series = get_series(bal_df, "Stockholders Equity")
                assets = get_latest(assets_series)
                equity = get_latest(equity_series)
                if assets and equity and equity != 0:
                    metrics["equity_multiplier_ttm"] = assets / equity
                else:
                    metrics["equity_multiplier_ttm"] = float("nan")
            except:
                metrics["equity_multiplier_ttm"] = float("nan")

            try:
                # Interest Coverage = EBIT / Interest Expense
                ebit_series = get_series(inc_df, "EBIT")
                if ebit_series.empty:
                    ebit_series = get_series(inc_df, "Operating Income")
                ebit = get_latest(ebit_series)

                interest_series = get_series(inc_df, "Interest Expense")
                interest = get_latest(interest_series)

                if ebit and interest and interest != 0:
                    metrics["interest_coverage_ttm"] = ebit / interest
                else:
                    metrics["interest_coverage_ttm"] = float("nan")
            except:
                metrics["interest_coverage_ttm"] = float("nan")

            try:
                # Net Debt / EBITDA
                total_debt_series = get_series(bal_df, "Total Debt")
                if total_debt_series.empty:
                    total_debt_series = get_series(bal_df, "Long Term Debt")
                total_debt = get_latest(total_debt_series)

                cash_series = get_series(bal_df, "Cash And Cash Equivalents")
                if cash_series.empty:
                    cash_series = get_series(bal_df, "Cash")
                cash = get_latest(cash_series)

                net_debt = (total_debt or 0) - (cash or 0)

                # EBITDA = Operating Income + D&A
                op_income_series = get_series(inc_df, "Operating Income")
                op_income = get_latest(op_income_series)

                da_series = get_series(cf_df, "Depreciation And Amortization")
                if da_series.empty:
                    da_series = get_series(cf_df, "Depreciation Amortization Depletion")
                da = get_latest(da_series)

                ebitda = (op_income or 0) + (da or 0)

                if net_debt is not None and ebitda and ebitda != 0:
                    metrics["net_debt_to_ebitda_ttm"] = net_debt / ebitda
                else:
                    metrics["net_debt_to_ebitda_ttm"] = float("nan")
            except:
                metrics["net_debt_to_ebitda_ttm"] = float("nan")

            try:
                # Dividend payout ratio
                payout = yf_info.get("payoutRatio", float("nan"))
                if not pd.isna(payout):
                    metrics["dividend_payout_ratio"] = payout
                else:
                    # Calculate from dividends / net income
                    div_series = get_series(cf_df, "Dividends Paid")
                    if div_series.empty:
                        div_series = get_series(cf_df, "Cash Dividends Paid")
                    div_paid = abs(get_latest(div_series))
                    ni_series = get_series(inc_df, "Net Income")
                    net_income = get_latest(ni_series)
                    if div_paid and net_income and net_income != 0:
                        metrics["dividend_payout_ratio"] = div_paid / net_income
                    else:
                        metrics["dividend_payout_ratio"] = float("nan")
            except:
                metrics["dividend_payout_ratio"] = float("nan")

            # Revenue growth (yoy) from yfinance
            metrics["revenue_growth_yoy"] = yf_info.get("revenueGrowth", float("nan"))
            metrics["eps_growth_yoy"] = yf_info.get("earningsGrowth", float("nan"))

            # 3-year averages (yfinance doesn't provide directly, use TTM as proxy)
            metrics["revenue_growth_3y_avg"] = metrics["revenue_growth_yoy"]
            metrics["eps_growth_3y_avg"] = metrics["eps_growth_yoy"]

            # R&D intensity
            try:
                rd_series = get_series(inc_df, "Research And Development")
                rd = get_latest(rd_series)
                revenue_series = get_series(inc_df, "Total Revenue")
                if revenue_series.empty:
                    revenue_series = get_series(inc_df, "Revenue")
                revenue = get_latest(revenue_series)
                if rd and revenue and revenue != 0:
                    metrics["rd_intensity"] = rd / revenue
                else:
                    metrics["rd_intensity"] = float("nan")
            except:
                metrics["rd_intensity"] = float("nan")

            # 3-year ROE average (use TTM as proxy)
            metrics["roe_3y_avg"] = metrics["roe_ttm"]

            # Operating cash flow metrics for red flags
            try:
                ocf_series = get_series(cf_df, "Operating Cash Flow")
                if ocf_series.empty:
                    ocf_series = get_series(cf_df, "Cash Flow From Operations")
                ocf = get_latest(ocf_series)
                metrics["ocf_ttm"] = ocf

                # 3-year average OCF
                if len(ocf_series) >= 3:
                    metrics["ocf_3y_avg"] = ocf_series.iloc[:3].mean()
                else:
                    metrics["ocf_3y_avg"] = ocf
            except:
                metrics["ocf_ttm"] = float("nan")
                metrics["ocf_3y_avg"] = float("nan")

            # Net income 3y avg
            try:
                ni_series = get_series(inc_df, "Net Income")
                if len(ni_series) >= 3:
                    metrics["net_income_3y_avg"] = ni_series.iloc[:3].mean()
                else:
                    metrics["net_income_3y_avg"] = get_latest(ni_series)
            except:
                metrics["net_income_3y_avg"] = float("nan")

            # FCF/Net Income 3y avg
            try:
                ocf_series = get_series(cf_df, "Operating Cash Flow")
                if ocf_series.empty:
                    ocf_series = get_series(cf_df, "Cash Flow From Operations")
                capex_series = get_series(cf_df, "Capital Expenditure")
                if capex_series.empty:
                    capex_series = get_series(cf_df, "Capital Expenditures")
                ni_series = get_series(inc_df, "Net Income")

                fcf_3y = []
                for i in range(min(3, len(ocf_series), len(capex_series), len(ni_series))):
                    ocf = ocf_series.iloc[i]
                    capex = capex_series.iloc[i] if i < len(capex_series) else 0
                    ni = ni_series.iloc[i] if i < len(ni_series) else 0
                    if ni and ni != 0:
                        fcf = ocf - abs(capex)
                        fcf_3y.append(fcf / ni)
                if fcf_3y:
                    metrics["fcf_to_net_income_3y_avg"] = sum(fcf_3y) / len(fcf_3y)
                else:
                    metrics["fcf_to_net_income_3y_avg"] = metrics["fcf_to_net_income_ttm"]
            except:
                metrics["fcf_to_net_income_3y_avg"] = metrics["fcf_to_net_income_ttm"]

            # Shares growth 3y
            try:
                shares_series = get_series(bal_df, "Ordinary Shares Number")
                if shares_series.empty:
                    shares_series = get_series(bal_df, "Share Capital")
                if len(shares_series) >= 3:
                    start = shares_series.iloc[-1]
                    end = shares_series.iloc[0]
                    if start and start != 0:
                        metrics["shares_growth_3y"] = (end - start) / start
                    else:
                        metrics["shares_growth_3y"] = 0.0
                else:
                    metrics["shares_growth_3y"] = 0.0
            except:
                metrics["shares_growth_3y"] = 0.0

            # Balance sheet items for going concern check
            try:
                assets = get_latest(get_series(bal_df, "Total Assets"))
                liabilities = get_latest(get_series(bal_df, "Total Liabilities"))
                metrics["assets_ttm"] = assets
                metrics["liabilities_ttm"] = liabilities
            except:
                metrics["assets_ttm"] = 1.0
                metrics["liabilities_ttm"] = 0.0

            # Accruals ratio = (Net Income - Operating Cash Flow) / Total Assets
            try:
                ni = metrics.get("net_income_3y_avg", float("nan"))
                ocf = metrics.get("ocf_3y_avg", float("nan"))
                assets = metrics.get("assets_ttm", 1.0)
                if not pd.isna(ni) and not pd.isna(ocf) and assets:
                    metrics["accruals_ratio"] = (ni - ocf) / assets
                else:
                    metrics["accruals_ratio"] = float("nan")
            except:
                metrics["accruals_ratio"] = float("nan")

            # Revenue CAGR stability
            try:
                revenue_series = get_series(inc_df, "Total Revenue")
                if revenue_series.empty:
                    revenue_series = get_series(inc_df, "Revenue")
                if len(revenue_series) >= 3:
                    revs = revenue_series.dropna().values
                    if len(revs) >= 3:
                        # Calculate year-over-year growth rates
                        growth_rates = []
                        for i in range(len(revs) - 1):
                            if revs[i + 1] != 0:
                                growth_rates.append((revs[i] - revs[i + 1]) / revs[i + 1])
                        if growth_rates:
                            metrics["rev_cagr_stability"] = float(np.std(growth_rates))
                        else:
                            metrics["rev_cagr_stability"] = float("nan")
                    else:
                        metrics["rev_cagr_stability"] = float("nan")
                else:
                    metrics["rev_cagr_stability"] = float("nan")
            except:
                metrics["rev_cagr_stability"] = float("nan")

            # Piotroski F-Score
            try:
                piotroski = 0
                # 1. Positive Net Income
                ni = get_latest(get_series(inc_df, "Net Income"))
                if ni and ni > 0:
                    piotroski += 1

                # 2. Positive Operating Cash Flow
                ocf = get_latest(get_series(cf_df, "Operating Cash Flow"))
                if ocf_series.empty:
                    ocf = get_latest(get_series(cf_df, "Cash Flow From Operations"))
                if ocf and ocf > 0:
                    piotroski += 1

                # 3. ROA improvement (use ROIC as proxy)
                roic = metrics.get("roic_ttm", float("nan"))
                if not pd.isna(roic) and roic > 0:
                    piotroski += 1

                # 4. Quality of earnings (OCF > Net Income)
                if ocf and ni and ocf > ni:
                    piotroski += 1

                # 5. Decrease in leverage
                try:
                    de_current = metrics["debt_to_equity_ttm"]
                    # Get previous year's balance sheet
                    bal_prev = (
                        bal_df.iloc[:, 1] if bal_df is not None and bal_df.shape[1] > 1 else None
                    )
                    if bal_prev is not None:
                        total_debt_prev = get_series(pd.DataFrame(bal_prev).T, "Total Debt")
                        if total_debt_prev.empty:
                            total_debt_prev = get_series(pd.DataFrame(bal_prev).T, "Long Term Debt")
                        equity_prev = get_series(pd.DataFrame(bal_prev).T, "Total Equity")
                        if equity_prev.empty:
                            equity_prev = get_series(
                                pd.DataFrame(bal_prev).T, "Stockholders Equity"
                            )
                        debt_prev = get_latest(total_debt_prev)
                        equity_prev_val = get_latest(equity_prev)
                        if debt_prev and equity_prev_val and equity_prev_val != 0:
                            de_prev = debt_prev / equity_prev_val
                            if de_current < de_prev:
                                piotroski += 1
                except:
                    pass

                # 6. Increase in current ratio
                cr_current = metrics["current_ratio_ttm"]
                try:
                    ca_series = get_series(bal_df, "Current Assets")
                    cl_series = get_series(bal_df, "Current Liabilities")
                    if ca_series.empty:
                        ca_series = get_series(bal_df, "Total Current Assets")
                    if cl_series.empty:
                        cl_series = get_series(bal_df, "Total Current Liabilities")
                    ca_prev = get_latest(ca_series)
                    cl_prev = get_latest(cl_series)
                    # Get previous year
                    ca_prev2 = ca_series.iloc[1] if len(ca_series) > 1 else ca_prev
                    cl_prev2 = cl_series.iloc[1] if len(cl_series) > 1 else cl_prev
                    if cl_prev2 and cl_prev2 != 0:
                        cr_prev = ca_prev2 / cl_prev2
                        if cr_current > cr_prev:
                            piotroski += 1
                except:
                    pass

                # 7. No new shares issued (shares growth < 0)
                if metrics["shares_growth_3y"] <= 0:
                    piotroski += 1

                # 8. Gross margin improvement
                gm_current = metrics["gross_margin_ttm"]
                try:
                    rev_series = get_series(inc_df, "Total Revenue")
                    if rev_series.empty:
                        rev_series = get_series(inc_df, "Revenue")
                    cogs_series = get_series(inc_df, "Cost Of Revenue")
                    if cogs_series.empty:
                        cogs_series = get_series(inc_df, "Cost Of Goods Sold")
                    rev = get_latest(rev_series)
                    cogs = get_latest(cogs_series)
                    if rev and rev != 0 and cogs is not None:
                        gm_prev = 1 - (cogs / rev)
                        if gm_current > gm_prev:
                            piotroski += 1
                except:
                    pass

                # 9. Asset turnover improvement
                try:
                    at_current = (
                        metrics["revenue_growth_yoy"]
                        if not pd.isna(metrics["revenue_growth_yoy"])
                        else 0
                    )
                    # Simplified - just check if revenue grew
                    if at_current > 0:
                        piotroski += 1
                except:
                    pass

                metrics["piotroski_f"] = piotroski
                metrics["piotroski_max"] = 9
            except:
                metrics["piotroski_f"] = float("nan")
                metrics["piotroski_max"] = 9

            return metrics

        except Exception as e:
            logger.warning(f"Failed to extract metrics for {ticker}: {e}")
            return {}
