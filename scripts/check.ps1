<#
.SYNOPSIS
    一键跑完全部检查：后端单测、端到端冒烟、基准比对、前端单测与构建、桌面壳冒烟。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -SkipDesktop
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Full

说明：
    默认 11 项；-Full 追加"打包态 UI 冒烟"（需要先 cd desktop; npm run dist）。
    打包态那条会启动真实安装产物并断言界面渲染、后端可用 —— 白屏与漏打包
    这两类缺陷只有它会发现，所以发版前应当跑 -Full。

退出码 0 表示全部通过。
#>

param(
    [switch]$SkipFrontendBuild,
    [switch]$SkipE2E,
    [switch]$SkipDesktop,
    [switch]$Full
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$frontendDir = Join-Path $root 'frontend'
$desktopDir = Join-Path $root 'desktop'

$venvPython = Join-Path $backendDir '.venv\Scripts\python.exe'
$python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }

$results = [System.Collections.Generic.List[object]]::new()

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Command,
        [string[]]$CommandArguments = @()
    )

    Write-Host ''
    Write-Host "==== $Name ====" -ForegroundColor Cyan
    Push-Location -LiteralPath $WorkingDirectory
    try {
        $exe = $Command[0]
        $baseArgs = @()
        if ($Command.Length -gt 1) { $baseArgs = $Command[1..($Command.Length - 1)] }
        & $exe @baseArgs @CommandArguments
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    }
    catch {
        Write-Host $_ -ForegroundColor Red
        $code = 1
    }
    finally {
        Pop-Location
    }

    $ok = $code -eq 0
    $results.Add([pscustomobject]@{ Name = $Name; Ok = $ok; Code = $code })
    if ($ok) {
        Write-Host "[ 通过 ] $Name" -ForegroundColor Green
    }
    else {
        Write-Host "[ 失败 ] $Name（退出码 $code）" -ForegroundColor Red
    }
}

Invoke-Step -Name '后端单元测试（阶段 0 基准 + API 契约）' -WorkingDirectory $backendDir `
    -Command @($python, '-m', 'unittest', 'discover', '-s', 'tests', '-t', '.')

Invoke-Step -Name '后端端到端冒烟（真实进程与端口）' -WorkingDirectory $backendDir `
    -Command @($python, 'tools\smoke_test.py')

Invoke-Step -Name '黄金基准字节级比对' -WorkingDirectory $backendDir `
    -Command @($python, 'tools\compare_golden.py')

Invoke-Step -Name 'P0 验收清单自动核对' -WorkingDirectory $backendDir `
    -Command @($python, 'tools\acceptance.py')

Invoke-Step -Name '20 台并发压测（模拟客户端）' -WorkingDirectory $backendDir `
    -Command @($python, 'tools\loadtest.py', '--quick')

Invoke-Step -Name 'WebSocket 通道本地自测（ws + wss）' -WorkingDirectory $backendDir `
    -Command @($python, 'tools\ws_selftest.py')

Invoke-Step -Name 'Android（uni-app）静态检查' -WorkingDirectory $root `
    -Command @('powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\check-uniapp.ps1')

Invoke-Step -Name '前端单元测试（路由 + 条码规则）' -WorkingDirectory $frontendDir `
    -Command @('npm', 'test')

if (-not $SkipFrontendBuild) {
    Invoke-Step -Name '前端类型检查与构建' -WorkingDirectory $frontendDir `
        -Command @('npm', 'run', 'build')
}

if (-not $SkipE2E) {
    Invoke-Step -Name '真实浏览器 UI 冒烟（Playwright）' -WorkingDirectory $frontendDir `
        -Command @('npm', 'run', 'e2e')
}

if (-not $SkipDesktop) {
    Invoke-Step -Name '桌面壳冒烟（Electron 拉起 Python 服务）' -WorkingDirectory $desktopDir `
        -Command @('npm', 'run', 'smoke')
}

# 打包态 UI 冒烟：唯一会真正打开窗口的检查，白屏与漏打包只有它拦得住。
# 需要先 npm run dist，故放在 -Full 里，不进默认 11 项。
if ($Full) {
    Invoke-Step -Name '打包态 UI 冒烟（真实安装产物）' -WorkingDirectory $desktopDir `
        -Command @('npm', 'run', 'smoke:packed')
}

Write-Host ''
Write-Host '=================== 汇总 ===================' -ForegroundColor Cyan
foreach ($item in $results) {
    $mark = if ($item.Ok) { '通过' } else { '失败' }
    $color = if ($item.Ok) { 'Green' } else { 'Red' }
    Write-Host ("  [{0}] {1}" -f $mark, $item.Name) -ForegroundColor $color
}

$failed = @($results | Where-Object { -not $_.Ok })
Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host "$($failed.Count) 项未通过。" -ForegroundColor Red
    exit 1
}
Write-Host '全部检查通过。' -ForegroundColor Green
exit 0
