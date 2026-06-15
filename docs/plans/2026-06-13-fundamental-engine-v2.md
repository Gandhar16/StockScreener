# Fundamental Engine V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the rigid fundamental analysis engine into a context-aware, sector-aware screening system with adaptive filters, scoring ranges, and weights, while preserving explainability and determinism.

**Architecture:**
- **Local Sector Cache:** Sector/Industry classifications are retrieved via `yfinance` and stored in a local JSON file (`config/sector_cache.json`) to prevent repeated slow API calls.
- **Pydantic Sector Configuration:** The config models are expanded to support a dictionary of sector-specific profiles (`sector_profiles`), mapping sector names to custom filters, weights, and scaling ranges.
- **Dynamic Scoring Engine:** `FundamentalEngine` identifies each stock's sector, looks up the corresponding profile, applies sector-specific hard exclusions, and uses sector-specific normalizers (e.g. higher PE tolerance for Tech, higher Debt tolerance for Financials).

**Tech Stack:** Python 3.14, FinanceToolkit, yfinance, PyYAML, Pandas, Pydantic, Pytest

---

### Task 1: Update Configuration Schema for Sector Profiles
- **Files:**
  - Modify: `stock_scanner/config.py`
  - Modify: `config/scanner_config.yaml`
  - Modify: `tests/test_config.py`
- **Steps:**
  1. Update `stock_scanner/config.py` to declare a new `SectorProfile` model which holds sector-specific `FilterConfig`, `WeightConfig`, and custom `ScoringRanges` (defining target/floor bounds for linear normalizers).
  2. Add `sector_profiles: Dict[str, SectorProfile]` field to `ScannerConfig` with default fallback mappings.
  3. Update `config/scanner_config.yaml` to include realistic profiles for `Technology` (high growth, R&D weighted) and `Financial Services` (higher debt allowance, current ratio ignored).
  4. Write unit tests in `tests/test_config.py` verifying parsing of sector-specific configs.
  5. Run tests to confirm.

### Task 2: Implement Sector Cache Manager
- **Files:**
  - Create: `stock_scanner/data/sector_cache.py`
  - Create: `tests/test_sector_cache.py`
- **Steps:**
  1. Write tests in `tests/test_sector_cache.py` mocking file read/write and yfinance info calls.
  2. Implement `stock_scanner/data/sector_cache.py` to load and save `config/sector_cache.json`.
  3. Include a method `get_sector_and_industry(ticker: str) -> tuple[str, str]` that checks the cache first, falls back to `yf.Ticker(ticker).info` on cache miss, updates the cache file, and defaults to `("General", "General")` on error.
  4. Run tests to verify the cache.

### Task 3: Refactor Fundamental Engine (V2)
- **Files:**
  - Modify: `stock_scanner/engine/fundamental.py`
  - Modify: `tests/test_fundamental.py`
- **Steps:**
  1. Update the mock Toolkit statements and profiles in `tests/test_fundamental.py`.
  2. Modify `stock_scanner/engine/fundamental.py` to:
     - Fetch each stock's sector using the Sector Cache.
     - Look up the active `SectorProfile` from config (falling back to `General` if not defined).
     - Bind the sector profile filters, weights, and scoring ranges to the ticker context.
     - Evaluate hard filters and scores using the bound sector criteria (e.g. current ratio skipped for financials, different PE scaling for tech vs general).
     - Include the resolved Sector/Industry and active profile in the final results DataFrame.
  3. Run tests in `tests/test_fundamental.py` to verify sector-aware scoring.

### Task 4: Update Orchestrator and Output Reports
- **Files:**
  - Modify: `stock_scanner/scanner.py`
  - Modify: `stock_scanner/output.py`
  - Modify: `tests/test_scanner.py`
- **Steps:**
  1. Update `stock_scanner/scanner.py` to handle the sector metadata lookup.
  2. Modify `stock_scanner/output.py` to output the stock's Sector/Industry and show the specific sector profile used in both the CSV and Markdown breakdown report.
  3. Update tests to verify output changes.

### Task 5: End-to-End Integration Run
- **Files:**
  - Execute: `main.py`
- **Steps:**
  1. Run the scanner in `single_stock` mode on a Tech stock (e.g., `NVDA`) and a Financial stock (e.g., `JPM`).
  2. Verify that `NVDA` is evaluated using the `Technology` profile and `JPM` using the `Financial Services` profile.
  3. Confirm the Markdown and CSV files are generated correctly.
