import logging
import pandas as pd
import yfinance as yf
from typing import List
from stock_scanner.config import ScannerConfig

logger = logging.getLogger(__name__)

class DataProvider:
    """
    DataProvider handles ticker loading, bulk price/volume downloading,
    and initial hard filters (price and volume) to reduce downstream fundamental scanning costs.
    """
    def __init__(self, config: ScannerConfig):
        self.config = config

    def get_default_tickers(self) -> List[str]:
        """
        Returns a curated default set of major US stocks if no tickers are configured.
        """
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
            "BRK-B", "JNJ", "V", "WMT", "PG", "JPM", "UNH", "HD",
            "MA", "LLY", "AVGO", "ABBV", "COST", "MRK", "ADBE", "CRM"
        ]

    def fetch_and_filter_prices(self, tickers: List[str]) -> pd.DataFrame:
        """
        Downloads the last 5 days of price and volume data in bulk,
        calculates last close and 5-day average volume, and applies price & volume filters.
        """
        if not tickers:
            tickers = self.get_default_tickers()

        logger.info(f"Downloading market data for {len(tickers)} tickers in bulk...")
        try:
            # Download 5 days of data for fast calculation of latest price and average volume
            df = yf.download(tickers, period="5d", progress=False)
        except Exception as e:
            logger.error(f"Error downloading data from yfinance: {e}")
            return pd.DataFrame(columns=["ticker", "last_price", "avg_volume"])

        if df.empty:
            logger.warning("No data downloaded from yfinance.")
            return pd.DataFrame(columns=["ticker", "last_price", "avg_volume"])

        records = []
        for ticker in tickers:
            try:
                # Handle single-ticker vs multi-ticker DataFrame format returned by yfinance
                if isinstance(df.columns, pd.MultiIndex):
                    close_key = ("Close", ticker) if ("Close", ticker) in df.columns else ("Adj Close", ticker)
                    vol_key = ("Volume", ticker)
                    if close_key not in df.columns or vol_key not in df.columns:
                        logger.warning(f"Ticker {ticker} missing in MultiIndex columns.")
                        continue
                    close_col = df[close_key]
                    vol_col = df[vol_key]
                else:
                    close_key = "Close" if "Close" in df.columns else "Adj Close"
                    vol_key = "Volume"
                    if close_key not in df.columns or vol_key not in df.columns:
                        logger.warning(f"Required keys missing in simple columns.")
                        continue
                    close_col = df[close_key]
                    vol_col = df[vol_key]
                
                # Filter NaNs
                close_col = close_col.dropna()
                vol_col = vol_col.dropna()
                
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
            df = yf.download(ticker, period=period, progress=False)
            if not df.empty:
                # Ensure all columns are single-level
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                return df
        except Exception as e:
            logger.error(f"Error downloading historical data for {ticker}: {e}")
        return pd.DataFrame()
