# 本機 ETL 排程腳本 — 三家院線全部執行（含新光）
# 由 Windows 工作排程器每日 10:30 / 22:30 CST 執行
# 執行結果 append 到 logs/etl_local.log

$ProjectRoot = "$PSScriptRoot"
$LogFile     = "$ProjectRoot\logs\etl_local.log"
$PythonExe   = (Get-Command python -ErrorAction SilentlyContinue).Source

if (-not $PythonExe) {
    Add-Content $LogFile "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: python not found"
    exit 1
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Add-Content $LogFile ""
Add-Content $LogFile "========== $timestamp =========="

Set-Location $ProjectRoot
& $PythonExe main.py --load 2>&1 | ForEach-Object {
    Add-Content $LogFile $_
}

$exitCode = $LASTEXITCODE
Add-Content $LogFile "Exit code: $exitCode"
