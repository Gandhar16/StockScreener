"""Tests for stock_scanner.engine.relative_strength (no network)."""

import numpy as np
import pandas as pd

from stock_scanner.engine.relative_strength import (
    DEFAULT_BENCHMARK,
    benchmark_for,
    mansfield_rs,
    rs_gate,
    rs_percentile,
)


def _series(vals, start="2023-01-02"):
    idx = pd.bdate_range(start, periods=len(vals))
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def _flat_bench(n=400):
    rng = np.random.default_rng(3)
    return _series(100 + rng.normal(0, 0.2, n))


class TestBenchmarkFor:
    def test_nse(self):
        assert benchmark_for("RELIANCE.NS") == "^NSEI"

    def test_bse(self):
        assert benchmark_for("TCS.BO") == "^BSESN"

    def test_us_default(self):
        assert benchmark_for("NVDA") == DEFAULT_BENCHMARK

    def test_case_insensitive(self):
        assert benchmark_for("infy.ns") == "^NSEI"

    def test_custom_map(self):
        assert benchmark_for("ABC.XY", {".XY": "^XYZ"}) == "^XYZ"


class TestMansfieldRS:
    def test_outperformer_positive(self):
        n = 400
        stock = _series(100 * (1 + 0.002) ** np.arange(n))  # steady outperformance
        rs = mansfield_rs(stock, _flat_bench(n))
        assert rs["rs_mansfield"] > 0
        assert rs["rs_trend"] == "improving"
        assert rs["rs_new_high"] is True

    def test_underperformer_negative(self):
        n = 400
        stock = _series(100 * (1 - 0.002) ** np.arange(n))
        rs = mansfield_rs(stock, _flat_bench(n))
        assert rs["rs_mansfield"] < 0
        assert rs["rs_trend"] == "deteriorating"

    def test_inline_with_market_near_zero(self):
        n = 400
        bench = _flat_bench(n)
        stock = bench * 2.0  # identical shape, different scale
        rs = mansfield_rs(stock, bench)
        assert abs(rs["rs_mansfield"]) < 3.0

    def test_missing_benchmark(self):
        stock = _series(np.linspace(100, 120, 300))
        rs = mansfield_rs(stock, None)
        assert rs["rs_mansfield"] is None

    def test_calendar_mismatch_inner_join(self):
        # Stock trades some days the benchmark doesn't (holiday mismatch)
        n = 300
        stock = _series(np.linspace(100, 130, n))
        bench = _flat_bench(n)
        bench = bench[bench.index.dayofweek != 2]  # drop all Wednesdays
        rs = mansfield_rs(stock, bench)
        assert rs["rs_mansfield"] is not None

    def test_too_short_overlap(self):
        stock = _series(np.linspace(100, 110, 30))
        bench = _series(np.full(30, 100.0))
        rs = mansfield_rs(stock, bench)
        assert rs["rs_mansfield"] is None


class TestRsGate:
    def test_bull_pass_on_strong_rs(self):
        g = rs_gate("bullish", {"rs_mansfield": 12.0, "rs_trend": "improving"})
        assert g["rs_pass"] is True

    def test_bull_pass_on_improving_laggard(self):
        g = rs_gate("bullish", {"rs_mansfield": -8.0, "rs_trend": "improving"})
        assert g["rs_pass"] is True

    def test_bull_fail_on_stagnant_laggard(self):
        g = rs_gate("bullish", {"rs_mansfield": -10.0, "rs_trend": "flat"})
        assert g["rs_pass"] is False

    def test_bull_hard_fail(self):
        g = rs_gate("bullish", {"rs_mansfield": -25.0, "rs_trend": "improving"})
        assert g["rs_pass"] is False

    def test_missing_rs_pass_through(self):
        g = rs_gate("bullish", {"rs_mansfield": None, "rs_trend": None})
        assert g["rs_pass"] is None

    def test_bear_fail_on_market_leader(self):
        g = rs_gate("bearish", {"rs_mansfield": 25.0, "rs_trend": "improving"})
        assert g["rs_pass"] is False

    def test_bear_pass_on_weakness(self):
        g = rs_gate("bearish", {"rs_mansfield": -15.0, "rs_trend": "deteriorating"})
        assert g["rs_pass"] is True


class TestRsPercentile:
    def test_ranking_order(self):
        vals = {"A": 30.0, "B": 0.0, "C": -30.0}
        pct = rs_percentile(vals)
        assert pct["A"] > pct["B"] > pct["C"]
        assert 1 <= pct["C"] and pct["A"] <= 99

    def test_none_values_stay_none(self):
        pct = rs_percentile({"A": 10.0, "B": None, "C": -5.0})
        assert pct["B"] is None
        assert pct["A"] is not None

    def test_per_benchmark_groups(self):
        vals = {"NVDA": 20.0, "INTC": -20.0, "TCS.NS": 5.0, "WIPRO.NS": -5.0}
        groups = {"NVDA": "^GSPC", "INTC": "^GSPC",
                  "TCS.NS": "^NSEI", "WIPRO.NS": "^NSEI"}
        pct = rs_percentile(vals, groups)
        # each group ranked independently: both group leaders share top rank
        assert pct["NVDA"] == pct["TCS.NS"]
        assert pct["INTC"] == pct["WIPRO.NS"]
        assert pct["NVDA"] > pct["INTC"]

    def test_singleton_group_is_none(self):
        pct = rs_percentile({"A": 5.0}, {"A": "^GSPC"})
        assert pct["A"] is None
