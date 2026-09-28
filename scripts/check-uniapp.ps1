<#
.SYNOPSIS
    Android（uni-app）工程的静态检查。

.DESCRIPTION
    这里做的是**能在 PC 上自动验的部分**：JS 语法、JSON 结构、目录完整性。
    真机行为（扫码、相机、组播、证书）必须由真机验证，不在这里假装通过。

    也可以单独跑：powershell -ExecutionPolicy Bypass -File scripts\check-uniapp.ps1
#>

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$androidDir = Join-Path $root 'android'
$failures = @()

function Report($ok, $label, $extra) {
    $mark = if ($ok) { ' OK ' } else { 'FAIL' }
    $suffix = if ($extra) { "  $extra" } else { '' }
    Write-Host "[$mark] $label$suffix"
    if (-not $ok) { $script:failures += $label }
}

if (-not (Test-Path -LiteralPath $androidDir)) {
    Write-Host '[FAIL] android/ 目录不存在'
    exit 1
}

# ---- 必需文件 ----
$required = @(
    'manifest.json', 'pages.json', 'main.js', 'App.vue', 'index.html',
    'pages\scan\scan.vue', 'pages\status\status.vue', 'pages\settings\settings.vue',
    'services\api.js', 'services\ws.js', 'services\store.js'
)
foreach ($rel in $required) {
    $path = Join-Path $androidDir $rel
    Report (Test-Path -LiteralPath $path) "必需文件存在：$rel"
}

# ---- JS 语法（用 Node 做解析，uni 全局不执行） ----
$jsFiles = Get-ChildItem -LiteralPath $androidDir -Recurse -File -Filter '*.js' |
    Where-Object { $_.FullName -notmatch '\\unpackage\\|\\node_modules\\' }
foreach ($file in $jsFiles) {
    & node --check $file.FullName 2>$null
    Report ($LASTEXITCODE -eq 0) "JS 语法：$($file.Name)"
}

# ---- JSON 结构（HBuilderX 允许注释，先剥掉再解析） ----
foreach ($name in @('manifest.json', 'pages.json')) {
    $path = Join-Path $androidDir $name
    if (-not (Test-Path -LiteralPath $path)) { continue }
    $raw = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    $stripped = [regex]::Replace($raw, '/\*[\s\S]*?\*/', '')
    try {
        $null = $stripped | ConvertFrom-Json
        Report $true "JSON 结构：$name"
    }
    catch {
        Report $false "JSON 结构：$name" $_.Exception.Message
    }
}

# ---- 权限与关键配置 ----
$manifest = Get-Content -LiteralPath (Join-Path $androidDir 'manifest.json') -Raw -Encoding UTF8
foreach ($permission in @('INTERNET', 'CAMERA', 'ACCESS_WIFI_STATE', 'CHANGE_WIFI_MULTICAST_STATE')) {
    Report ($manifest -match $permission) "Android 权限已声明：$permission"
}
Report ($manifest -match '"Barcode"') '已启用 Barcode 模块（uni.scanCode 需要）'
Report ($manifest -match '"packagename"\s*:\s*"com\.pharmrelate\.multi\.capture"') '生产包名固定为 com.pharmrelate.multi.capture'

# ---- Android 启动图标 ----
$iconSpecs = @{
    'static\icons\app-icon-round-ldpi-48.png' = 48
    'static\icons\app-icon-round-mdpi-48.png' = 48
    'static\icons\app-icon-round-hdpi-72.png' = 72
    'static\icons\app-icon-round-xhdpi-96.png' = 96
    'static\icons\app-icon-round-xxhdpi-144.png' = 144
    'static\icons\app-icon-round-xxxhdpi-192.png' = 192
}
Add-Type -AssemblyName System.Drawing
foreach ($entry in $iconSpecs.GetEnumerator()) {
    $path = Join-Path $androidDir $entry.Key
    $exists = Test-Path -LiteralPath $path
    Report $exists "Android 图标存在：$($entry.Key)"
    if (-not $exists) { continue }
    $image = [System.Drawing.Image]::FromFile($path)
    try {
        $sizeOk = $image.Width -eq $entry.Value -and $image.Height -eq $entry.Value
        Report $sizeOk "Android 图标尺寸：$($entry.Key)" "$($image.Width)x$($image.Height)"
    }
    finally {
        $image.Dispose()
    }
    $manifestPath = $entry.Key.Replace('\', '/')
    Report ($manifest -match [regex]::Escape($manifestPath)) "manifest 已引用：$manifestPath"
}

$pages = Get-Content -LiteralPath (Join-Path $androidDir 'pages.json') -Raw -Encoding UTF8
foreach ($page in @('pages/scan/scan', 'pages/status/status', 'pages/settings/settings')) {
    Report ($pages -match [regex]::Escape($page)) "路由已注册：$page"
}

# ---- 不修改一期代码：android/ 与一期目录互不引用 ----
$leak = Get-ChildItem -LiteralPath $androidDir -Recurse -File |
    Where-Object { $_.FullName -notmatch '\\unpackage\\' } |
    Select-String -Pattern 'from\s+[''"].*\.\./\.\./\.\./(backend|frontend)' -List
Report (-not $leak) 'android/ 未反向引用一期代码'

Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "uni-app 静态检查未通过（$($failures.Count) 项）：" -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}
Write-Host 'uni-app 静态检查通过（真机行为需真机验证）' -ForegroundColor Green
exit 0
