import math
import yaml
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, model_validator

class FilterConfig(BaseModel):
    min_market_cap: float = Field(default=500_000_000, description="Minimum market cap in USD")
    min_price: float = Field(default=5.0, description="Minimum stock price in USD")
    min_volume: float = Field(default=100_000, description="Minimum average daily volume")
    min_current_ratio: float = Field(default=1.0, description="Minimum current ratio")
    max_debt_to_equity: float = Field(default=2.0, description="Maximum debt-to-equity ratio")
    max_pe_ratio: Optional[float] = Field(default=40.0, description="Maximum P/E ratio")

class CategoryWeights(BaseModel):
    graham_safety: float = Field(default=0.35)
    fisher_growth: float = Field(default=0.30)
    buffett_quality: float = Field(default=0.35)

    @model_validator(mode='after')
    def validate_sum(self) -> 'CategoryWeights':
        total = self.graham_safety + self.fisher_growth + self.buffett_quality
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Category weights must sum to 1.0, got {total}")
        return self

class GrahamSafetyWeights(BaseModel):
    current_ratio: float = Field(default=0.3)
    debt_to_equity: float = Field(default=0.3)
    pe_ratio: float = Field(default=0.4)

    @model_validator(mode='after')
    def validate_sum(self) -> 'GrahamSafetyWeights':
        total = self.current_ratio + self.debt_to_equity + self.pe_ratio
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Graham safety weights must sum to 1.0, got {total}")
        return self

class FisherGrowthWeights(BaseModel):
    revenue_growth_yoy: float = Field(default=0.4)
    eps_growth_yoy: float = Field(default=0.4)
    rd_intensity: float = Field(default=0.2)

    @model_validator(mode='after')
    def validate_sum(self) -> 'FisherGrowthWeights':
        total = self.revenue_growth_yoy + self.eps_growth_yoy + self.rd_intensity
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Fisher growth weights must sum to 1.0, got {total}")
        return self

class BuffettQualityWeights(BaseModel):
    roic: float = Field(default=0.4)
    operating_margin: float = Field(default=0.3)
    fcf_to_net_income: float = Field(default=0.3)

    @model_validator(mode='after')
    def validate_sum(self) -> 'BuffettQualityWeights':
        total = self.roic + self.operating_margin + self.fcf_to_net_income
        if not math.isclose(total, 1.0, rel_tol=1e-5):
            raise ValueError(f"Buffett quality weights must sum to 1.0, got {total}")
        return self

class BatchConfig(BaseModel):
    size: int = Field(default=5, ge=1, description="Number of tickers per fundamental screening batch")
    delay_seconds: float = Field(default=15.0, ge=0.0, description="Delay between batches in seconds")

class ScoringRangeConfig(BaseModel):
    pe_ratio: List[float] = Field(default=[10.0, 30.0], description="[Target PE, Floor PE]")
    current_ratio: List[float] = Field(default=[1.0, 2.5], description="[Floor CR, Target CR]")
    debt_to_equity: List[float] = Field(default=[0.5, 2.0], description="[Target DE, Floor DE]")
    revenue_growth_yoy: List[float] = Field(default=[0.0, 0.15], description="[Floor Growth, Target Growth]")
    eps_growth_yoy: List[float] = Field(default=[0.0, 0.15], description="[Floor Growth, Target Growth]")
    rd_intensity: List[float] = Field(default=[0.0, 0.10], description="[Floor RD, Target RD]")
    roic: List[float] = Field(default=[0.05, 0.20], description="[Floor ROIC, Target ROIC]")
    operating_margin: List[float] = Field(default=[0.05, 0.25], description="[Floor Margin, Target Margin]")

class WeightConfig(BaseModel):
    category_weights: CategoryWeights = Field(default_factory=CategoryWeights)
    graham_safety: GrahamSafetyWeights = Field(default_factory=GrahamSafetyWeights)
    fisher_growth: FisherGrowthWeights = Field(default_factory=FisherGrowthWeights)
    buffett_quality: BuffettQualityWeights = Field(default_factory=BuffettQualityWeights)

class SectorProfile(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    weights: WeightConfig = Field(default_factory=WeightConfig)
    scoring_ranges: ScoringRangeConfig = Field(default_factory=ScoringRangeConfig)

class ScannerConfig(BaseModel):
    mode: Literal['market_scan', 'single_stock'] = Field(default='single_stock')
    tickers: List[str] = Field(default_factory=list)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    weights: WeightConfig = Field(default_factory=WeightConfig)
    scoring_ranges: ScoringRangeConfig = Field(default_factory=ScoringRangeConfig)
    batch: BatchConfig = Field(default_factory=BatchConfig)
    sector_profiles: dict[str, SectorProfile] = Field(default_factory=dict)

def load_config_from_yaml(yaml_content: str) -> ScannerConfig:
    data = yaml.safe_load(yaml_content) or {}
    return ScannerConfig(**data)

def load_config_from_file(file_path: str) -> ScannerConfig:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return load_config_from_yaml(content)

def save_config_to_file(config: ScannerConfig, file_path: str) -> None:
    data = config.model_dump()
    with open(file_path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
