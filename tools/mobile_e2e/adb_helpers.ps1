# LEGOGOD 手机 APP 真机 E2E 辅助函数（ADB 驱动真实 UI）。
# 仅用于验收取证与自动化操作，不属于 APP 产品代码。
# 证据目录优先读环境变量 LEGO_E2E_DIR；未设置时在仓库 artifacts/e2e-mobile/ 下按本轮时间戳新建。
# ADB 优先读环境变量 LEGO_ADB，再从 PATH 查找；缺失时给出可操作错误。
$ErrorActionPreference = 'Stop'

# 仓库根：本脚本位于 <repo>/tools/mobile_e2e/，向上两级即仓库根。
$script:LegogodRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:AdbPath = $null

function Get-LegoAdb {
    if ($script:AdbPath) { return $script:AdbPath }
    if ($env:LEGO_ADB) {
        if (-not (Test-Path $env:LEGO_ADB)) {
            throw "环境变量 LEGO_ADB 指向的文件不存在：$env:LEGO_ADB"
        }
        $script:AdbPath = $env:LEGO_ADB
        return $script:AdbPath
    }
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) {
        $script:AdbPath = $cmd.Source
        return $script:AdbPath
    }
    throw "未找到 adb：请把 Android platform-tools 加入 PATH，或设置环境变量 LEGO_ADB 指向 adb(.exe)。"
}

$script:EvidenceRoot = if ($env:LEGO_E2E_DIR) {
    $env:LEGO_E2E_DIR
} else {
    Join-Path $script:LegogodRoot ("artifacts\e2e-mobile\" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-mobile-e2e')
}

function Adb {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & (Get-LegoAdb) @Args
}

function Invoke-Adb {
    param([string]$Command)
    $out = & (Get-LegoAdb) @($Command -split ' ')
    return $out
}

function Set-CaseDir {
    param([string]$CaseId)
    $dir = Join-Path $script:EvidenceRoot "android\$CaseId"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return $dir
}

function Save-Screenshot {
    param([string]$Path)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $bytes = & (Get-LegoAdb) exec-out screencap -p
    [System.IO.File]::WriteAllBytes($Path, $bytes)
    Write-Host "[e2e] 截图: $Path"
}

function Dump-UiXml {
    param([string]$Path)
    Adb shell uiautomator dump /sdcard/legogod_ui.xml 2>&1 | Out-Null
    $xmlText = (Adb exec-out cat /sdcard/legogod_ui.xml) -join "`n"
    if ($Path) {
        $dir = Split-Path -Parent $Path
        if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        [System.IO.File]::WriteAllText($Path, $xmlText, [System.Text.Encoding]::UTF8)
    }
    try { return [xml]$xmlText } catch { return $null }
}

function Get-NodeBounds {
    param($Node)
    if (-not $Node -or -not $Node.bounds) { return $null }
    $m = [regex]::Match($Node.bounds, '\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
    if (-not $m.Success) { return $null }
    $x1 = [int]$m.Groups[1].Value; $y1 = [int]$m.Groups[2].Value
    $x2 = [int]$m.Groups[3].Value; $y2 = [int]$m.Groups[4].Value
    return [PSCustomObject]@{
        X = [int](($x1 + $x2) / 2)
        Y = [int](($y1 + $y2) / 2)
        X1 = $x1; Y1 = $y1; X2 = $x2; Y2 = $y2
    }
}

function Find-UiNode {
    param($Xml, [string]$Text, [switch]$Exact)
    if (-not $Xml) { return $null }
    foreach ($node in $Xml.SelectNodes('//node')) {
        $t = [string]$node.text
        $d = [string]$node.'content-desc'
        if ($Exact) {
            if ($t -eq $Text -or $d -eq $Text) { return $node }
        } else {
            if (($t -and $t.Contains($Text)) -or ($d -and $d.Contains($Text))) { return $node }
        }
    }
    return $null
}

function Wait-UiText {
    param([string]$Text, [int]$TimeoutSeconds = 20, [switch]$Exact)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $xml = Dump-UiXml
        $node = Find-UiNode -Xml $xml -Text $Text -Exact:$Exact
        if ($node) { return $node }
        Start-Sleep -Milliseconds 600
    }
    return $null
}

function Tap-UiText {
    param([string]$Text, [int]$TimeoutSeconds = 20, [switch]$Exact)
    $node = Wait-UiText -Text $Text -TimeoutSeconds $TimeoutSeconds -Exact:$Exact
    if (-not $node) { throw "未找到可点击文本：$Text" }
    $b = Get-NodeBounds -Node $node
    if (-not $b) { throw "节点没有 bounds：$Text" }
    Adb shell input tap $b.X $b.Y | Out-Null
    Write-Host "[e2e] 点击「$Text」($($b.X),$($b.Y))"
    Start-Sleep -Milliseconds 500
}

function Tap-UiPoint {
    param([int]$X, [int]$Y)
    Adb shell input tap $X $Y | Out-Null
    Start-Sleep -Milliseconds 400
}

function Input-AdbUnicodeText {
    param([string]$Text)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $b64 = [Convert]::ToBase64String($bytes)
    Adb shell am broadcast -a com.legogod.adbime.INPUT --es msg $b64 | Out-Null
    Start-Sleep -Milliseconds 700
}

function Delete-InputText {
    param([int]$Count = 200)
    Adb shell am broadcast -a com.legogod.adbime.DELETE --ei count $Count | Out-Null
    Start-Sleep -Milliseconds 500
}

function Back {
    Adb shell input keyevent 4 | Out-Null
    Start-Sleep -Milliseconds 600
}

function Swipe-Up {
    param([int]$Times = 1)
    for ($i = 0; $i -lt $Times; $i++) {
        Adb shell input swipe 540 1500 540 700 300 | Out-Null
        Start-Sleep -Milliseconds 400
    }
}

function Swipe-Down {
    param([int]$Times = 1)
    for ($i = 0; $i -lt $Times; $i++) {
        Adb shell input swipe 540 700 540 1500 300 | Out-Null
        Start-Sleep -Milliseconds 400
    }
}

function Save-JsonFile {
    param([string]$Path, $Object)
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $json = $Object | ConvertTo-Json -Depth 12
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Invoke-Api {
    param([string]$Path, [string]$Token = '')
    $headers = @{}
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    $base = if ($env:LEGO_API_BASE) { $env:LEGO_API_BASE.TrimEnd('/') } else { 'http://127.0.0.1:8600' }
    return Invoke-RestMethod -Uri "$base$Path" -Headers $headers -Method Get -TimeoutSec 20
}

Write-Host '[e2e] 辅助函数已加载（Adb/Dump-UiXml/Tap-UiText/Save-Screenshot/Invoke-Api ...）'
