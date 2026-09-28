<#
.SYNOPSIS
    把 HBuilderX 云打包产出的 APK 发成 GitHub Release，并同步网页面板上的版本信息。

.DESCRIPTION
    一条命令完成「发版」这件事：
      1. 找到 HBuilderX 最新的 Android 打包产物（或用 -ApkPath 指定）；
      2. 校验包名 / 版本号 / 签名与私有证书一致；
      3. 按固定资产名 PharmRelate-Multi-Capture.apk 暂存，并生成 .sha256；
      4. 创建（或覆盖）GitHub Release，上传两个资产；
      5. 回写 web/apk.json（版本 / 大小 / SHA256 / 日期），提交并推送。

    固定资产名是这套机制的关键：网页主按钮指向
    https://github.com/sd3247930/PharmRelate-Multi/releases/latest/download/PharmRelate-Multi-Capture.apk
    releases/latest 永远指向最新版，所以升版只需要换资产，网页一行都不用改。

.EXAMPLE
    # 常规发版（自动取最新打包产物，tag = v<manifest.versionName>）
    powershell -ExecutionPolicy Bypass -File scripts\publish-apk.ps1

    # 指定产物 / 不推送（先干跑一遍看输出）
    powershell -ExecutionPolicy Bypass -File scripts\publish-apk.ps1 -ApkPath "D:\...\__UNI__DA0B962__20260928090958.apk" -SkipPush

.NOTES
    - keystore 与口令只在 private\签名证书\ 本地保留，不入库；
    - 首次发布前请确认 HBuilderX 云打包用的是同一份 keystore，否则老用户必须卸载重装。
#>

