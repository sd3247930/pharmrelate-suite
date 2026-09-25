<#
.SYNOPSIS
    以局域网模式启动后端，供 Android 真机连接。

.DESCRIPTION
    默认的启动方式监听 127.0.0.1，手机连不上 —— 这是 Android 接入时最常见的卡点。
    本脚本改为监听 0.0.0.0 并打印本机局域网 IP，手机端填这个地址即可。

    不修改任何一期代码：监听地址本身是 uvicorn 的启动参数。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\serve-lan.ps1
    powershell -ExecutionPolicy Bypass -File scripts\serve-lan.ps1 -Port 17800
#>

param(
    [int]$Port = 17800
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }

# 找出本机局域网 IPv4 地址（排除回环与虚拟网卡常见的 169.254 网段）
$addresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $_.IPAddress -ne '127.0.0.1' -and
        $_.IPAddress -notlike '169.254.*' -and
        $_.PrefixOrigin -ne 'WellKnown'
    } |
    Select-Object -ExpandProperty IPAddress -Unique

Write-Host ''
Write-Host '================ 籽关通 局域网服务 ================' -ForegroundColor Cyan
Write-Host "监听地址 : 0.0.0.0:$Port（局域网内所有网卡可访问）"
if ($addresses) {
    Write-Host '手机端在「连接设置」里填以下地址之一：' -ForegroundColor Yellow
    foreach ($ip in $addresses) {
        Write-Host "    http://$ip`:$Port" -ForegroundColor Green
    }
    Write-Host '  （选与手机同一网段的那个）' -ForegroundColor DarkGray
} else {
    Write-Host '未找到局域网 IPv4 地址，请确认已连接车间局域网。' -ForegroundColor Red
}
Write-Host ''
Write-Host '注意：明文传输。选项 B 下务必只监听局域网网卡并隔离网段。' -ForegroundColor Yellow
Write-Host '按 Ctrl+C 停止。' -ForegroundColor DarkGray
Write-Host '=================================================' -ForegroundColor Cyan
Write-Host ''

Push-Location -LiteralPath $backendDir
try {
    & $python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
}
finally {
    Pop-Location
}
