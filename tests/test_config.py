"""Tests for configuration loading."""

import pytest

from stock_scanner.config import ScannerConfig, load_config_from_file


def test_load_default_config():
    """Test loading default configuration."""
    config = ScannerConfig()
    assert config.mode == "market_scan"
    assert len(config.tickers) == 0
    assert config.filters.min_market_cap == 500_000_000
    assert config.filters.min_price == 5.0


@pytest.mark.skip(reason="Windows temp dir permission issue")
def test_load_config_from_file(tmp_path):
    """Test loading configuration from YAML file."""
    yaml_content = """
mode: single_stock
tickers:
  - AAPL
  - MSFT
filters:
  min_market_cap: 1000000000
  min_price: 10.0
  min_volume: 500000
weights:
  category_weights:
    graham_safety: 0.4
    fisher_growth: 0.3
    buffett_quality: 0.3
"""
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml_content)

    config = load_config_from_file(str(config_file))

    assert config.mode == "single_stock"
    assert config.tickers == ["AAPL", "MSFT"]
    assert config.filters.min_market_cap == 1_000_000_000
    assert config.filters.min_price == 10.0
    assert config.weights.category_weights.graham_safety == 0.4