param(
    [string]$ApkPath,
    [string]$Tag,
    [string]$StagingDirectory,
    [switch]$SkipPush
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path -Parent $PSScriptRoot
$androidDir = Join-Path $root 'android'
$manifestPath = Join-Path $androidDir 'manifest.json'
$apkJsonPath = Join-Path $root 'web\apk.json'

$fixedAssetName = 'PharmRelate-Multi-Capture.apk'
$expectedPackage = 'com.pharmrelate.multi.capture'
$expectedLabel = '籽关通'
$downloadUrl = "https://github.com/sd3247930/PharmRelate-Multi/releases/latest/download/$fixedAssetName"
$hbuilderApkDir = '<ANDROID_PROJECT_DIR>\unpackage\release\apk'

if (-not $StagingDirectory) {
    $StagingDirectory = Join-Path $root 'private\构建产物'
}

function Write-Step($text) { Write-Host "`n==== $text ====" -ForegroundColor Cyan }
function Fail($text) { Write-Host "[失败] $text" -ForegroundColor Red; exit 1 }

# ---------- 1. 读 manifest 拿版本号 ----------
Write-Step '读取 Android 版本号'
if (-not (Test-Path -LiteralPath $manifestPath)) { Fail "找不到 $manifestPath" }
$manifestRaw = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8
$manifestJson = [regex]::Replace($manifestRaw, '/\*[\s\S]*?\*/', '') | ConvertFrom-Json
$versionName = $manifestJson.versionName
$versionCode = $manifestJson.versionCode
if (-not $versionName) { Fail 'android/manifest.json 里没有 versionName' }
if (-not $Tag) { $Tag = "v$versionName" }
Write-Host "版本：$versionName（versionCode $versionCode）  发布 tag：$Tag"

# ---------- 2. 找 APK ----------
Write-Step '定位 APK 产物'
if (-not $ApkPath) {
    if (-not (Test-Path -LiteralPath $hbuilderApkDir)) {
        Fail "HBuilderX 产物目录不存在：$hbuilderApkDir（请先在 HBuilderX 里云打包，或用 -ApkPath 指定）"
    }
    $latest = Get-ChildItem -LiteralPath $hbuilderApkDir -Filter '*.apk' -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { Fail "该目录下没有 .apk：$hbuilderApkDir" }
    $ApkPath = $latest.FullName
}
if (-not (Test-Path -LiteralPath $ApkPath)) { Fail "APK 不存在：$ApkPath" }
$apkItem = Get-Item -LiteralPath $ApkPath
Write-Host "APK：$($apkItem.FullName)"
Write-Host ("大小：{0:N0} 字节（{1:N1} MB）" -f $apkItem.Length, ($apkItem.Length / 1MB))

# ---------- 3. 校验包名 / 应用名 / 签名 ----------
Write-Step '校验 APK（包名 / 应用名 / 签名）'
$buildTools = Get-ChildItem '<ANDROID_SDK>\build-tools' -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending | Select-Object -First 1
if ($buildTools) {
    $aapt2 = Join-Path $buildTools.FullName 'aapt2.exe'
    if (Test-Path -LiteralPath $aapt2) {
        $badging = & $aapt2 dump badging $ApkPath 2>&1 | Out-String
        if ($badging -notmatch [regex]::Escape("name='$expectedPackage'")) {
            Fail "包名不是 $expectedPackage（aapt2 输出：$(($badging -split "`n")[0])）"
        }
        if ($badging -notmatch [regex]::Escape("versionName='$versionName'")) {
            Fail "APK 的 versionName 与 manifest.json（$versionName）不一致"
        }
        if ($badging -notmatch [regex]::Escape($expectedLabel)) {
            Fail "应用名里找不到「$expectedLabel」"
        }
        Write-Host "OK 包名 $expectedPackage · 应用名 $expectedLabel · versionName $versionName"
    }
    $apksigner = Join-Path $buildTools.FullName 'apksigner.bat'
    if (Test-Path -LiteralPath $apksigner) {
        $signInfo = & $apksigner verify --print-certs $ApkPath 2>&1 | Out-String
        $sha = ([regex]::Match($signInfo, 'SHA-256 digest:\s*([0-9a-fA-F]+)')).Groups[1].Value
        if ($sha) {
            Write-Host "签名 SHA-256：$sha"
            $fingerprintFile = Join-Path $root 'private\签名证书\指纹.txt'
            if (Test-Path -LiteralPath $fingerprintFile) {
                $recorded = (Get-Content -LiteralPath $fingerprintFile -Raw).Trim().ToLower().Replace(':', '')
                if ($recorded -and $recorded -ne $sha.ToLower()) {
                    Fail "签名指纹与 private\签名证书\指纹.txt 不一致（换证书会让老用户无法覆盖安装）"
                }
                Write-Host 'OK 签名指纹与已登记指纹一致'
            } else {
                Set-Content -LiteralPath $fingerprintFile -Value $sha -Encoding UTF8 -NoNewline
                Write-Host "已登记签名指纹到 private\签名证书\指纹.txt"
            }
        } else {
            Write-Host '[提示] 未能从 apksigner 输出里取到 SHA-256，跳过指纹比对' -ForegroundColor Yellow
        }
    }
} else {
    Write-Host '[提示] 未找到 Android build-tools，跳过包名与签名校验' -ForegroundColor Yellow
}

# ---------- 4. 暂存为固定资产名 + 生成 sha256 ----------
Write-Step '暂存固定资产名与校验文件'
$stagingDir = Join-Path $StagingDirectory $Tag
New-Item -ItemType Directory -Force -Path $stagingDir | Out-Null
$stagedApk = Join-Path $stagingDir $fixedAssetName
Copy-Item -LiteralPath $ApkPath -Destination $stagedApk -Force
$hash = (Get-FileHash -LiteralPath $stagedApk -Algorithm SHA256).Hash.ToLower()
$shaFile = "$stagedApk.sha256"
Set-Content -LiteralPath $shaFile -Value "$hash  $fixedAssetName" -Encoding ASCII -NoNewline
Write-Host "暂存：$stagedApk"
Write-Host "SHA256：$hash"

# ---------- 5. 创建 / 覆盖 Release ----------
Write-Step "发布 GitHub Release：$Tag"
$gh = (Get-Command gh -ErrorAction SilentlyContinue).Source
if (-not $gh) { Fail '找不到 gh CLI（https://cli.github.com/），或改成在网页上手动上传资产' }

& gh release view $Tag --repo sd3247930/PharmRelate-Multi *> $null
$releaseExists = ($LASTEXITCODE -eq 0)

if ($releaseExists) {
    Write-Host "Release $Tag 已存在，改为覆盖上传资产（--clobber）"
    & gh release upload $Tag $stagedApk $shaFile --repo sd3247930/PharmRelate-Multi --clobber
} else {
    $notes = @"
手机采集端（uni-app）Android 安装包。

- 包名：``$expectedPackage``
- 版本：``$versionName``（versionCode $versionCode）
- 签名：自有证书，固定签名（换证书需先卸载旧版再装）
- SHA256：``$hash``

固定下载直链（网页「📲 安装 → 📥 下载应用」用的就是它）：
$downloadUrl
"@
    & gh release create $Tag $stagedApk $shaFile --repo sd3247930/PharmRelate-Multi `
        --title "手机采集端 $versionName" --notes $notes
}
if ($LASTEXITCODE -ne 0) { Fail "gh release 执行失败（退出码 $LASTEXITCODE）" }

# ---------- 6. 回写 web/apk.json ----------
Write-Step '回写 web/apk.json'
$meta = [ordered]@{
    '_comment'    = '由 scripts/publish-apk.ps1 在发布 Release 时自动回写，不要手改；页面读不到它时会退回 HTML 里的静态文案。'
    'name'        = $fixedAssetName
    'released'    = $true
    'tag'         = $Tag
    'versionName' = $versionName
    'versionCode' = [int]$versionCode
    'sizeBytes'   = $apkItem.Length
    'sha256'      = $hash
    'releasedAt'  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd')
    'packageName' = $expectedPackage
    'downloadUrl' = $downloadUrl
}
$json = ($meta | ConvertTo-Json -Depth 4) + "`n"
[System.IO.File]::WriteAllText($apkJsonPath, $json, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "已更新：$apkJsonPath"

# ---------- 7. 提交并推送 ----------
Write-Step '提交 web/apk.json'
Push-Location -LiteralPath $root
try {
    & git add -- 'web/apk.json'
    & git commit -m "release: 手机采集端 $versionName —— 直链与网页面板信息同步"
    if ($LASTEXITCODE -ne 0) { Write-Host '[提示] 没有需要提交的改动（apk.json 内容未变）' -ForegroundColor Yellow }
    if (-not $SkipPush) {
        & git push origin HEAD
        if ($LASTEXITCODE -ne 0) { Fail 'git push 失败' }
    } else {
        Write-Host '[跳过] -SkipPush：未推送（Pages 上仍是旧版本信息）' -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}

Write-Host "`n发布完成。把这条链接发到手机上验收：" -ForegroundColor Green
Write-Host "  https://sd3247930.github.io/PharmRelate-Multi/?install=1" -ForegroundColor Green
Write-Host "  直链：$downloadUrl" -ForegroundColor Green
