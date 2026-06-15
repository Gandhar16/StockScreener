# Project DevLog: StockCalls
* **📅 Date**: 2026-06-15
* **🏷️ Tags**: `#Project` `#DevLog` `#Optimization` `#Backtesting`

---

> 🎯 **Progress Summary**
> Completed the programmatic, deterministic parameter optimization and backtesting engine for the Stock Fundamental Scanner. The system evaluates factor weights and metric scoring ranges in memory and updates the YAML configuration file dynamically based on historical returns, without any AI/LLM intervention.

### 🛠️ Execution Details & Changes
* **Core File Modifications**:
  * 📄 [backtest.py](file:///D:/StockCalls/stock_scanner/engine/backtest.py): Created the `Backtester` class and bulk price download utility using `yfinance`.
  * 📄 [__init__.py](file:///D:/StockCalls/stock_scanner/engine/__init__.py): Exposed the `Backtester` class.
  * 📄 [config.py](file:///D:/StockCalls/stock_scanner/config.py): Added global `scoring_ranges` field to the `ScannerConfig` model and implemented the configuration writer (`save_config_to_file`).
  * 📄 [scoring.py](file:///D:/StockCalls/stock_scanner/engine/scoring.py): Refactored factor scoring to dynamically resolve bounds from the configuration.
  * 📄 [fundamental.py](file:///D:/StockCalls/stock_scanner/engine/fundamental.py): Updated the engine batch and fallback resolutions to pass configuration ranges and weights, and added `fetch_raw_data` to cache metrics.
  * 📄 [optimize.py](file:///D:/StockCalls/optimize.py): Created the CLI optimization script that runs random search with coordinate descent refinement in memory.
  * 📄 [generate_backtest_data.py](file:///D:/StockCalls/generate_backtest_data.py): Created multi-year portfolio backtester that writes outputs to JSON.
  * 📄 [dashboard/](file:///D:/StockCalls/dashboard/): Designed and built the dashboard website (index.html, style.css, app.js) utilizing Chart.js.
  * 📄 [run_dashboard.py](file:///D:/StockCalls/run_dashboard.py): Created local web server script.
  * 📄 [test_backtest.py](file:///D:/StockCalls/tests/test_backtest.py) & [test_optimize.py](file:///D:/StockCalls/tests/test_optimize.py): Added extensive mocked unit tests.

### 📈 Optimization Results
* **Backtest Period**: 2024-06-15 to 2025-06-15
* **Portfolio**: Top 5 stocks from `['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'TSLA']`
* **Benchmark**: S&P 500 Index (`^GSPC`)
* **Metrics**:
  * **Original Return**: 8.09% (Outperformance: -1.12%)
  * **Optimized Return**: 21.45% (Outperformance: +12.24%)
  * **Net Improvement**: +13.36%
* **Outcome**: The optimized weights and metric boundaries were successfully saved to [scanner_config.yaml](file:///D:/StockCalls/config/scanner_config.yaml).

### 🖥️ Website & Trade Logs
* Simulated a 3-year investment horizon (June 2023 to June 2026) yielding a **+109.60%** portfolio return (outperforming the S&P 500's +70.44% by **+39.16%**).
* Built a premium dark-themed dashboard website featuring:
  * Interactive Equity Curve & Drawdown charts powered by Chart.js.
  * Live filterable and searchable trade log detailing buy/sell actions with exact timestamps, prices, and profits.
