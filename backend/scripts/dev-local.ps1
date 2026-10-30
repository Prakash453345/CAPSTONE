# Runs the ITMS backend locally on Windows, no Docker.
#
# Prereqs (one-time, from backend/):
#   winget install --id taizod1024.redis-windows-fork -e   # redis-server
#   python -m venv .venv
#   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
#   .venv\Scripts\python.exe -m pip install -e libs/domain -e libs/common -e libs/geo `
#       -e services/simulation-service -e services/api-gateway -e services/vision-service
#
# Usage (from anywhere):
#   powershell -File backend\scripts\dev-local.ps1                 # sim in live mode
#   powershell -File backend\scripts\dev-local.ps1 -SimMode sumo   # the A-CA-MP demo run instead
#   powershell -File backend\scripts\dev-local.ps1 -WithVision     # also the video clip worker
# Then the console: cd frontend; npm run dev  ->  http://localhost:5173
#
# Live mode is the default because the console's operator actions (create an
# anomaly, dispatch, green corridor, confirming a video finding) only run there.

param(
    [ValidateSet("live", "sumo")] [string] $SimMode = "live",
    [switch] $WithVision
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot   # backend/
Set-Location $root

$redisExe = Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter "redis-server.exe" -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $redisExe) {
    throw "redis-server.exe not found. Install it first: winget install --id taizod1024.redis-windows-fork -e"
}

$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    throw "venv not found at backend\.venv -- run the setup steps in this script's header comment first."
}

$run = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $run | Out-Null

function Start-BackendProcess($name, [string[]] $arguments) {
    Start-Process -FilePath $venvPy -ArgumentList $arguments -WorkingDirectory $root `
        -RedirectStandardOutput "$run\$name.log" -RedirectStandardError "$run\$name.err.log" -WindowStyle Hidden
}

Write-Host "Starting redis-server..."
Start-Process -FilePath $redisExe -ArgumentList "--port 6379" -WorkingDirectory $run -WindowStyle Hidden
Start-Sleep -Seconds 2

Write-Host "Starting api-gateway on :8000..."
# 127.0.0.1, not 0.0.0.0: commands and video uploads need no API key, so the
# gateway must not be reachable from the rest of the network (campus Wi-Fi, a
# demo room). The console reaches it through Vite's proxy on this machine.
Start-BackendProcess "api-gateway" @("-m", "uvicorn", "api_gateway.main:app", "--host", "127.0.0.1", "--port", "8000")

Write-Host "Starting simulation-service (SUMO, $SimMode mode)..."
$env:SUMO_BINARY = Join-Path $root ".venv\Scripts\sumo.exe"
$env:SIM_REALTIME_FACTOR = "4"
$env:SIM_MODE = $SimMode
Start-BackendProcess "simulation-service" @("-m", "sim_service.main")

if ($WithVision) {
    Write-Host "Starting vision-service clip worker..."
    Start-BackendProcess "vision-clips" @("-m", "vision_service.clips")
}

Write-Host ""
Write-Host "=========================================================="
Write-Host " api-gateway: http://localhost:8000/health  (API docs: /docs)"
Write-Host " ws stream:   ws://localhost:8000/v1/stream"
Write-Host " console:     cd frontend; npm run dev  ->  http://localhost:5173"
Write-Host " logs:        backend\.run\*.log  (the API key is in api-gateway.err.log)"
Write-Host " To stop: Get-Process redis-server,sumo,python | Stop-Process -Force"
Write-Host "=========================================================="
