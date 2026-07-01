# setup_scheduler.ps1
# Creates a Windows Task Scheduler task that runs the daily scan every morning.
# Run once as Administrator:  powershell -ExecutionPolicy Bypass -File setup_scheduler.ps1

$TaskName    = "StockCalls Daily Scan"
$ScriptPath  = "D:\StockCalls\run_daily_scan.bat"
$RunTime     = "07:30"          # 7:30 AM — change to suit your market open preference
$Description = "StockCalls full S&P 500 scanner — technicals on fundamentally strong stocks, Telegram alerts"

# Remove old task if it exists
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed existing task '$TaskName'"
}

# Action: run the batch file
$Action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`""

# Trigger: daily at $RunTime, Monday–Friday only
$Trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At $RunTime

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -WakeToRun $false

# Principal: run as current user
$Principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Trigger `
    -Settings   $Settings `
    -Principal  $Principal `
    -Description $Description `
    -Force | Out-Null

Write-Host ""
Write-Host "Task Scheduler setup complete!" -ForegroundColor Green
Write-Host "  Task:    $TaskName"
Write-Host "  Runs:    Monday–Friday at $RunTime"
Write-Host "  Script:  $ScriptPath"
Write-Host "  Logs:    D:\StockCalls\reports\scan_log_YYYYMMDD.txt"
Write-Host ""
Write-Host "To change run time, edit the `$RunTime variable at the top of this file and re-run."
Write-Host "To run immediately: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "To remove:          Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
