# Runs the ITMS backend locally on Windows, no Docker.
#
# Prereqs (one-time):
#   winget install --id taizod1024.redis-windows-fork -e   # redis-server
#   python -m venv .venv
#   .venv\Scripts\python.exe -m pip install -e packages/common -e packages/domain `
#       -e services/api-service -e services/sim-service
#
# Usage: powershell -File scripts\dev-local.ps1
# Stop everything with: Get-Job | Stop-Job; Get-Job | Remove-Job

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$redisExe = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter "redis-server.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $redisExe) {
    throw "redis-server.exe not found. Install it first: winget install --id taizod1024.redis-windows-fork -e"
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "venv not found at .venv -- run the setup steps in this script's header comment first."
}

$sumoExe = Join-Path $root ".venv\Scripts\sumo.exe"
New-Item -ItemType Directory -Force -Path (Join-Path $root ".run") | Out-Null

Write-Host "Starting redis-server..."
Start-Process -FilePath $redisExe -ArgumentList "--port 6379" -WindowStyle Hidden
Start-Sleep -Seconds 2

Write-Host "Starting api-service on :8000..."
Start-Process -FilePath $venvPy -ArgumentList "-m","uvicorn","api_service.main:app","--host","0.0.0.0","--port","8000" `
    -WorkingDirectory $root -RedirectStandardOutput "$root\.run\api-service.log" -RedirectStandardError "$root\.run\api-service.err.log" -WindowStyle Hidden

Write-Host "Starting sim-service (SUMO)..."
$env:SUMO_BINARY = $sumoExe
$env:SIM_REALTIME_FACTOR = "4"
Start-Process -FilePath $venvPy -ArgumentList "-m","sim_service.main" `
    -WorkingDirectory $root -RedirectStandardOutput "$root\.run\sim-service.log" -RedirectStandardError "$root\.run\sim-service.err.log" -WindowStyle Hidden

Write-Host ""
Write-Host "=========================================================="
Write-Host " api-service: http://localhost:8000/health"
Write-Host " ws stream:   ws://localhost:8000/v1/stream"
Write-Host " live map:    open web/live.html in a browser"
Write-Host " logs:        .run/*.log"
Write-Host " To stop: Get-Process redis-server,sumo,python | Stop-Process -Force"
Write-Host "=========================================================="
