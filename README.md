# US Stock Fundamental Scanner (V1)

A professional, modular, YAML-configured Python package for US stock screening based on fundamental criteria. It uses **yfinance** for real-time market data (price & volume) and **FinanceToolkit** for institutional-grade financial statement calculations.

---

## 🛠️ Architecture

The scanner uses a multi-stage pipeline designed for execution speed and API rate-limit protection:
1. **Stage 1 (Market Filtering - yfinance):** Downloads daily price and volume data in bulk. Excludes penny stocks or low-liquidity stocks instantly (e.g. price < $5, volume < 100k shares).
2. **Stage 2 (Fundamental Screening - FinanceToolkit):** Downloads balance sheets, income statements, and cash flows for the surviving candidates. Excludes stocks that fail key Graham safety levels (e.g. Current Ratio < 1.0, Debt-to-Equity > 2.0).
3. **Stage 3 (Weighted Scoring):** Computes normalized safety, growth, and quality scores, then ranks the passing stocks by a final weighted score.

---

## 📊 Scoring Methodology

Stocks are scored from `0` to `100` across three strategic investment styles:

### 1. Graham-Style Safety (Value & Liquidity)
*   **Current Ratio:** Measures short-term liquidity. Scaled from `1.0` (score 0) to `2.5` (score 100).
*   **Debt-to-Equity:** Measures leverage risk. Scaled from `0.5` (score 100) to `2.0` (score 0).
*   **P/E Ratio:** Value indicator. Scaled from `10.0` (score 100) to `30.0` (score 0). Negative P/E scores `0`.

### 2. Fisher-Style Growth (Growth Quality)
*   **YoY Revenue Growth:** 3-year average. Scaled from `0.0%` (score 0) to `15.0%` (score 100).
*   **YoY EPS Growth:** 3-year average. Scaled from `0.0%` (score 0) to `15.0%` (score 100).
*   **R&D Intensity:** R&D Expenses / Revenue (latest year). Scaled from `0.0%` (score 0) to `10.0%` (score 100).

### 3. Buffett-Style Quality (Moat & Capital Efficiency)
*   **ROIC:** Return on Invested Capital (3-year average). Scaled from `5.0%` (score 0) to `20.0%` (score 100).
*   **Operating Margin:** Latest year. Scaled from `5.0%` (score 0) to `25.0%` (score 100).
*   **FCF to Net Income:** Earnings Quality. Checks if operating cash flow covers CapEx and Net Income. Value of `1.0` or higher scores `100`, negative values score `0`.

---

## ⚙️ Configuration (`config/scanner_config.yaml`)

You can fully customize the scanner behavior (run modes, filters, weights) without changing any code:

```yaml
mode: market_scan # 'market_scan' or 'single_stock'

tickers:
  - AAPL
  - MSFT
  - GOOGL
  - AMZN
  - NVDA

filters:
  min_market_cap: 500000000
  min_price: 5.0
  min_volume: 100000
  min_current_ratio: 1.0
  max_debt_to_equity: 2.0
  max_pe_ratio: 40.0

weights:
  category_weights:
    graham_safety: 0.35
    fisher_growth: 0.30
    buffett_quality: 0.35
  # Sub-weights inside each category must sum to 1.0
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
```

---

## 🚀 How to Run

### Install Dependencies
```bash
pip install pandas yfinance financetoolkit pyyaml pydantic pytest
```

### Full Market Scan
Runs pre-filters and scores all stocks configured in the YAML:
```bash
python main.py --mode market_scan
```

### Single Stock Analysis
Directly deep-dives into specific tickers, bypassing initial price/volume pre-filters:
```bash
python main.py --mode single_stock --tickers MSFT,AAPL
```

### Options
*   `--config`: Path to custom config file (default: `config/scanner_config.yaml`).
*   `--output-dir`: Path to save reports (default: `reports/`).

---

## 📂 Output Reports

Outputs are saved in the configured output directory:
*   `scan_results.csv`: Raw sorted scoring metrics.
*   `scan_report.md`: Visual Markdown report featuring rating labels (e.g. 🟢 Strong Buy, 🔴 Avoid) and metric tables.

<!-- CI trigger -->
