<#
.SYNOPSIS
    手机端分发站（web/ + Pages + APK 直链）的验收脚本。

.DESCRIPTION
    分两段：
      本地静态段（默认跑，离线可用）：页面结构、固定资产名直链、消隐逻辑、
                                     apk.json / manifest.json 合法性与三者一致。
      线上段（默认跑，需要联网）：Pages 站点返回 200 且带安装入口；
                                     APK 直链返回 Content-Disposition: attachment
                                     与 application/vnd.android.package-archive
                                     —— 这两条就是「不跳 GitHub 页面、直接落盘」的证据。

    scripts\check.ps1 里跑的是 -SkipOnline 版本（回归不该依赖网络），
    发版或验收时再完整跑一次。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\verify-install-entry.ps1
    powershell -ExecutionPolicy Bypass -File scripts\verify-install-entry.ps1 -SkipOnline

.NOTES
    退出码 0 = 全部通过；1 = 有未通过项。
#>

param(
    [switch]$SkipOnline,
    [string]$SiteUrl = 'https://sd3247930.github.io/pharmrelate-suite/'
)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$webDir = Join-Path $root 'web'
$indexPath = Join-Path $webDir 'index.html'
$appJsPath = Join-Path $webDir 'app.js'
$apkJsonPath = Join-Path $webDir 'apk.json'
$pwaJsonPath = Join-Path $webDir 'manifest.json'

$fixedAssetName = 'PharmRelate-Multi-Capture.apk'
$fixedUrl = "https://github.com/sd3247930/pharmrelate-suite/releases/latest/download/$fixedAssetName"
$logoAssets = @(
    'app-logo-round-192-v2.png',
    'app-logo-round-512-v2.png',
    'app-logo-round-maskable-512-v2.png',
    'og-cover-v2.png'
)

$failures = [System.Collections.Generic.List[string]]::new()
$checks = 0

function Report($ok, $label, $extra) {
    $script:checks++
    $mark = if ($ok) { ' OK ' } else { 'FAIL' }
    $suffix = if ($extra) { "  $extra" } else { '' }
    Write-Host "[$mark] $label$suffix"
    if (-not $ok) { $script:failures.Add($label) }
}

function Read-Text($path) {
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    return Get-Content -LiteralPath $path -Raw -Encoding UTF8
}

# ======================= 本地静态段 =======================
Write-Host '---- 本地静态检查 ----' -ForegroundColor Cyan

$index = Read-Text $indexPath
$appJs = Read-Text $appJsPath

Report ($null -ne $index) 'web/index.html 存在'
if ($index) {
    Report ($index -match '📲') '顶栏有「📲 安装」入口'
    Report ($index -match 'id="installBtn"') '入口有 id="installBtn"（脚本可挂事件）'
    Report ($index -match '📥 下载应用') '有「📥 下载应用」面板标题'
    Report ($index -match 'role="dialog"') '面板声明 role="dialog"'
    Report ($index -match 'aria-expanded') '入口声明 aria-expanded（状态可读）'
    Report ($index -match [regex]::Escape($fixedUrl)) '主按钮 href 是固定资产名直链'
    Report ($index -match ('download="' + [regex]::Escape($fixedAssetName) + '"')) '主按钮带固定资产名的 download 属性'
    Report ($index -match '为什么要装') '面板含「为什么要装 APK」说明'
    Report ($index -match '在浏览器打开') '面板含微信 / QQ 内「在浏览器打开」引导'
    Report ($index -match '导出') '面板含「先导出再迁移」说明'
    Report ($index -match 'og:title' -and $index -match 'og:image') '含 og:title / og:image 分享预览'
    Report ($index -match 'manifest.json') '引用 PWA manifest'
    Report ($index -match 'class="app-bar-logo"') '顶栏显示圆形品牌 Logo'
    Report ($index -match 'icons/app-logo-round-192-v2.png') '页面引用版本化圆形 Logo'
    # 主按钮不依赖 JS：href 必须写在 HTML 里，而不是只靠脚本注入
    Report ($index -match '<a[^>]+id="apkDownload"[^>]+href=') '主按钮的 href 写在 HTML 里（不依赖 JS）'
}

Report ($null -ne $appJs) 'web/app.js 存在'
if ($appJs) {
    Report ($appJs -match 'display-mode:\s*standalone') '含独立窗口（standalone）判定'
    Report ($appJs -match "protocol === 'file:'") '含 file:// 判定'
    Report ($appJs -match 'no-install-entry') '含隐藏安装入口的类名切换'
    Report ($appJs -match 'install=1' -or $appJs -match 'install=') '含 ?install=1 深链支持'
    Report ($appJs -match 'apk\.json') '会读取 apk.json 动态信息'
}

# 面板样式：手机点击区不小于 48px
$styles = Read-Text (Join-Path $webDir 'styles.css')
Report ($null -ne $styles) 'web/styles.css 存在'
if ($styles) {
    Report ($styles -match 'min-height:\s*(48|5[0-9]|6[0-9])px') '点击区不小于 48px'
    Report ($styles -match 'font-size:\s*16px') '正文 16px 起'
}

