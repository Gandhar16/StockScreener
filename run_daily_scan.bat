@echo off
REM StockCalls Daily Scanner
REM Runs every morning via Windows Task Scheduler
REM Fundamentals: cached 30 days per ticker (only re-screened when stale)
REM Technicals + Telegram alerts: runs fresh every day

cd /d D:\StockCalls

REM Log file: one per day, kept for 30 days
set LOGFILE=reports\scan_log_%date:~-4,4%%date:~-7,2%%date:~-10,2%.txt

echo ============================= >> "%LOGFILE%"
echo StockCalls Daily Scan >> "%LOGFILE%"
echo %date% %time% >> "%LOGFILE%"
echo ============================= >> "%LOGFILE%"

python scan_and_alert.py --min-conviction CONFIRMED >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Finished: %time% >> "%LOGFILE%"

REM Clean up log files older than 30 days
forfiles /p "reports" /m "scan_log_*.txt" /d -30 /c "cmd /c del @path" 2>nul

exit /b 0
