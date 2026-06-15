# Programmatic Optimization & Backtesting Implementation Plan

**Goal:** Build a purely programmatic, deterministic backtesting and parameter optimization engine for the Stock Fundamental Scanner. The system will mathematically optimize factor weights and metric ranges based on historical stock returns and save the results back to the scanner configuration, without any AI or LLM interference.

---

### Task 1: Create the Backtesting Engine
- **Files:**
  - Create: `stock_scanner/engine/backtest.py`
- **Steps:**
  - [x] Implement historical price retrieval helper (obtaining price at start date and price after $M$ months using `yfinance` history).
  * [x] Implement `Backtester` class that takes a historical start date, runs the V2 fundamental screening on that date's financial statements, selects the top $N$ stocks, and calculates the average holding period return of those stocks.
  * [x] Add utility to compute S&P 500 index return over the same period as a benchmark benchmark.

### Task 2: Create the Optimizer Script
- **Files:**
  - Create: `optimize.py`
- **Steps:**
  - [ ] Implement an objective function that evaluates a candidate set of weights and scoring ranges, runs the backtester, and returns the negative portfolio outperformance (to be minimized).
  * [ ] Implement a programmatic optimization loop (e.g. grid search or random search) that finds the weights and boundaries that maximize historical returns.
  * [ ] Build a CLI entrypoint supporting overrides for holding period, tickers list, and optimization bounds.

### Task 3: Implement Config Writer in Config Layer
- **Files:**
  - Modify: `stock_scanner/config.py`
- **Steps:**
  - [x] Add a utility function/method to update the `ScannerConfig` Pydantic model with new weights or ranges.
  * [x] Add a save utility that dumps the updated `ScannerConfig` back to a YAML configuration file (`config/scanner_config.yaml`), replacing the old weights and ranges.

### Task 4: Test and Verify Integration
- **Files:**
  - Create: `tests/test_backtest.py`
- **Steps:**
  - [x] Write unit tests to mock historical statement calculations and historical prices to verify backtester functionality.
  * [x] Run `pytest` to ensure all tests pass.
  * [x] Execute a live optimization run using actual historical stock data (e.g. looking back 12 months) and verify the YAML configuration is updated with the mathematically optimized weights.

### Task 5: Technical Indicator-Based Entries & Exits (Future Enhancement)
- **Goal:** Replace the fixed holding period constraint with dynamic, technical-indicator-driven entry and exit signals to maximize profit and protect against drawdowns.
- **Steps:**
  - [ ] Implement technical indicator calculators (e.g. Moving Averages, RSI, MACD) to generate buy and sell triggers.
  - [ ] Update the backtesting engine to evaluate daily/weekly indicators instead of forcing fixed 12-month holds.
  - [ ] Combine fundamental scores as a selection filter (e.g. trade only high-quality stocks) with technical signals determining exact transaction entry and exit timings.
  - [ ] Backtest the combined strategy, log the trades, and compare performance results on the web dashboard.
