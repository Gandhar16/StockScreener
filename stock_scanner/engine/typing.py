"""Type hints and aliases for the stock scanner."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, NotRequired, TypeAlias, TypedDict

import pandas as pd

# Primitive types
Ticker: TypeAlias = str
Score: TypeAlias = float
Timestamp: TypeAlias = datetime

# DataFrame type hints (using TypeAlias for readability)
OHLCV: TypeAlias = pd.DataFrame  # columns: Open, High, Low, Close, Volume, index: DatetimeIndex
Fundamentals: TypeAlias = pd.DataFrame  # financial statement data
BenchmarkData: TypeAlias = pd.DataFrame  # benchmark price data

# Signal types
SignalType: TypeAlias = Literal["BUY", "SELL", "HOLD", "WATCH-LONG", "WATCH-SHORT"]
ConvictionLevel: TypeAlias = Literal["HIGH", "MEDIUM", "LOW"]


# Configuration types
class PhaseConfig(TypedDict):
    start: str
    end: str
    as_of: int


ScannerMode: TypeAlias = Literal["market_scan", "single_stock"]
BenchmarkMap: TypeAlias = dict[str, str]  # ticker suffix -> benchmark symbol


# Fundamental data structures
class FundamentalMetrics(TypedDict):
    """Core fundamental metrics from FinanceToolkit."""

    current_ratio: NotRequired[float]
    debt_to_equity: NotRequired[float]
    pe_ratio: NotRequired[float]
    revenue_growth_yoy: NotRequired[float]
    eps_growth_yoy: NotRequired[float]
    rd_intensity: NotRequired[float]
    roic: NotRequired[float]
    operating_margin: NotRequired[float]
    fcf_to_net_income: NotRequired[float]
    market_cap: NotRequired[float]
    # ... add more as needed


class TechnicalMetrics(TypedDict):
    """Technical analysis metrics."""

    sma_20: NotRequired[float]
    sma_50: NotRequired[float]
    sma_200: NotRequired[float]
    ema_12: NotRequired[float]
    ema_26: NotRequired[float]
    rsi: NotRequired[float]
    macd: NotRequired[float]
    macd_signal: NotRequired[float]
    macd_hist: NotRequired[float]
    atr: NotRequired[float]
    bb_upper: NotRequired[float]
    bb_lower: NotRequired[float]
    bb_middle: NotRequired[float]
    volume_sma: NotRequired[float]
    # ... more indicators


class MarketStructure(TypedDict):
    """Market structure analysis."""

    trend: NotRequired[Literal["UP", "DOWN", "SIDEWAYS"]]
    higher_highs: NotRequired[bool]
    higher_lows: NotRequired[bool]
    lower_highs: NotRequired[bool]
    lower_lows: NotRequired[bool]
    key_levels: NotRequired[list[float]]
    support: NotRequired[float]
    resistance: NotRequired[float]


class PatternSignal(TypedDict):
    """Detected chart pattern."""

    name: str
    type: Literal["bullish", "bearish", "neutral"]
    confidence: float
    entry_zone: NotRequired[tuple[float, float]]
    stop_loss: NotRequired[float]
    target: NotRequired[float]
    risk_reward: NotRequired[float]


class EntrySignal(TypedDict):
    """Trade entry signal."""

    ticker: str
    signal: SignalType
    price: float
    stop_loss: float
    target: float
    risk_reward: float
    conviction: ConvictionLevel
    pattern: NotRequired[PatternSignal]
    mtf_aligned: bool
    rs_ok: bool
    volume_ok: bool
    setup_score: float


class ScoredStock(TypedDict):
    """Stock with fundamental scores."""

    ticker: str
    total_score: float
    graham_safety: float
    fisher_growth: float
    buffett_quality: float
    # Sub-scores
    current_ratio: NotRequired[float]
    debt_to_equity: NotRequired[float]
    pe_ratio: NotRequired[float]
    revenue_growth_yoy: NotRequired[float]
    eps_growth_yoy: NotRequired[float]
    rd_intensity: NotRequired[float]
    roic: NotRequired[float]
    operating_margin: NotRequired[float]
    fcf_to_net_income: NotRequired[float]
    # Raw metrics
    metrics: NotRequired[FundamentalMetrics]
    # Technical
    technical: NotRequired[TechnicalMetrics]
    market_structure: NotRequired[MarketStructure]
    patterns: NotRequired[list[PatternSignal]]
    entry_signal: NotRequired[EntrySignal]


# Result types
ScanResult = list[ScoredStock]


class EquityCall(TypedDict):
    ticker: str
    type: Literal["long_term", "swing", "sell"]
    score: float
    conviction: ConvictionLevel
    entry: NotRequired[float]
    stop: NotRequired[float]
    target: NotRequired[float]
    thesis: NotRequired[str]
    risks: NotRequired[list[str]]
    technical: NotRequired[TechnicalMetrics]
    fundamental: NotRequired[FundamentalMetrics]
    entry_signal: NotRequired[EntrySignal]
    timestamp: datetime


# Pipeline phase results
class PhaseResult(TypedDict):
    phase: int
    tickers_in: int
    tickers_out: int
    results: list[ScoredStock]
    duration_seconds: float
    timestamp: datetime


class PipelineResult(TypedDict):
    phases: list[PhaseResult]
    equity_calls: list[EquityCall]
    benchmark_performance: dict
    portfolio_nav: pd.Series
    metadata: dict
