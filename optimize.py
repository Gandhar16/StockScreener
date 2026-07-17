import argparse
import logging
import os
import random

import pandas as pd

from stock_scanner.config import ScannerConfig, load_config_from_file, save_config_to_file
from stock_scanner.engine.backtest import get_bulk_historical_returns
from stock_scanner.engine.fundamental import FundamentalEngine
from stock_scanner.engine.scoring import calculate_factor_scores

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Search bounds for metric scoring ranges [min_lower, max_lower], [min_upper, max_upper]
BOUNDS = {
    "pe_ratio": ((5.0, 15.0), (20.0, 45.0)),
    "current_ratio": ((0.5, 1.5), (2.0, 4.0)),
    "debt_to_equity": ((0.1, 0.8), (1.5, 3.5)),
    "revenue_growth_yoy": ((-0.05, 0.05), (0.10, 0.30)),
    "eps_growth_yoy": ((-0.05, 0.05), (0.10, 0.30)),
    "roic": ((0.02, 0.08), (0.12, 0.30)),
    "operating_margin": ((0.02, 0.08), (0.15, 0.35)),
}


def random_weights(n: int) -> list[float]:
    """Generates n random weights that sum to 1.0."""
    w = [random.random() for _ in range(n)]
    s = sum(w)
    return [x / s for x in w]


def sample_config_params() -> dict:
    """Samples a random configuration of weights and scoring ranges within the bounds."""
    params = {}

    # 1. Weights
    cw = random_weights(3)
    params["category_weights"] = {
        "graham_safety": cw[0],
        "fisher_growth": cw[1],
        "buffett_quality": cw[2],
    }

    gw = random_weights(3)
    params["graham_safety"] = {"current_ratio": gw[0], "debt_to_equity": gw[1], "pe_ratio": gw[2]}

    fw = random_weights(3)
    params["fisher_growth"] = {
        "revenue_growth_yoy": fw[0],
        "eps_growth_yoy": fw[1],
        "rd_intensity": fw[2],
    }

    bw = random_weights(3)
    params["buffett_quality"] = {
        "roic": bw[0],
        "operating_margin": bw[1],
        "fcf_to_net_income": bw[2],
    }

    # 2. Ranges
    params["scoring_ranges"] = {}
    for key, (b_low, b_high) in BOUNDS.items():
        low = random.uniform(b_low[0], b_low[1])
        high = random.uniform(b_high[0], b_high[1])
        if low >= high:
            low, high = high, low
        params["scoring_ranges"][key] = [low, high]

    return params


