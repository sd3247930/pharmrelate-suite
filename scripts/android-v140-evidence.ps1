<#
.SYNOPSIS
    Android v1.4.0 真机验证取证：截图 / 相机占用检查 / 应用日志。

.DESCRIPTION
    配合 private\md执行方案\Android-v1.4.0-真机验证操作脚本.md 使用。
    真机行为无法在 PC 上自动断言，这个脚本只负责把**证据**（截图与日志）落盘，
    断言由人对着操作脚本里的「预期结果」逐条确认 —— 不在这里假装通过。

    为什么用 screencap + pull 而不是 exec-out：
      PowerShell 捕获原生命令的 stdout 会按文本解码，PNG 会被解坏（本项目 v1.3.1 踩过）。
      先截到手机的 /sdcard 再 pull，二进制全程不经过 PowerShell 的字符串管道。

.PARAMETER Label
    证据文件名（不含扩展名），例如 01-扫箱号条形码-成功。

.PARAMETER OutDir
    证据输出目录。默认 private\测试输出\Android-v1.4.0-真机验证-<今天>。

.PARAMETER Log
    同时抓一份应用日志与当前焦点窗口名（logcat -d，最近 600 行）。

.PARAMETER Camera
    同时检查相机是否真的被本应用占用（针对「取景界面不是独立 Activity」那个坑）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\android-v140-evidence.ps1 `
        -Label 01-扫箱号条形码-成功 -Camera -Log
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Label,

    [string]$OutDir,

    [switch]$Log,

    [switch]$Camera
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Find-Adb {
    $onPath = Get-Command adb -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk\platform-tools\adb.exe'),
        (Join-Path $env:LOCALAPPDATA 'Android\Sdk\adb.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw '找不到 adb。请安装 Android platform-tools，或把 adb 加到 PATH。'
}

$adb = Find-Adb

$deviceLines = (& $adb devices) | Where-Object { $_ -match "\tdevice" }
if (-not $deviceLines) {
    throw '没有处于 device 状态的安卓设备。请先连上手机（USB 调试或无线调试）。'
}

if (-not $OutDir) {
    $stamp = Get-Date -Format 'yyyyMMdd'
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $OutDir = Join-Path $repoRoot "private\测试输出\Android-v1.4.0-真机验证-$stamp"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# 截到手机再拉回来：绕开 PowerShell 对二进制 stdout 的文本解码
$remoteShot = '/sdcard/pr-v140-shot.png'
$localShot = Join-Path $OutDir "$Label.png"

& $adb shell screencap -p $remoteShot | Out-Null
& $adb pull $remoteShot $localShot | Out-Null
& $adb shell rm -f $remoteShot | Out-Null

if (-not (Test-Path -LiteralPath $localShot)) {
    throw "截图失败：$localShot 没有生成。"
}
Write-Host ("[截图] {0}  ({1:N0} 字节)" -f $localShot, (Get-Item -LiteralPath $localShot).Length)

if ($Camera) {
    Write-Host '[相机] 检查本应用是否占用 camera 设备…'
    $cameraOwner = & $adb shell dumpsys media.camera 2>$null | Select-String 'io.dcloud.HBuilder'
    if ($cameraOwner) {
        Write-Host '  ✓ 相机被本应用占用 —— 取景界面确实起来了'
        $cameraOwner | Select-Object -First 3 | ForEach-Object { Write-Host ('    ' + $_.ToString().Trim()) }
    } else {
        Write-Host '  ✗ 没看到 io.dcloud.HBuilder 占用相机 —— 取景界面可能没起来，或已经被 BACK 关掉'
    }
}

if ($Log) {
    $logFile = Join-Path $OutDir "$Label.log.txt"
    & $adb logcat -d -t 600 > $logFile
    & $adb shell dumpsys window 2>$null | Select-String 'mCurrentFocus' |
        Out-File -FilePath $logFile -Append -Encoding utf8
    Write-Host "[日志] $logFile"
}

Write-Host ''
Write-Host '提示：取景界面只要还留在屏幕上，后续截图拍到的全是相机画面。'
Write-Host '      拿完证据请按一次 BACK 关掉它，再截业务界面。'
