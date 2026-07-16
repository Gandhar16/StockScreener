import logging
import hashlib
import pandas as pd
import yfinance as yf
from typing import List, Optional
from stock_scanner.config import ScannerConfig
from stock_scanner.data.cache import get_price_cache, set_price_cache, get_benchmark_cache, set_benchmark_cache

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
        Uses caching with 1-hour TTL.
        """
        if not tickers:
            tickers = self.get_default_tickers()

        # Try cache first
        cached = get_price_cache(tickers, period="5d")
        if cached is not None:
            logger.info(f"Using cached price data for {len(tickers)} tickers")
            records = []
            for ticker, data in cached.items():
                if data["last_price"] >= self.config.filters.min_price and                    data["avg_volume"] >= self.config.filters.min_volume:
                    records.append({
                        "ticker": ticker,
                        "last_price": data["last_price"],
                        "avg_volume": data["avg_volume"]
                    })
            return pd.DataFrame(records)

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
        cache_data = {}
        
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

                # Store in cache data
                cache_data[ticker] = {
                    "last_price": last_price,
                    "avg_volume": avg_volume
                }

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

        # Cache the results
        if cache_data:
            set_price_cache(tickers, cache_data, period="5d")

        return pd.DataFrame(records)

    def fetch_historical_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame:
        """
        Downloads historical daily OHLC data for a single ticker.
        Uses caching with 24-hour TTL.
        """
        # Try cache first
        cached = get_price_cache([ticker], period=period)
        if cached and ticker in cached:
            # Convert cached data back to DataFrame
            data = cached[ticker]
            if isinstance(data, dict) and "ohlcv" in data:
                return pd.DataFrame(data["ohlcv"])
        
        logger.info(f"Downloading {period} of historical daily prices for {ticker}...")
        try:
            df = yf.download(ticker, period=period, progress=False)
            if not df.empty:
                # Ensure all columns are single-level
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                
                # Cache the result
                ohlcv_data = df.to_dict("records")
                cache_data = {ticker: {"ohlcv": ohlcv_data}}
                set_price_cache([ticker], cache_data, period=period)
                
                return df
        except Exception as e:
            logger.error(f"Error downloading historical data for {ticker}: {e}")
        return pd.DataFrame()

    def fetch_benchmark(self, benchmark: str = "^GSPC", period: str = "2y") -> pd.DataFrame:
        """
        Download benchmark data (e.g., S&P 500) with caching.
        """
        cached = get_benchmark_cache(benchmark, period)
        if cached is not None:
            return pd.DataFrame(cached)
        
        logger.info(f"Downloading benchmark {benchmark} for {period}...")
        try:
            df = yf.download(benchmark, period=period, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [col[0] for col in df.columns]
                
                # Cache for 24 hours
                set_benchmark_cache(benchmark, df.to_dict("records"), period=period)
                return df
        except Exception as e:
            logger.error(f"Error downloading benchmark {benchmark}: {e}")
        return pd.DataFrame()
