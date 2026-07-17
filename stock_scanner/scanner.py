import logging

import pandas as pd

from stock_scanner.config import ScannerConfig
from stock_scanner.data.provider import DataProvider
from stock_scanner.engine.fundamental import FundamentalEngine

logger = logging.getLogger(__name__)

class StockScanner:
    """
    StockScanner orchestrates the stock screening workflow.
    It supports two modes:
      1. 'single_stock': Directly runs fundamental scoring on specified tickers.
      2. 'market_scan': Performs bulk price & volume filtering first, then scores the remaining stocks.
    """
    def __init__(self, config: ScannerConfig):
        self.config = config
        self.provider = DataProvider(config)
        self.engine = FundamentalEngine(config)

    def run(self) -> pd.DataFrame:
        """
        Executes the scan based on configured mode.
        Returns a sorted DataFrame of results with fundamental and technical structure columns.
        """
        logger.info(f"Starting Stock Scanner in '{self.config.mode}' mode...")

        if self.config.mode == "single_stock":
            if not self.config.tickers:
                logger.error("No tickers provided for single_stock analysis.")
                return pd.DataFrame()

            # Directly run fundamental scoring, bypassing yfinance price/volume pre-filter
            results_df = self.engine.analyze_tickers(self.config.tickers)

            # Fetch latest price using yfinance to populate in output if missing
            try:
                price_df = self.provider.fetch_and_filter_prices(self.config.tickers)
                if not price_df.empty and not results_df.empty:
                    results_df = results_df.merge(
                        price_df[["ticker", "last_price", "avg_volume"]],
                        on="ticker",
                        how="left"
                    )
            except Exception as e:
                logger.warning(f"Failed to fetch market prices for single stock mode details: {e}")

            results_df = self._run_technical_analysis(results_df)
            return results_df

        elif self.config.mode == "market_scan":
            # 1. Fetch initial candidate ticker list
            candidates = self.config.tickers if self.config.tickers else self.provider.get_default_tickers()
            logger.info(f"Loaded {len(candidates)} candidate tickers for scanning.")

            # 2. Stage 1 Filter: Price & Volume via yfinance
            filtered_market_data = self.provider.fetch_and_filter_prices(candidates)
            if filtered_market_data.empty:
                logger.warning("No tickers passed price & volume pre-filters.")
                return pd.DataFrame()

            passed_tickers = filtered_market_data["ticker"].tolist()
            logger.info(f"{len(passed_tickers)} tickers passed price & volume checks. Proceeding to fundamental analysis.")

            # 3. Stage 2 Filter & Scoring: Fundamentals via FinanceToolkit
            fundamental_results = self.engine.analyze_tickers(passed_tickers)
            if fundamental_results.empty:
                logger.warning("No tickers passed fundamental screening.")
                return pd.DataFrame()

            # 4. Merge market data (prices/volumes) with fundamental scorecard
            final_df = fundamental_results.merge(
                filtered_market_data[["ticker", "last_price", "avg_volume"]],
                on="ticker",
                how="left"
            )

            # Sort by total score descending
            final_df = final_df.sort_values(by="total_score", ascending=False).reset_index(drop=True)

            # 5. Technical Market Structure Analysis
            final_df = self._run_technical_analysis(final_df)
            return final_df
        else:
            logger.error(f"Unknown mode: {self.config.mode}")
            return pd.DataFrame()

    def _run_technical_analysis(self, results_df: pd.DataFrame) -> pd.DataFrame:
        """
        Runs the MarketStructureEngine on each ticker in the results DataFrame.
        """
        if results_df.empty:
            return results_df

        from stock_scanner.engine.technical import MarketStructureEngine
        engine = MarketStructureEngine()

        support_zones_list = []
        resistance_zones_list = []
        support_trendlines_list = []
        resistance_trendlines_list = []
        long_term_support_list = []
        long_term_resistance_list = []
        short_term_support_list = []
        short_term_resistance_list = []
        contexts_list = []

        logger.info(f"Running technical market structure analysis for {len(results_df)} tickers...")

        for ticker in results_df["ticker"]:
            # Fetch 2 years of daily history via DataProvider
            hist_df = self.provider.fetch_historical_prices(ticker, period="2y")
            if hist_df.empty:
                logger.warning(f"No historical daily data returned for {ticker}")
                support_zones_list.append([])
                resistance_zones_list.append([])
                support_trendlines_list.append([])
                resistance_trendlines_list.append([])
                long_term_support_list.append([])
                long_term_resistance_list.append([])
                short_term_support_list.append([])
                short_term_resistance_list.append([])
                contexts_list.append("Unknown (No Data)")
                continue

            try:
                # Run market structure analysis
                analysis = engine.analyze_structure(hist_df)
                support_zones_list.append(analysis["support_zones"])
                resistance_zones_list.append(analysis["resistance_zones"])
                support_trendlines_list.append(analysis["support_trendlines"])
                resistance_trendlines_list.append(analysis["resistance_trendlines"])
                long_term_support_list.append(analysis.get("long_term_support_trendlines", []))
                long_term_resistance_list.append(analysis.get("long_term_resistance_trendlines", []))
                short_term_support_list.append(analysis.get("short_term_support_trendlines", []))
                short_term_resistance_list.append(analysis.get("short_term_resistance_trendlines", []))
                contexts_list.append(analysis["context"])
            except Exception as e:
                logger.error(f"Failed to perform technical analysis for {ticker}: {e}")
                support_zones_list.append([])
                resistance_zones_list.append([])
                support_trendlines_list.append([])
                resistance_trendlines_list.append([])
                long_term_support_list.append([])
                long_term_resistance_list.append([])
                short_term_support_list.append([])
                short_term_resistance_list.append([])
                contexts_list.append("Error")

        results_df["support_zones"] = support_zones_list
        results_df["resistance_zones"] = resistance_zones_list
        results_df["support_trendlines"] = support_trendlines_list
        results_df["resistance_trendlines"] = resistance_trendlines_list
        results_df["long_term_support_trendlines"] = long_term_support_list
        results_df["long_term_resistance_trendlines"] = long_term_resistance_list
        results_df["short_term_support_trendlines"] = short_term_support_list
        results_df["short_term_resistance_trendlines"] = short_term_resistance_list
        results_df["technical_context"] = contexts_list

        return results_df