def get_config_params_from_model(config: ScannerConfig) -> dict:
    """Extracts parameters from a ScannerConfig pydantic model to build a params dict."""
    return {
        "category_weights": {
            "graham_safety": config.weights.category_weights.graham_safety,
            "fisher_growth": config.weights.category_weights.fisher_growth,
            "buffett_quality": config.weights.category_weights.buffett_quality,
        },
        "graham_safety": {
            "current_ratio": config.weights.graham_safety.current_ratio,
            "debt_to_equity": config.weights.graham_safety.debt_to_equity,
            "pe_ratio": config.weights.graham_safety.pe_ratio,
        },
        "fisher_growth": {
            "revenue_growth_yoy": config.weights.fisher_growth.revenue_growth_yoy,
            "eps_growth_yoy": config.weights.fisher_growth.eps_growth_yoy,
            "rd_intensity": config.weights.fisher_growth.rd_intensity,
        },
        "buffett_quality": {
            "roic": config.weights.buffett_quality.roic,
            "operating_margin": config.weights.buffett_quality.operating_margin,
            "fcf_to_net_income": config.weights.buffett_quality.fcf_to_net_income,
        },
        "scoring_ranges": {
            "pe_ratio": config.scoring_ranges.pe_ratio,
            "current_ratio": config.scoring_ranges.current_ratio,
            "debt_to_equity": config.scoring_ranges.debt_to_equity,
            "revenue_growth_yoy": config.scoring_ranges.revenue_growth_yoy,
            "eps_growth_yoy": config.scoring_ranges.eps_growth_yoy,
            "roic": config.scoring_ranges.roic,
            "operating_margin": config.scoring_ranges.operating_margin,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Programmatic Parameter Optimizer for Stock Scanner"
    )
    parser.add_argument(
        "--config", type=str, default="config/scanner_config.yaml", help="Path to config file"
    )
    parser.add_argument(
        "--tickers", type=str, default="", help="Comma-separated tickers for backtesting"
    )
    parser.add_argument(
        "--start-date", type=str, default="2023-06-15", help="Backtesting screen date (YYYY-MM-DD)"
    )
    parser.add_argument("--holding-months", type=int, default=12, help="Holding period in months")
    parser.add_argument(
        "--top-n", type=int, default=5, help="Number of selected stocks in portfolio"
    )
    parser.add_argument("--iterations", type=int, default=500, help="Random search iterations")
    parser.add_argument(
        "--refine-steps", type=int, default=100, help="Coordinate descent refinement steps"
    )
    parser.add_argument(
        "--save", action="store_true", default=True, help="Save optimized parameters to config file"
    )
    parser.add_argument(
        "--no-save",
        action="store_false",
        dest="save",
        help="Do not save optimized parameters to config file",
    )
    parser.add_argument("--benchmark", type=str, default="^GSPC", help="Benchmark ticker")

    args = parser.parse_args()

    # Seed for determinism
    random.seed(42)

    # 1. Load config
    logger.info(f"Loading scanner configuration from {args.config}...")
    if not os.path.exists(args.config):
        logger.error(f"Config file not found at {args.config}")
        return
    config = load_config_from_file(args.config)

    # 2. Resolve tickers list
    tickers = []
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif config.tickers:
        tickers = config.tickers
    else:
        tickers = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "AMZN",
            "META",
            "NVDA",
            "TSLA",
            "BRK-B",
            "JNJ",
            "V",
            "WMT",
            "PG",
            "JPM",
        ]
    logger.info(f"Using tickers for backtest optimization: {tickers}")

    # Parse dates
    start_ts = pd.Timestamp(args.start_date)
    end_ts = start_ts + pd.DateOffset(months=args.holding_months)
    as_of_year = start_ts.year - 1

    # 3. Fetch raw financial data and historical returns exactly once
    logger.info("Initializing fundamental data fetching...")
    engine = FundamentalEngine(config)
    raw_data = engine.fetch_raw_data(tickers, as_of_year=as_of_year)

    if not raw_data:
        logger.error("No fundamental data retrieved. Check internet connection and tickers.")
        return

    # Download bulk historical prices for return calculations
    logger.info("Fetching price history...")
    returns = get_bulk_historical_returns(tickers, start_ts, end_ts, args.benchmark)

    # Evaluate return function
    def evaluate(config_params: dict) -> float:
        scores = []
        for item in raw_data:
            ticker = item["ticker"]
            sector = item["sector"]
            metrics = item["metrics"]
            penalty = item["red_flag_penalty"]
            is_disq = item["is_disqualified"]

            if is_disq:
                continue

            cw = config_params["category_weights"]
            gw = config_params["graham_safety"]
            config_params["fisher_growth"]
            config_params["buffett_quality"]
            scoring_ranges = config_params["scoring_ranges"]

            is_fin = (
                "financial" in sector.lower()
                or "bank" in sector.lower()
                or gw.get("current_ratio", 1.0) == 0.0
            )
            if is_fin:
                relevant_metrics = [
                    "roe",
                    "equity_multiplier",
                    "price_to_book",
                    "dividend_yield",
                    "operating_margin",
                ]
                irrelevant_metrics = [
                    "current_ratio",
                    "debt_to_equity",
                    "fcf_to_net_income",
                    "ev_to_ebitda",
                    "price_to_sales",
                    "gross_margin",
                ]
                pref_val_methods = ["price_to_book", "price_to_earnings"]
            else:
                relevant_metrics = list(scoring_ranges.keys())
                irrelevant_metrics = []
                pref_val_methods = ["price_to_earnings"]

            candidate_sect_config = {
                "relevant_metrics": relevant_metrics,
                "irrelevant_metrics": irrelevant_metrics,
                "preferred_valuation_methods": pref_val_methods,
                "weights": {
                    "business_quality": cw.get("buffett_quality", 0.35),
                    "valuation": cw.get("graham_safety", 0.35) * 0.6,
                    "financial_risk": cw.get("graham_safety", 0.35) * 0.4,
                    "growth": cw.get("fisher_growth", 0.30),
                    "capital_allocation": 0.0,
                },
                "scoring_ranges": scoring_ranges,
            }

            # Score
            ticker_scores, _ = calculate_factor_scores(metrics, candidate_sect_config)

            for key in ticker_scores:
                ticker_scores[key] = max(0.0, ticker_scores[key] - penalty)

            w = candidate_sect_config["weights"]
            total_score = (
                ticker_scores.get("business_quality", 50.0) * w.get("business_quality", 0.25)
                + ticker_scores.get("valuation", 50.0) * w.get("valuation", 0.25)
                + ticker_scores.get("financial_risk", 50.0) * w.get("financial_risk", 0.20)
                + ticker_scores.get("growth", 50.0) * w.get("growth", 0.20)
                + ticker_scores.get("capital_allocation", 50.0) * w.get("capital_allocation", 0.10)
            )
            scores.append((ticker, total_score))

        if not scores:
            return 0.0

        scores.sort(key=lambda x: x[1], reverse=True)
        top_selected = [x[0] for x in scores[: args.top_n]]

        port_returns = [
            returns.get(t, 0.0) for t in top_selected if t in returns and not pd.isna(returns[t])
        ]
        if not port_returns:
            return 0.0
        return sum(port_returns) / len(port_returns)

    # 4. Evaluate Original Configuration
    original_params = get_config_params_from_model(config)
    original_return = evaluate(original_params)
    benchmark_return = returns.get(args.benchmark, 0.0)

    logger.info(f"Original Configuration Portfolio Return: {original_return:.2%}")
    logger.info(f"Benchmark ({args.benchmark}) Return: {benchmark_return:.2%}")

    # 5. Optimization Loop: Step 1 - Random Search
    logger.info(f"Starting Random Search phase with {args.iterations} iterations...")
    best_params = original_params
    best_return = original_return

    for _i in range(args.iterations):
        cand = sample_config_params()
        ret = evaluate(cand)
        if ret > best_return:
            best_return = ret
            best_params = cand

    logger.info(f"Random Search Phase complete. Best Return: {best_return:.2%}")

    # 6. Optimization Loop: Step 2 - Coordinate Descent Refinement
    logger.info(f"Starting Coordinate Descent Refinement with {args.refine_steps} steps...")

    def perturb_weights(w_dict: dict, strength: float = 0.05) -> dict:
        keys = list(w_dict.keys())
        w_list = [w_dict[k] for k in keys]
        perturbed = [max(0.01, w + random.gauss(0, strength)) for w in w_list]
        s = sum(perturbed)
        norm = [p / s for p in perturbed]
        return {k: norm[i] for i, k in enumerate(keys)}

    for _step in range(args.refine_steps):
        cand = {
            "category_weights": best_params["category_weights"].copy(),
            "graham_safety": best_params["graham_safety"].copy(),
            "fisher_growth": best_params["fisher_growth"].copy(),
            "buffett_quality": best_params["buffett_quality"].copy(),
            "scoring_ranges": {k: v.copy() for k, v in best_params["scoring_ranges"].items()},
        }

        # Randomly choose what type of change to make
        change_type = random.choice(["cat_weights", "sub_weights", "ranges"])

        if change_type == "cat_weights":
            cand["category_weights"] = perturb_weights(cand["category_weights"])
        elif change_type == "sub_weights":
            sub_key = random.choice(["graham_safety", "fisher_growth", "buffett_quality"])
            cand[sub_key] = perturb_weights(cand[sub_key])
        else:
            # Perturb a scoring range
            range_key = random.choice(list(BOUNDS.keys()))
            bounds = BOUNDS[range_key]
            # Randomly perturb lower or upper bound
            low, high = cand["scoring_ranges"][range_key]
            if random.choice([True, False]):
                # Perturb lower bound
                low = max(bounds[0][0], min(bounds[0][1], low + random.gauss(0, 0.5)))
            else:
                # Perturb upper bound
                high = max(bounds[1][0], min(bounds[1][1], high + random.gauss(0, 0.5)))

            if low >= high:
                low, high = high, low
            cand["scoring_ranges"][range_key] = [low, high]

        ret = evaluate(cand)
        if ret > best_return:
            best_return = ret
            best_params = cand

    logger.info(f"Refinement complete. Optimized Return: {best_return:.2%}")

    # 7. Print Outperformance Summary
    original_return - benchmark_return
    best_return - benchmark_return
    best_return - original_return

    # 8. Save updated config if requested
    if args.save:
        logger.info("Updating scanner config models with optimized parameters...")

        # Category weights
        config.weights.category_weights.graham_safety = best_params["category_weights"][
            "graham_safety"
        ]
        config.weights.category_weights.fisher_growth = best_params["category_weights"][
            "fisher_growth"
        ]
        config.weights.category_weights.buffett_quality = best_params["category_weights"][
            "buffett_quality"
        ]

        # Graham weights
        config.weights.graham_safety.current_ratio = best_params["graham_safety"]["current_ratio"]
        config.weights.graham_safety.debt_to_equity = best_params["graham_safety"]["debt_to_equity"]
        config.weights.graham_safety.pe_ratio = best_params["graham_safety"]["pe_ratio"]

        # Fisher weights
        config.weights.fisher_growth.revenue_growth_yoy = best_params["fisher_growth"][
            "revenue_growth_yoy"
        ]
        config.weights.fisher_growth.eps_growth_yoy = best_params["fisher_growth"]["eps_growth_yoy"]
        config.weights.fisher_growth.rd_intensity = best_params["fisher_growth"]["rd_intensity"]

        # Buffett weights
        config.weights.buffett_quality.roic = best_params["buffett_quality"]["roic"]
        config.weights.buffett_quality.operating_margin = best_params["buffett_quality"][
            "operating_margin"
        ]
        config.weights.buffett_quality.fcf_to_net_income = best_params["buffett_quality"][
            "fcf_to_net_income"
        ]

        # Scoring ranges
        config.scoring_ranges.pe_ratio = best_params["scoring_ranges"]["pe_ratio"]
        config.scoring_ranges.current_ratio = best_params["scoring_ranges"]["current_ratio"]
        config.scoring_ranges.debt_to_equity = best_params["scoring_ranges"]["debt_to_equity"]
        config.scoring_ranges.revenue_growth_yoy = best_params["scoring_ranges"][
            "revenue_growth_yoy"
        ]
        config.scoring_ranges.eps_growth_yoy = best_params["scoring_ranges"]["eps_growth_yoy"]
        config.scoring_ranges.roic = best_params["scoring_ranges"]["roic"]
        config.scoring_ranges.operating_margin = best_params["scoring_ranges"]["operating_margin"]

        logger.info(f"Saving updated configuration to {args.config}...")
        try:
            save_config_to_file(config, args.config)
            logger.info("Configuration successfully updated and saved.")
        except Exception as e:
            logger.error(f"Failed to save optimized configuration: {e}")


if __name__ == "__main__":
    main()
