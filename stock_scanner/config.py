import math
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alpha_vantage_api_key: str = ""
    polygon_api_key: str = ""
    finnhub_api_key: str = ""
    database_url: str = "sqlite:///reports/calls.db"
    log_level: str = "INFO"


class FilterConfig(BaseModel):
    min_market_cap: float = Field(default=500_000_000, description="Minimum market cap in USD")
    min_price: float = Field(default=5.0, description="Minimum stock price in USD")
    min_volume: float = Field(default=100_000, description="Minimum average daily volume")
    min_current_ratio: float = Field(default=1.0, description="Minimum current ratio")
    max_debt_to_equity: float = Field(default=2.0, description="Maximum debt-to-equity ratio")
    max_pe_ratio: float | None = Field(default=40.0, description="Maximum P/E ratio")


class CategoryWeights(BaseModel):
    graham_safety: float = Field(default=0.35)
    fisher_growth: float = Field(default=0.30)
    buffett_quality: float = Field(default=0.35)

    @model_validator(mode="after")
    def validate_sum(self) -> "CategoryWeights":
        total = self.graham_safety + self.fisher_growth + self.buffett_quality
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Category weights must sum to 1.0, got {total}")
        return self


class GrahamSafetyWeights(BaseModel):
    current_ratio: float = Field(default=0.3)
    debt_to_equity: float = Field(default=0.3)
    pe_ratio: float = Field(default=0.4)

    @model_validator(mode="after")
    def validate_sum(self) -> "GrahamSafetyWeights":
        total = self.current_ratio + self.debt_to_equity + self.pe_ratio
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Graham safety weights must sum to 1.0, got {total}")
        return self


class FisherGrowthWeights(BaseModel):
    revenue_growth_yoy: float = Field(default=0.4)
    eps_growth_yoy: float = Field(default=0.4)
    rd_intensity: float = Field(default=0.2)

    @model_validator(mode="after")
    def validate_sum(self) -> "FisherGrowthWeights":
        total = self.revenue_growth_yoy + self.eps_growth_yoy + self.rd_intensity
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Fisher growth weights must sum to 1.0, got {total}")
        return self


class BuffettQualityWeights(BaseModel):
    roic: float = Field(default=0.4)
    operating_margin: float = Field(default=0.3)
    fcf_to_net_income: float = Field(default=0.3)

    @model_validator(mode="after")
    def validate_sum(self) -> "BuffettQualityWeights":
        total = self.roic + self.operating_margin + self.fcf_to_net_income
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Buffett quality weights must sum to 1.0, got {total}")
        return self


class BatchConfig(BaseModel):
    size: int = Field(
        default=5, ge=1, description="Number of tickers per fundamental screening batch"
    )
    delay_seconds: float = Field(
        default=15.0, ge=0.0, description="Delay between batches in seconds"
    )


class ScoringRangeConfig(BaseModel):
    pe_ratio: list[float] = Field(default_factory=lambda: [8.0, 36.0])
    current_ratio: list[float] = Field(default_factory=lambda: [1.0, 2.5])
    debt_to_equity: list[float] = Field(default_factory=lambda: [0.5, 2.0])
    revenue_growth_yoy: list[float] = Field(default_factory=lambda: [0.03, 0.21])
    eps_growth_yoy: list[float] = Field(default_factory=lambda: [-0.05, 0.165])
    rd_intensity: list[float] = Field(default_factory=lambda: [0.0, 0.1])
    roic: list[float] = Field(default_factory=lambda: [0.02, 0.29])
    operating_margin: list[float] = Field(default_factory=lambda: [0.07, 0.32])
    fcf_to_net_income: list[float] = Field(default_factory=lambda: [0.5, 1.5])