foreach ($icon in $logoAssets) {
    Report (Test-Path -LiteralPath (Join-Path $webDir ('icons\' + $icon))) "图标存在：icons/$icon"
}

$apkJson = $null
if (Test-Path -LiteralPath $apkJsonPath) {
    try { $apkJson = Get-Content -LiteralPath $apkJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $apkJson = $null }
}
Report ($null -ne $apkJson) 'web/apk.json 是合法 JSON'
if ($apkJson) {
    Report ($apkJson.downloadUrl -eq $fixedUrl) 'apk.json 的 downloadUrl 与页面一致（固定资产名）'
    Report ($apkJson.name -eq $fixedAssetName) 'apk.json 的 name 是固定资产名'
    if ($apkJson.released) {
        Report ([bool]$apkJson.sha256) 'apk.json 已填 SHA256'
        Report ([int]$apkJson.sizeBytes -gt 0) 'apk.json 已填文件大小'
        Report ([bool]$apkJson.versionName) 'apk.json 已填版本号'
        Report ($index -match [regex]::Escape([string]$apkJson.sha256) -eq $false) 'SHA256 不写死在 HTML（由 apk.json 提供）'
    } else {
        Write-Host '[跳过] apk.json 标记为未发布：跳过版本字段检查（发版后应变为已发布）' -ForegroundColor Yellow
    }
}

$pwaJson = $null
if (Test-Path -LiteralPath $pwaJsonPath) {
    try { $pwaJson = Get-Content -LiteralPath $pwaJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $pwaJson = $null }
}
Report ($null -ne $pwaJson) 'web/manifest.json 是合法 JSON'
if ($pwaJson) {
    Report ($pwaJson.display -eq 'standalone') 'PWA 以 standalone 方式启动（装到主屏后无地址栏）'
    Report (@($pwaJson.icons).Count -ge 3) 'PWA 至少声明 3 个图标（含 maskable）'
    $pwaIconSources = @($pwaJson.icons | ForEach-Object { $_.src })
    foreach ($icon in $logoAssets[0..2]) {
        Report ($pwaIconSources -contains "icons/$icon") "PWA manifest 引用：icons/$icon"
    }
}

$workflowPath = Join-Path $root '.github\workflows\pages.yml'
$workflow = Read-Text $workflowPath
Report ($null -ne $workflow) '.github/workflows/pages.yml 存在'
if ($workflow) {
    Report ($workflow -match 'upload-pages-artifact') '工作流使用 upload-pages-artifact'
    Report ($workflow -match 'deploy-pages') '工作流使用 deploy-pages'
    Report ($workflow -match 'path:\s*web') '发布的目录是 web/'
}

# ======================= 线上段 =======================
if ($SkipOnline) {
    Write-Host "`n[跳过] -SkipOnline：不检查 Pages 与 APK 直链" -ForegroundColor Yellow
} else {
    Write-Host "`n---- 线上检查（需要联网）----" -ForegroundColor Cyan
    $ProgressPreference = 'SilentlyContinue'

    try {
        $site = Invoke-WebRequest -UseBasicParsing -Uri $SiteUrl -TimeoutSec 40
        Report ($site.StatusCode -eq 200) "Pages 返回 200：$SiteUrl" "(状态码 $($site.StatusCode))"
        Report ($site.Content -match 'id="installBtn"') 'Pages 页面里能找到安装入口'
        Report ($site.Content -match [regex]::Escape($fixedAssetName)) 'Pages 页面里能找到固定资产名'
    } catch {
        Report $false "Pages 返回 200：$SiteUrl" $_.Exception.Message
        Write-Host '        提示：Pages 首次部署要等 Actions 跑完（约 1~2 分钟）；刚推送完就查会 404。' -ForegroundColor Yellow
    }

    # 站点资源逐个确认：PWA manifest / 面板数据 / 图标 少一个，都会让「装到主屏」或分享预览静默失效
    $siteRoot = $SiteUrl.TrimEnd('/')
    $onlineAssets = @('manifest.json', 'apk.json') + @($logoAssets | ForEach-Object { "icons/$_" })
    foreach ($asset in $onlineAssets) {
        try {
            $res = Invoke-WebRequest -UseBasicParsing -Method Head -Uri "$siteRoot/$asset" -TimeoutSec 30
            Report ($res.StatusCode -eq 200) "Pages 资源可访问：/$asset"
        } catch {
            Report $false "Pages 资源可访问：/$asset" $_.Exception.Message
        }
    }

    try {
        $head = Invoke-WebRequest -UseBasicParsing -Method Head -Uri $fixedUrl -MaximumRedirection 6 -TimeoutSec 60
        $disposition = [string]$head.Headers['Content-Disposition']
        $contentType = [string]$head.Headers['Content-Type']
        Report ($disposition -match '^\s*attachment') 'APK 直链返回 Content-Disposition: attachment（浏览器直接落盘）' $disposition
        Report ($contentType -match 'android\.package-archive') 'APK 直链的 Content-Type 正确' $contentType
        $finalUri = [string]$head.BaseResponse.RequestMessage.RequestUri
        Report ($finalUri -notmatch 'github\.com/.*/releases/?$') '直链没有停在 Release 网页上' $finalUri
        if ($apkJson -and $apkJson.released -and $apkJson.sizeBytes) {
            $len = [long]$head.Headers['Content-Length']
            Report ($len -eq [long]$apkJson.sizeBytes) '线上 APK 字节数与 apk.json 一致' "(线上 $len / 记录 $($apkJson.sizeBytes))"
        }
    } catch {
        Report $false "APK 直链可下载：$fixedUrl" $_.Exception.Message
        Write-Host '        提示：Release 尚未发布时这里会 404 —— 先跑 scripts\publish-apk.ps1。' -ForegroundColor Yellow
    }
}

# ======================= 汇总 =======================
Write-Host ''
if ($failures.Count -gt 0) {
    Write-Host "安装入口验收未通过（$($failures.Count)/$checks 项）：" -ForegroundColor Red
    foreach ($item in $failures) { Write-Host "  - $item" -ForegroundColor Red }
    exit 1
}
Write-Host "安装入口验收通过（$checks 项）。" -ForegroundColor Green
exit 0
