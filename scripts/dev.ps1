<#
.SYNOPSIS
    一键启动开发环境（后端 FastAPI + 前端 Vite）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -ApiPort 18000 -NoReload

说明：
    后端以后台作业运行，前端在前台运行；按 Ctrl+C 退出时会自动回收后端。
    浏览器访问 http://localhost:5173，/api 由 Vite 代理到后端。
#>

param(
    [int]$ApiPort = 17800,
    [switch]$NoReload
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'

$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
if ($python -eq 'python') {
    Write-Warning '未找到 backend\.venv，将使用系统 Python。建议先执行：cd backend; python -m venv .venv; .venv\Scripts\python.exe -m pip install -e ".[dev]"'
}

$apiOrigin = "http://127.0.0.1:$ApiPort"
$backendArgs = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$ApiPort")
if (-not $NoReload) { $backendArgs += '--reload' }

Write-Host "启动后端 $apiOrigin ..." -ForegroundColor Cyan
$backendJob = Start-Job -ScriptBlock {
    param($py, $dir, $arguments)
    Set-Location -LiteralPath $dir
    & $py @arguments
} -ArgumentList $python, $backendDir, $backendArgs

try {
    Start-Sleep -Seconds 2
    Write-Host "启动前端 http://localhost:5173 ..." -ForegroundColor Cyan
    Write-Host '浏览器打开 http://localhost:5173；按 Ctrl+C 结束。' -ForegroundColor DarkGray

    Set-Location -LiteralPath $frontendDir
    $env:PHARMRELATE_API_ORIGIN = $apiOrigin
    npm run dev
}
finally {
    Write-Host '正在停止后端 ...' -ForegroundColor DarkGray
    Stop-Job -Job $backendJob -ErrorAction SilentlyContinue
    Remove-Job -Job $backendJob -Force -ErrorAction SilentlyContinue
    Write-Host '已停止。' -ForegroundColor DarkGray
}
