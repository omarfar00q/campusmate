# CampusMate One-Command Runner (PowerShell)
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Starting CampusMate (MCP Server + Agent API + Frontend)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentDir = Split-Path -Parent $ScriptDir
$env:PYTHONPATH = "$ParentDir;$ScriptDir;$($env:PYTHONPATH)"
$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "[!] Virtual environment not found at $PythonExe. Please initialize .venv first." -ForegroundColor Red
    exit 1
}

# 1. Seed database
Write-Host "[1/4] Ensuring database seed data is initialized..." -ForegroundColor Yellow
& $PythonExe -m campusmate.data.seed_data

# 2. Launch MCP Server
Write-Host "[2/4] Starting Standalone MCP Server on port 8000..." -ForegroundColor Yellow
$McpProcess = Start-Process -FilePath $PythonExe -ArgumentList "-m", "campusmate.server.app.main", "--port", "8000" -PassThru -NoNewWindow

Start-Sleep -Seconds 1

# 3. Launch Agent SSE API
Write-Host "[3/4] Starting Agent SSE Service on port 8001..." -ForegroundColor Yellow
$AgentProcess = Start-Process -FilePath $PythonExe -ArgumentList "-m", "campusmate.agent.api", "--port", "8001" -PassThru -NoNewWindow

Start-Sleep -Seconds 1

# 4. Launch Vite Frontend
Write-Host "[4/4] Starting Vite Frontend on port 5173..." -ForegroundColor Yellow
$FrontendDir = Join-Path $ScriptDir "frontend"
$FrontendProcess = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory $FrontendDir -PassThru -NoNewWindow

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " All CampusMate services are active!" -ForegroundColor Green
Write-Host " - Frontend UI:   http://localhost:5173" -ForegroundColor Green
Write-Host " - MCP Server:    http://127.0.0.1:8000/mcp (Health: /health)" -ForegroundColor Green
Write-Host " - Agent SSE API: http://127.0.0.1:8001/api/chat (Health: /api/health)" -ForegroundColor Green
Write-Host ""
Write-Host " [OK] Running in built-in offline mode -- NO API KEYS REQUIRED!" -ForegroundColor Cyan
Write-Host " Open http://localhost:5173 and click any prompt chip." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop all services."

try {
    while ($true) { Start-Sleep -Seconds 2 }
} finally {
    Write-Host "Shutting down CampusMate background processes..." -ForegroundColor Yellow
    Stop-Process -Id $McpProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $AgentProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $FrontendProcess.Id -Force -ErrorAction SilentlyContinue
    Set-Location $ScriptDir
}
