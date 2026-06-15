import pytest
import numpy as np
import pandas as pd
from stock_scanner.engine.technical import MarketStructureEngine

@pytest.fixture
def sample_ohlc_data():
    """
    Generates synthetic daily OHLC data with peaks and troughs to test pivots.
    """
    dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
    
    # Generate a baseline price series with distinct highs and lows
    # Base pattern: a sine wave to create clean peaks and troughs
    x = np.linspace(0, 4 * np.pi, 100)
    base_price = 100.0 + 10.0 * np.sin(x)
    
    close = base_price + np.random.normal(0, 0.5, 100)
    high = close + 1.5
    low = close - 1.5
    open_p = close + np.random.normal(0, 0.2, 100)
    volume = np.random.randint(100000, 500000, 100)
    
    df = pd.DataFrame({
        "Open": open_p,
        "High": high,
        "Low": low,
        "Close": close,
        "Volume": volume
    }, index=dates)
    
    return df

def test_engine_initialization():
    engine = MarketStructureEngine(window_size=3, tolerance_pct=0.02)
    assert engine.window_size == 3
    assert engine.tolerance_pct == 0.02

def test_find_pivots(sample_ohlc_data):
    engine = MarketStructureEngine(window_size=5)
    p_highs, p_lows = engine._find_pivots(sample_ohlc_data)
    
    assert isinstance(p_highs, list)
    assert isinstance(p_lows, list)
    
    # There should be pivot highs and lows detected on a sine wave pattern over 100 days
    assert len(p_highs) > 0
    assert len(p_lows) > 0
    
    for p in p_highs:
        assert "price" in p
        assert "index" in p
        assert "date" in p
        assert "volume" in p

def test_build_horizontal_zones(sample_ohlc_data):
    engine = MarketStructureEngine(window_size=5, tolerance_pct=0.03)
    p_highs, p_lows = engine._find_pivots(sample_ohlc_data)
    current_price = float(sample_ohlc_data["Close"].iloc[-1])
    
    support_zones = engine._build_horizontal_zones(sample_ohlc_data, p_lows, "support", current_price)
    resistance_zones = engine._build_horizontal_zones(sample_ohlc_data, p_highs, "resistance", current_price)
    
    assert isinstance(support_zones, list)
    assert isinstance(resistance_zones, list)
    
    if len(support_zones) > 0:
        zone = support_zones[0]
        # Check standard fields
        assert "type" in zone
        assert zone["type"] == "support_zone"
        assert "center_price" in zone
        assert "price_range" in zone
        assert "touch_count" in zone
        assert "recency_days" in zone
        assert "reaction_strength" in zone
        assert "distance_pct" in zone
        assert "strength_score" in zone

def test_detect_trendlines(sample_ohlc_data):
    # Construct trendline validation test by explicitly creating local valleys on a line
    engine = MarketStructureEngine(window_size=5)
    
    # Create pivots aligned on a perfect linear support trendline: y = 0.5 * x + 50
    # For 100 trading days
    dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
    
    # Base Low series is higher than the trendline
    lows = [0.5 * i + 60.0 for i in range(100)]
    # Set explicit valleys on the line at indices 10, 40, 70
    lows[10] = 0.5 * 10 + 50.0  # 55.0
    lows[40] = 0.5 * 40 + 50.0  # 70.0
    lows[70] = 0.5 * 70 + 50.0  # 85.0
    
    df = pd.DataFrame({
        "Open": [80.0] * 100,
        "High": [120.0] * 100,
        "Low": lows,
        "Close": [90.0] * 100,
        "Volume": [100000] * 100
    }, index=dates)
    
    current_price = 90.0
    trendlines = engine._detect_trendlines(df, [], "support", current_price)
    
    # There should be a trendline matching slope ~0.5 and intercept ~50
    assert len(trendlines) > 0
    best_tl = trendlines[0]
    assert best_tl["type"] == "support_trendline"
    assert pytest.approx(best_tl["slope"], 0.01) == 0.5
    assert pytest.approx(best_tl["intercept"], 0.01) == 50.0
    assert best_tl["touch_count"] >= 3

def test_analyze_structure(sample_ohlc_data):
    engine = MarketStructureEngine(window_size=5)
    analysis = engine.analyze_structure(sample_ohlc_data)
    
    assert "support_zones" in analysis
    assert "resistance_zones" in analysis
    assert "support_trendlines" in analysis
    assert "resistance_trendlines" in analysis
    assert "context" in analysis
    
    # Should cap at 23
    assert len(analysis["support_zones"]) <= 23
    assert len(analysis["resistance_zones"]) <= 23
    
    # Verify context is a string
    assert isinstance(analysis["context"], str)

def test_empty_dataframe():
    engine = MarketStructureEngine()
    empty_df = pd.DataFrame()
    analysis = engine.analyze_structure(empty_df)
    
    assert analysis["support_zones"] == []
    assert analysis["resistance_zones"] == []
    assert "Insufficient Data" in analysis["context"]
