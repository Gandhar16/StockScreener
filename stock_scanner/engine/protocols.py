"""Type protocols for dependency injection and testing."""

from typing import Protocol, runtime_checkable
import pandas as pd
from stock_scanner.config import ScannerConfig


@runtime_checkable
class DataProviderProtocol(Protocol):
    """Protocol for data providers."""
    
    def get_default_tickers(self) -> list[str]: ...
    
    def fetch_and_filter_prices(self, tickers: list[str]) -> pd.DataFrame: ...
    
    def fetch_historical_prices(self, ticker: str, period: str = "2y") -> pd.DataFrame: ...
    
    def fetch_benchmark(self, benchmark: str = "^GSPC", period: str = "2y") -> pd.DataFrame: ...


@runtime_checkable
class FundamentalEngineProtocol(Protocol):
    """Protocol for fundamental analysis engines."""
    
    def analyze_tickers(self, tickers: list[str]) -> pd.DataFrame: ...
    
    def _score_current_ratio(self, value: float) -> float: ...
    
    def _score_debt_to_equity(self, value: float) -> float: ...
    
    def _score_pe_ratio(self, value: float) -> float: ...
    
    def _score_revenue_growth(self, value: float) -> float: ...
    
    def _score_eps_growth(self, value: float) -> float: ...
    
    def _score_rd_intensity(self, value: float) -> float: ...
    
    def _score_roic(self, value: float) -> float: ...
    
    def _score_operating_margin(self, value: float) -> float: ...
    
    def _score_fcf_to_net_income(self, value: float) -> float: ...


@runtime_checkable
class TechnicalEngineProtocol(Protocol):
    """Protocol for technical analysis engines."""
    
    def analyze(self, ohlcv: pd.DataFrame) -> pd.DataFrame: ...
    
    def detect_market_structure(self, ohlcv: pd.DataFrame) -> dict: ...
    
    def find_support_resistance(self, ohlcv: pd.DataFrame) -> list[float]: ...


@runtime_checkable
class PatternFinderProtocol(Protocol):
    """Protocol for pattern detection."""
    
    def find_patterns(self, ohlcv: pd.DataFrame) -> list[dict]: ...
    
    def classify_pattern(self, pattern: dict) -> str: ...


@runtime_checkable
class ScoringEngineProtocol(Protocol):
    """Protocol for scoring engines."""
    
    def score_ticker(self, ticker: str, fundamental_data: dict, technical_data: dict) -> float: ...
    
    def calculate_category_scores(self, data: dict) -> dict: ...


@runtime_checkable
class CallsDatabaseProtocol(Protocol):
    """Protocol for calls database operations."""
    
    def upsert_call(self, call: dict) -> None: ...
    
    def get_calls_by_ticker(self, ticker: str) -> list[dict]: ...
    
    def export_portfolio_json(self) -> dict: ...


@runtime_checkable
class SentimentEngineProtocol(Protocol):
    """Protocol for sentiment analysis."""
    
    def analyze_sentiment(self, ticker: str) -> dict: ...
    
    def get_news_sentiment(self, ticker: str) -> float: ...


# Type aliases for common data structures
TickerData = dict[str, any]
FundamentalData = dict[str, any]
TechnicalData = dict[str, any]
SignalData = dict[str, any]