class TechnicalConfig(BaseModel):
    history_period: str = Field(
        default="2y", description="Historical period for technical analysis"
    )

    class MTFConfig(BaseModel):
        aligned_threshold: int = Field(
            default=55, description="Weekly alignment score needed to count as aligned"
        )

    class RSConfig(BaseModel):
        benchmark_map: dict = Field(
            default_factory=lambda: {
                ".NS": "^NSEI",
                ".BO": "^BSESN",
            }
        )
        default_benchmark: str = Field(default="^GSPC")
        soft_floor: float = Field(
            default=-5.0, description="Bull setups need Mansfield RS above this (or improving)"
        )
        hard_floor: float = Field(
            default=-20.0, description="Below this = severe laggard, hard reject"
        )

    class GatesConfig(BaseModel):
        account_size: float = Field(default=100000)
        risk_per_trade_pct: float = Field(default=0.01)
        atr_stop_mult: float = Field(default=2.0)
        min_stop_pct: float = Field(default=0.02)
        max_stop_pct: float = Field(default=0.10)
        max_position_pct: float = Field(default=0.15)
        min_rr_high_conviction: float = Field(default=2.0)
        min_rr_floor: float = Field(default=1.5)

    class SetupScoreConfig(BaseModel):
        weights: dict = Field(
            default_factory=lambda: {
                "pattern": 0.35,
                "mtf": 0.20,
                "rs": 0.15,
                "volume": 0.15,
                "rr": 0.15,
            }
        )

    mtf: MTFConfig = Field(default_factory=MTFConfig)
    rs: RSConfig = Field(default_factory=RSConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    setup_score: SetupScoreConfig = Field(default_factory=SetupScoreConfig)


class FundamentalExtrasConfig(BaseModel):
    accruals_red_flag_threshold: float = Field(default=0.10)
    peer_percentile_min_group: int = Field(default=4)
    peer_valuation_blend: float = Field(default=0.5)


class SectorProfileConfig(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    weights: CategoryWeights = Field(default_factory=CategoryWeights)
    graham_safety: GrahamSafetyWeights = Field(default_factory=GrahamSafetyWeights)
    fisher_growth: FisherGrowthWeights = Field(default_factory=FisherGrowthWeights)
    buffett_quality: BuffettQualityWeights = Field(default_factory=BuffettQualityWeights)


class ScannerConfig(BaseModel):
    mode: Literal["market_scan", "single_stock"] = "market_scan"
    tickers: list[str] = Field(default_factory=list)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    weights: CategoryWeights = Field(default_factory=CategoryWeights)
    graham_safety: GrahamSafetyWeights = Field(default_factory=GrahamSafetyWeights)
    fisher_growth: FisherGrowthWeights = Field(default_factory=FisherGrowthWeights)
    buffett_quality: BuffettQualityWeights = Field(default_factory=BuffettQualityWeights)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    scoring_ranges: ScoringRangeConfig = Field(default_factory=ScoringRangeConfig)
    technical: TechnicalConfig = Field(default_factory=TechnicalConfig)
    fundamental_extras: FundamentalExtrasConfig = Field(default_factory=FundamentalExtrasConfig)
    sector_profiles: dict[str, SectorProfileConfig] = Field(default_factory=dict)


def load_config_from_file(config_path: str) -> ScannerConfig:
    """Load configuration from YAML file."""
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    # Process nested structures
    if "filters" in data and isinstance(data["filters"], dict):
        data["filters"] = FilterConfig(**data["filters"])

    if "weights" in data and isinstance(data["weights"], dict):
        w = data["weights"]
        # Handle category_weights
        if "category_weights" in w and isinstance(w["category_weights"], dict):
            cw = w["category_weights"]
            data["weights"] = CategoryWeights(
                graham_safety=cw.get("graham_safety", 0.35),
                fisher_growth=cw.get("fisher_growth", 0.30),
                buffett_quality=cw.get("buffett_quality", 0.35),
            )
        # Handle graham_safety weights
        if "graham_safety" in w and isinstance(w["graham_safety"], dict):
            data["graham_safety"] = GrahamSafetyWeights(**w["graham_safety"])
        if "fisher_growth" in w and isinstance(w["fisher_growth"], dict):
            data["fisher_growth"] = FisherGrowthWeights(**w["fisher_growth"])
        if "buffett_quality" in w and isinstance(w["buffett_quality"], dict):
            data["buffett_quality"] = BuffettQualityWeights(**w["buffett_quality"])
        # If no nested, create CategoryWeights from the top-level
        else:
            data["weights"] = CategoryWeights(**w)

    # Top-level weight objects
    if "graham_safety" in data and isinstance(data["graham_safety"], dict):
        data["graham_safety"] = GrahamSafetyWeights(**data["graham_safety"])
    if "fisher_growth" in data and isinstance(data["fisher_growth"], dict):
        data["fisher_growth"] = FisherGrowthWeights(**data["fisher_growth"])
    if "buffett_quality" in data and isinstance(data["buffett_quality"], dict):
        data["buffett_quality"] = BuffettQualityWeights(**data["buffett_quality"])

    if "batch" in data and isinstance(data["batch"], dict):
        data["batch"] = BatchConfig(**data["batch"])
    if "scoring_ranges" in data and isinstance(data["scoring_ranges"], dict):
        data["scoring_ranges"] = ScoringRangeConfig(**data["scoring_ranges"])
    if "technical" in data and isinstance(data["technical"], dict):
        data["technical"] = TechnicalConfig(**data["technical"])
    if "fundamental_extras" in data and isinstance(data["fundamental_extras"], dict):
        data["fundamental_extras"] = FundamentalExtrasConfig(**data["fundamental_extras"])

    if "sector_profiles" in data:
        profiles = {}
        for sector, profile in data["sector_profiles"].items():
            if isinstance(profile, dict):
                prof = profile.copy()
                if "filters" in prof and isinstance(prof["filters"], dict):
                    prof["filters"] = FilterConfig(**prof["filters"])
                if "weights" in prof and isinstance(prof["weights"], dict):
                    pw = prof["weights"]
                    if "category_weights" in pw and isinstance(pw["category_weights"], dict):
                        cw = pw["category_weights"]
                        prof["weights"] = CategoryWeights(
                            graham_safety=cw.get("graham_safety", 0.35),
                            fisher_growth=cw.get("fisher_growth", 0.30),
                            buffett_quality=cw.get("buffett_quality", 0.35),
                        )
                    else:
                        prof["weights"] = CategoryWeights(**pw)
                    # Nested weight objects in sector profile
                    if "graham_safety" in pw and isinstance(pw["graham_safety"], dict):
                        prof["graham_safety"] = GrahamSafetyWeights(**pw["graham_safety"])
                    if "fisher_growth" in pw and isinstance(pw["fisher_growth"], dict):
                        prof["fisher_growth"] = FisherGrowthWeights(**pw["fisher_growth"])
                    if "buffett_quality" in pw and isinstance(pw["buffett_quality"], dict):
                        prof["buffett_quality"] = BuffettQualityWeights(**pw["buffett_quality"])
                profiles[sector] = SectorProfileConfig(**prof)
        data["sector_profiles"] = profiles

    return ScannerConfig(**data)


# Global settings instance
settings = Settings()
