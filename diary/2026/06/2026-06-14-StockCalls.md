# Project DevLog: StockCalls
* **📅 Date**: 2026-06-14
* **🏷️ Tags**: `#Project` `#DevLog`

---

> 🎯 **Progress Summary**
> Completed the implementation of the Stock Fundamental Scanner V2, refactoring the rigid universal filters into a sector-aware, cycle-aware, and risk-aware equity analysis engine with 100% backward-compatible metrics and test coverage.

### 🛠️ Execution Details & Changes
* **Git Commits**: None (working locally)
* **Core File Modifications**:
  * 📄 [config.py](file:///D:/StockCalls/stock_scanner/config.py): Fixed Pydantic `NameError` class loading bug by reordering `WeightConfig` and `SectorProfile` declarations.
  * 📄 [sector_config.py](file:///D:/StockCalls/stock_scanner/engine/sector_config.py): Created sector configs for Software, Semiconductors, Banks/Financials, Utilities, Consumer Staples, Industrials, Energy, and Healthcare.
  * 📄 [risk_flags.py](file:///D:/StockCalls/stock_scanner/engine/risk_flags.py): Created checked red-flags (accounting quality, leverage, going concern) while skipping bank-inappropriate metrics.
  * 📄 [scoring.py](file:///D:/StockCalls/stock_scanner/engine/scoring.py): Created factor scoring formulas with custom equity multiplier ranges for banks.
  * 📄 [explanation.py](file:///D:/StockCalls/stock_scanner/engine/explanation.py): Created rating buckets ("Strong Buy", "Buy", "Watchlist", "Hold", "Avoid", "High Risk") and strengths/weaknesses generator.
  * 📄 [fundamental.py](file:///D:/StockCalls/stock_scanner/engine/fundamental.py): Refactored the core engine batches to bind yfinance sector info, run flags, score factors, and map-back V1 scores for backward compatibility.
  * 📄 [output.py](file:///D:/StockCalls/stock_scanner/output.py): Updated output layouts to format reports with new V2 tables, ratings, and breakdowns.
  * 📄 [test_fundamental.py](file:///D:/StockCalls/tests/test_fundamental.py): Updated unit tests to mock `yfinance` sector details and verify V2 scores.
  * 📄 [architecture_v2.md](file:///C:/Users/gandh/.gemini/antigravity-cli/brain/6e4e1b65-d158-4ef1-940d-bf2758d1e6a0/architecture_v2.md): Created detailed architecture doc and run results.

### 🚨 Troubleshooting
> 🐛 **Problem Encountered**: In V1, JPM was scored as 0.0 Quality and 0.0 Financial Risk because banking operations naturally violate non-financial constraints like Operating Cash Flow, Current Ratio, and Debt-to-Equity.
> 💡 **Solution**: Sector config maps financials to skip FCF/OCF and gross margin tests. Scaled leverage via `Equity Multiplier` in range [5.0, 15.0] instead of `Debt-to-Equity`.

### ⏭️ Next Steps
- [ ] Implement the `Sector Cache Manager` (Task 2 in [2026-06-13-fundamental-engine-v2.md](file:///D:/StockCalls/docs/plans/2026-06-13-fundamental-engine-v2.md)) to cache yfinance sector info locally and prevent slow repeated API queries.
- [ ] Implement command line flag overrides in `main.py` for user qualitative inputs (moat, management, dilution risk).
