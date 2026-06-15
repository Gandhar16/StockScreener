# Stock Scanner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a modular, YAML-configured US Stock Scanner package in Python that screens stocks on fundamental metrics based on Graham-style safety, Fisher-style growth, and Buffett-style quality, using FinanceToolkit and yfinance.

**Architecture:** 
- A YAML configuration defines filters, weights, ticker source list, and run mode.
- A `Config` Pydantic model parses and validates the configuration.
- A `DataProvider` fetches basic ticker lists and real-time prices/volumes using `yfinance`.
- A `FundamentalEngine` performs raw data calculations using `FinanceToolkit`, executing hard filters, calculating safety/growth/quality metrics, and producing a weighted scorecard.
- An `Orchestrator` runs the scan (either full market scan on the selected list or single-stock mode).
- An `OutputFormatter` generates clean Markdown/CSV reports.

**Tech Stack:** Python 3.14, FinanceToolkit, yfinance, PyYAML, Pandas, Pydantic, Pytest

---

### Task 1: Package Configuration & Validation
- **Files:**
  - Create: `config/scanner_config.yaml`
  - Create: `stock_scanner/config.py`
  - Create: `tests/test_config.py`
- **Steps:**
  1. Write tests in `tests/test_config.py` verifying YAML parsing, default values, and weight validation.
  2. Implement `stock_scanner/config.py` using `pydantic` and `pyyaml` to load and validate configurations.
  3. Create `config/scanner_config.yaml` with realistic filters (current ratio > 1.0, debt/equity < 2.0) and weights.
  4. Run pytest to verify configuration parsing.

### Task 2: Data Provider Layer (yfinance)
- **Files:**
  - Create: `stock_scanner/data/__init__.py`
  - Create: `stock_scanner/data/provider.py`
  - Create: `tests/test_provider.py`
- **Steps:**
  1. Write tests in `tests/test_provider.py` mocking yfinance calls to return stock metadata (market cap, price, volume).
  2. Implement `stock_scanner/data/provider.py` to fetch S&P 500 / custom tickers, get market caps, prices, and volumes, and filter them based on basic thresholds (market cap, price, volume).
  3. Verify the provider using pytest.

### Task 3: Fundamental Engine Layer (FinanceToolkit)
- **Files:**
  - Create: `stock_scanner/engine/__init__.py`
  - Create: `stock_scanner/engine/fundamental.py`
  - Create: `tests/test_fundamental.py`
- **Steps:**
  1. Write tests in `tests/test_fundamental.py` mocking `financetoolkit.Toolkit` results.
  2. Implement `stock_scanner/engine/fundamental.py` to load financial ratios (Current Ratio, Debt-to-Equity, PE, ROIC, Operating Margin, FCF/Net Income, Revenue/EPS growth).
  3. Implement normalizers/scorers for Graham (safety), Fisher (growth), and Buffett (quality) metrics.
  4. Implement weighted scoring and sorting of stocks.
  5. Verify the engine using pytest.

### Task 4: CLI Scanner Orchestrator
- **Files:**
  - Create: `stock_scanner/__init__.py`
  - Create: `stock_scanner/scanner.py`
  - Create: `stock_scanner/output.py`
  - Create: `tests/test_scanner.py`
- **Steps:**
  1. Write tests in `tests/test_scanner.py` for orchestrator execution flow.
  2. Implement `stock_scanner/output.py` to format results into CSV and a beautiful Markdown table.
  3. Implement `stock_scanner/scanner.py` to coordinate the data provider, fundamental engine, and output generation.
  4. Run tests to confirm integration works.

### Task 5: Main Entrypoint & CLI Integration
- **Files:**
  - Create: `main.py`
  - Create: `pyproject.toml`
- **Steps:**
  1. Implement `pyproject.toml` defining the project metadata, dependencies, and CLI entrypoint.
  2. Implement `main.py` to load config, initialize scanner, and run the selected mode.
  3. Run a manual single-stock scan on a test ticker (e.g. `AAPL`) and inspect the output.
  4. Run a small multi-stock scan (e.g. `AAPL`, `MSFT`, `GOOG`) and inspect the final Markdown/CSV report.
