@echo off
echo Starting StockCalls Dashboard...
echo.
echo Dashboard: http://localhost:8000
echo Press Ctrl+C to stop
echo.
cd /d "%~dp0dashboard"
python -m http.server 8000
