# 專案上下文 (Agent Context)：StockCalls

> **最後更新時間**：2026-06-14 16:40
> **自動生成**：由 `prepare_context.py` 產生，供 AI Agent 快速掌握專案全局

---

## 🎯 1. 專案目標 (Project Goal)
* **核心目的**：A professional, modular, YAML-configured Python package for US stock screening based on fundamental criteria. It uses **yfinance** for real-time market data (price & volume) and **FinanceToolkit** for institutional-grade financial statement calculations.
* _完整說明見 [README.md](README.md)_

## 🛠️ 2. 技術棧與環境 (Tech Stack & Environment)
* **Python 專案**：使用 pyproject.toml 管理
* _詳見 pyproject.toml 的 dependencies 區塊_

### 原始設定檔

<details><summary>pyproject.toml</summary>

```toml
[build-system]
requires = ["setuptools>=61.0.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "stock_scanner"
version = "1.0.0"
description = "A professional fundamental analysis stock scanner using FinanceToolkit and yfinance"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "Antigravity Dev Team"}
]
dependencies = [
    "pandas",
    "yfinance",
    "financetoolkit",
    "pyyaml",
    "pydantic>=2.0"
]

[project.optional-dependencies]
dev = [
    "pytest"
]

[project.scripts]
stock-scan = "main:main"

```
</details>

## 📂 3. 核心目錄結構 (Core Structure)
_(💡 AI 讀取守則：請依據此結構尋找對應檔案，勿盲目猜測路徑)_
```text
StockCalls/
├── AGENT_CONTEXT.md
├── ImprovementInstrtuctions.txt
├── README.md
├── config
│   └── scanner_config.yaml
├── diary
│   └── 2026
│       └── 06
├── docs
│   └── plans
│       ├── 2026-06-12-stock-scanner.md
│       └── 2026-06-13-fundamental-engine-v2.md
├── main.py
├── pyproject.toml
├── reports
│   ├── scan_report.md
│   └── scan_results.csv
├── stock_scanner
│   ├── __init__.py
│   ├── config.py
│   ├── data
│   │   ├── __init__.py
│   │   └── provider.py
│   ├── engine
│   │   ├── __init__.py
│   │   ├── explanation.py
│   │   ├── fundamental.py
│   │   ├── risk_flags.py
│   │   ├── scoring.py
│   │   └── sector_config.py
│   ├── output.py
│   └── scanner.py
└── tests
    ├── test_config.py
    ├── test_fundamental.py
    ├── test_provider.py
    └── test_scanner.py
```

## 🏛️ 4. 架構與設計約定 (Architecture & Conventions)
* _（尚無 `.auto-skill-local.md`，專案踩坑經驗將在開發過程中自動累積）_

## 🚦 5. 目前進度與待辦 (Current Status & TODO)
_(自動提取自最近日記 2026-06-14)_

### 🚧 待辦事項
- [ ] Implement the `Sector Cache Manager` (Task 2 in [2026-06-13-fundamental-engine-v2.md](file:///D:/StockCalls/docs/plans/2026-06-13-fundamental-engine-v2.md)) to cache yfinance sector info locally and prevent slow repeated API queries.
- [ ] Implement command line flag overrides in `main.py` for user qualitative inputs (moat, management, dilution risk).

