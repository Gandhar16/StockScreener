"""FastAPI server for StockCalls dashboard integration."""

import json

# Import stock_scanner modules
import sys
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent))

from stock_scanner.config import ScannerConfig, load_config_from_file
from stock_scanner.engine.backtest import Backtester
from stock_scanner.scanner import StockScanner

app = FastAPI(
    title="StockCalls API",
    description="API for StockCalls dashboard",
    version="1.0.0"
)

# CORS for dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
REPORTS_DIR = Path("reports")
DASHBOARD_DIR = Path("dashboard/dist")

# Models
class ScanRequest(BaseModel):
    tickers: list[str] | None = None
    mode: str = "market_scan"

class BacktestRequest(BaseModel):
    phases: int = 3
    start_year: int = 2021
    tickers_per_phase: int = 20
    rebalance_days: int = 30

class SettingsRequest(BaseModel):
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    alpha_vantage_key: str | None = None
    polygon_key: str | None = None
    finnhub_key: str | None = None
    scan_schedule: str = "0 6 * * *"
    backtest_default_phases: int = 3
    data_cache_ttl: int = 24
    log_level: str = "INFO"

class TelegramTestRequest(BaseModel):
    bot_token: str
    chat_id: str

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# Equity Calls
@app.get("/api/equity_calls")
async def get_equity_calls():
    """Get latest equity calls for dashboard."""
    try:
        # Try to load from reports
        calls_file = REPORTS_DIR / "equity_calls.json"
        if calls_file.exists():
            with open(calls_file) as f:
                data = json.load(f)
                return data

        # Fallback to dashboard file
        dash_file = Path("dashboard/equity_calls.json")
        if dash_file.exists():
            with open(dash_file) as f:
                return json.load(f)

        return {"calls": [], "timestamp": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/equity_calls/{ticker}")
async def get_equity_call(ticker: str):
    """Get detailed equity call for a specific ticker."""
    data = await get_equity_calls()
    for call in data.get("calls", []):
        if call.get("ticker", "").upper() == ticker.upper():
            return call
    raise HTTPException(status_code=404, detail=f"Call for {ticker} not found")

# Dashboard Data
@app.get("/api/dashboard")
async def get_dashboard_data():
    """Get aggregated dashboard data."""
    calls_data = await get_equity_calls()
    calls = calls_data.get("calls", [])

    return {
        "equity_calls": calls,
        "long_term_calls": [c for c in calls if c.get("type") == "long_term"],
        "swing_calls": [c for c in calls if c.get("type") == "swing"],
        "sell_calls": [c for c in calls if c.get("type") == "sell"],
        "metadata": {
            "last_updated": datetime.now().isoformat(),
            "universe_size": len(calls),
            "scan_duration_seconds": 0,
        }
    }

# Stock Detail
@app.get("/api/stock/{ticker}")
async def get_stock_detail(ticker: str):
    """Get detailed stock data for dashboard."""
    # This would normally fetch fresh data
    # For now, return from calls if available
    calls_data = await get_equity_calls()
    for call in calls_data.get("calls", []):
        if call.get("ticker", "").upper() == ticker.upper():
            return call
    raise HTTPException(status_code=404, detail=f"Data for {ticker} not found")

# Scanner
@app.post("/api/scan")
async def run_scan(request: ScanRequest):
    """Run a stock scan."""
    try:
        config_path = "config/scanner_config.yaml"
        if Path(config_path).exists():
            config = load_config_from_file(config_path)
        else:
            config = ScannerConfig()

        if request.tickers:
            config.tickers = request.tickers
        config.mode = request.mode

        scanner = StockScanner(config)
        results_df = scanner.run()

        if results_df.empty:
            return {"results": [], "count": 0}

        # Convert to records
        results = results_df.to_dict(orient="records")
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Pipeline
@app.post("/api/pipeline")
async def run_pipeline(background_tasks: BackgroundTasks):
    """Run full pipeline."""
    try:
        # Import pipeline module
        import pipeline
        # Run in background
        background_tasks.add_task(pipeline.main)
        return {"status": "started", "message": "Pipeline started in background"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Backtest
@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest):
    """Run backtest simulation."""
    try:
        backtester = Backtester()
        results = backtester.run(
            phases=request.phases,
            start_year=request.start_year,
            tickers_per_phase=request.tickers_per_phase,
            rebalance_days=request.rebalance_days,
        )
        return {"results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Settings
@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    settings_file = Path("config/settings.json")
    if settings_file.exists():
        with open(settings_file) as f:
            return json.load(f)
    return {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "alpha_vantage_key": "",
        "polygon_key": "",
        "finnhub_key": "",
        "scan_schedule": "0 6 * * *",
        "backtest_default_phases": 3,
        "data_cache_ttl": 24,
        "log_level": "INFO",
    }

@app.post("/api/settings")
async def save_settings(settings: SettingsRequest):
    """Save settings."""
    settings_file = Path("config/settings.json")
    settings_file.parent.mkdir(exist_ok=True)
    with open(settings_file, "w") as f:
        json.dump(settings.dict(), f, indent=2)
    return {"status": "saved"}

@app.post("/api/test/telegram")
async def test_telegram(request: TelegramTestRequest):
    """Send test Telegram message."""
    import requests

    url = f"https://api.telegram.org/bot{request.bot_token}/sendMessage"
    payload = {
        "chat_id": request.chat_id,
        "text": "🧪 StockCalls test message - configuration successful!",
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            return {"success": True, "message": "Test message sent"}
        else:
            return {"success": False, "error": response.text}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Generate Calls
@app.post("/api/generate_calls")
async def generate_calls(background_tasks: BackgroundTasks):
    """Generate equity calls."""
    try:
        import generate_calls
        background_tasks.add_task(generate_calls.main)
        return {"status": "started", "message": "Call generation started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Serve dashboard static files
if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DASHBOARD_DIR / "assets"), name="assets")

@app.get("/{full_path:path}")
async def serve_dashboard(full_path: str):
    """Serve dashboard for all other routes (SPA fallback)."""
    index_file = DASHBOARD_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Dashboard not built. Run 'npm run build' in dashboard directory."}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
