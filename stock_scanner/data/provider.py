import logging

import pandas as pd
import yfinance as yf

from stock_scanner.config import ScannerConfig

logger = logging.getLogger(__name__)


class DataProvider:
    """
    DataProvider handles ticker loading, bulk price/volume downloading,
    and initial hard filters (price and volume) to reduce downstream fundamental scanning costs.
    Uses yfinance for all data - no API key required.
    """
    def __init__(self, config: ScannerConfig):
        self.config = config

    def get_default_tickers(self) -> list[str]:
        """
        Returns a curated default set of major US stocks if no tickers are configured.
        """
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "BRK-B", "JNJ", "V", "WMT", "PG", "JPM", "UNH", "HD",
            "MA", "LLY", "AVGO", "ABBV", "COST", "MRK", "ADBE", "CRM"
        ]

    def fetch_and_filter_prices(self, tickers: list[str]) -> pd.DataFrame:
        """
        Downloads the last 5 days of price and volume data in bulk,
        calculates last close and 5-day average volume, and applies price & volume filters.
        """
        if not tickers:
            tickers = self.get_default_tickers()

        logger.info(f"Downloading market data for {len(tickers)} tickers in bulk...")
        try:
            # Download 5 days of data for fast calculation of latest price and average volume
            df = yf.download(tickers, period="5d", progress=False, group_by='ticker', auto_adjust=True)
        except Exception as e:
            logger.error(f"Error downloading data from yfinance: {e}")
            return pd.DataFrame(columns=["ticker", "last_price", "avg_volume"])

        if df.empty:
            logger.warning("No data downloaded from yfinance.")
            return pd.DataFrame(columns=["ticker", "last_price", "avg_volume"])

        records = []
        for ticker in tickers:
            try:
                # Handle both single-ticker and multi-ticker DataFrame format
                if isinstance(df.columns, pd.MultiIndex):
                    if (ticker,) not in df.columns.get_level_values(0):
                        logger.warning(f"Ticker {ticker} missing in MultiIndex columns.")
                        continue
                    ticker_df = df[ticker]
                else:
                    ticker_df = df

                # Filter NaNs
                close_col = ticker_df['Close'].dropna()
                vol_col = ticker_df['Volume'].dropna()

                if close_col.empty or vol_col.empty:
                    logger.debug(f"Ticker {ticker} has missing price or volume data.")
                    continue

                last_price = float(close_col.iloc[-1])
                avg_volume = float(vol_col.mean())

                # Apply hard filters for price and volume
                if last_price >= self.config.filters.min_price and avg_volume >= self.config.filters.min_volume:
                    records.append({
                        "ticker": ticker,
                        "last_price": last_price,
                        "avg_volume": avg_volume
                    })
                else:
                    logger.debug(f"Ticker {ticker} filtered out: Price={last_price:.2f}, AvgVol={avg_volume:.0f}")
            except KeyError:
                logger.warning(f"Ticker {ticker} not found in downloaded yfinance columns.")
            except Exception as e:
                logger.error(f"Error processing yfinance data for {ticker}: {e}")

        return pd.DataFrame(records)

    def fetch_historical_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """
        Downloads historical daily OHLC data for a single ticker.
        """
        logger.info(f"Downloading {period} of historical daily prices for {ticker}...")
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if not df.empty:
                # Ensure all columns are single-level
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                return df
        except Exception as e:
            logger.error(f"Error downloading historical data for {ticker}: {e}")
        return pd.DataFrame()

    def fetch_fundamental_data(self, ticker: str) -> dict:
        """
        Fetch fundamental data from yfinance info.
        Returns a dict with available fundamental metrics.
        """
        try:
            yf_ticker = yf.Ticker(ticker)
            info = yf_ticker.info or {}

            # Extract available fundamental metrics
            metrics = {
                "current_ratio_ttm": info.get("currentRatio"),
                "debt_to_equity_ttm": info.get("debtToEquity"),
                "pe_ratio_ttm": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "ev_to_ebitda": info.get("enterpriseToEbitda"),
                "revenue_growth_ttm": info.get("revenueGrowth"),
                "eps_growth_ttm": info.get("earningsGrowth"),
                "rd_intensity": info.get("researchAndDevelopment", 0) / max(info.get("totalRevenue", 1), 1) if info.get("researchAndDevelopment") else None,
                "roic_ttm": info.get("returnOnInvestedCapital"),
                "roe_ttm": info.get("returnOnEquity"),
                "operating_margin_ttm": info.get("operatingMargins"),
                "gross_margin_ttm": info.get("grossMargins"),
                "fcf_to_net_income_ttm": info.get("freeCashflow", 0) / max(info.get("netIncomeToCommon", 1), 1) if info.get("freeCashflow") and info.get("netIncomeToCommon") else None,
                "dividend_yield": info.get("dividendYield"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "price_to_fcf": info.get("marketCap", 0) / max(info.get("freeCashflow", 1), 1) if info.get("freeCashflow") else None,
                "market_cap": info.get("marketCap"),
                "shares_outstanding": info.get("sharesOutstanding"),
                "net_income_ttm": info.get("netIncomeToCommon"),
                "ocf_ttm": info.get("operatingCashflow"),
                "capex_ttm": info.get("capitalExpenditures"),
                "assets_ttm": info.get("totalAssets"),
                "liabilities_ttm": info.get("totalLiabilities"),
                "net_income_3y_avg": info.get("netIncomeToCommon"),
                "eps_ttm": info.get("trailingEps"),
                "forward_eps": info.get("forwardEps"),
            }

            # Remove None values
            return {k: v for k, v in metrics.items() if v is not None and not (isinstance(v, float) and math.isnan(v))}
        except Exception as e:
            logger.warning(f"Failed to fetch fundamental data for {ticker}: {e}")
            return {}

    def get_default_tickers(self) -> list[str]:
        """Default S&P 500 major tickers."""
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "BRK-B", "JNJ", "V", "WMT", "PG", "JPM", "UNH", "HD",
            "MA", "LLY", "AVGO", "ABBV", "COST", "MRK", "ADBE", "CRM",
            "ORCL", "ACN", "CVX", "TXN", "AMD", "QCOM", "INTC", "NFLX",
            "AMD", "AMD", "DIS", "NKE", "PYPL", "UBER", "SNOW", "ZM"
        ]
