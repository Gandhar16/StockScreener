import pytest
import yaml
from pydantic import ValidationError
from stock_scanner.config import ScannerConfig, load_config_from_yaml

def test_default_config():
    # Test that default config is valid and weights sum to 1.0
    yaml_str = """
    mode: market_scan
    tickers: ["AAPL", "MSFT"]
    filters:
      min_market_cap: 1000000000
      min_price: 10.0
      min_volume: 200000
      min_current_ratio: 1.0
      max_debt_to_equity: 2.0
    weights:
      category_weights:
        graham_safety: 0.35
        fisher_growth: 0.30
        buffett_quality: 0.35
      graham_safety:
        current_ratio: 0.3
        debt_to_equity: 0.3
        pe_ratio: 0.4
      fisher_growth:
        revenue_growth_yoy: 0.5
        eps_growth_yoy: 0.5
        rd_intensity: 0.0
      buffett_quality:
        roic: 0.4
        operating_margin: 0.3
        fcf_to_net_income: 0.3
    """
    config = load_config_from_yaml(yaml_str)
    assert config.mode == "market_scan"
    assert config.tickers == ["AAPL", "MSFT"]
    assert config.filters.min_price == 10.0
    assert config.weights.category_weights.graham_safety == 0.35
    assert config.weights.graham_safety.current_ratio == 0.3

def test_invalid_mode():
    yaml_str = """
    mode: invalid_mode
    """
    with pytest.raises(ValidationError):
        load_config_from_yaml(yaml_str)

def test_weights_sum_validation():
    # If category weights do not sum to 1.0, validation should fail or raise an error
    yaml_str = """
    weights:
      category_weights:
        graham_safety: 0.5
        fisher_growth: 0.5
        buffett_quality: 0.5  # Sums to 1.5
    """
    with pytest.raises(ValidationError) as excinfo:
        load_config_from_yaml(yaml_str)
    assert "weights must sum to 1.0" in str(excinfo.value)

def test_sector_profile_config():
    yaml_str = """
    sector_profiles:
      Technology:
        filters:
          min_current_ratio: 1.0
          max_debt_to_equity: 1.5
          max_pe_ratio: 50.0
        scoring_ranges:
          pe_ratio: [15.0, 45.0]
        weights:
          category_weights:
            graham_safety: 0.20
            fisher_growth: 0.50
            buffett_quality: 0.30
          graham_safety:
            current_ratio: 0.3
            debt_to_equity: 0.3
            pe_ratio: 0.4
          fisher_growth:
            revenue_growth_yoy: 0.4
            eps_growth_yoy: 0.4
            rd_intensity: 0.2
          buffett_quality:
            roic: 0.4
            operating_margin: 0.3
            fcf_to_net_income: 0.3
    """
    config = load_config_from_yaml(yaml_str)
    assert "Technology" in config.sector_profiles
    tech_prof = config.sector_profiles["Technology"]
    assert tech_prof.filters.max_pe_ratio == 50.0
    assert tech_prof.scoring_ranges.pe_ratio == [15.0, 45.0]
    assert tech_prof.weights.category_weights.fisher_growth == 0.50

def test_save_config(tmp_path):
    from stock_scanner.config import save_config_to_file, load_config_from_file
    yaml_str = """
    mode: market_scan
    tickers: ["AAPL"]
    filters:
      min_price: 10.0
    weights:
      category_weights:
        graham_safety: 0.35
        fisher_growth: 0.30
        buffett_quality: 0.35
      graham_safety:
        current_ratio: 0.3
        debt_to_equity: 0.3
        pe_ratio: 0.4
      fisher_growth:
        revenue_growth_yoy: 0.5
        eps_growth_yoy: 0.5
        rd_intensity: 0.0
      buffett_quality:
        roic: 0.4
        operating_margin: 0.3
        fcf_to_net_income: 0.3
    """
    config = load_config_from_yaml(yaml_str)
    file_path = tmp_path / "test_config.yaml"
    save_config_to_file(config, str(file_path))
    
    # Reload and check
    reloaded = load_config_from_file(str(file_path))
    assert reloaded.mode == "market_scan"
    assert reloaded.tickers == ["AAPL"]
    assert reloaded.filters.min_price == 10.0
    assert reloaded.weights.category_weights.graham_safety == 0.35


