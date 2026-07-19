# 本機 ETL 排程腳本 — 三家院線全部執行（含新光）
# 由 Windows 工作排程器每日 10:30 / 22:30 CST 執行
# 執行結果 append 到 logs/etl_local.log
#
# 新光（skcinemas）若透過 VPN 連線會被目標網站擋下，
# 執行前先停用本機 VPN client 服務，確保新光用真實 IP 抓取。
# 執行後不會自動重新連線；若不需要這個行為可自行註解掉下面這段。

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

try {
    Stop-Service -Name "SEVPNCLIENT" -Force -ErrorAction Stop
    Add-Content $LogFile "[$timestamp] SoftEther VPN client 已停用"
} catch {
    Add-Content $LogFile "[$timestamp] WARNING: 停用 SoftEther VPN client 失敗: $_"
}

Set-Location $ProjectRoot
& $PythonExe main.py --load 2>&1 | ForEach-Object {
    Add-Content $LogFile $_
}

$exitCode = $LASTEXITCODE
Add-Content $LogFile "Exit code: $exitCode"
