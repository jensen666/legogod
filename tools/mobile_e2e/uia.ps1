# LEGOGOD 真机 E2E：UiAutomation 驱动调用封装（结果从 logcat 读取）。
# 证据目录优先读环境变量 LEGO_E2E_DIR；未设置时在仓库 artifacts/e2e-mobile/ 下按本轮时间戳新建，
# 避免不同轮次共用旧证据。ADB 优先读环境变量 LEGO_ADB，再从 PATH 查找；缺失时给出可操作错误。

# 仓库根：本脚本位于 <repo>/tools/mobile_e2e/，向上两级即仓库根。
$script:LegogodRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$script:AdbPath = $null

# 惰性解析 adb 路径：优先显式环境变量，其次 PATH，最后给出可操作错误。
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

# 证据根目录：显式环境变量优先，否则按轮次时间戳在仓库内新建目录（不共用旧证据）。
$global:E2eEvidence = if ($env:LEGO_E2E_DIR) {
    $env:LEGO_E2E_DIR
} else {
    Join-Path $script:LegogodRoot ("artifacts\e2e-mobile\" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-mobile-e2e')
}

function Run-UiAction {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [string]$Text = '',
        [string]$Name = '',
        [int]$TimeoutMs = 0,
        [int]$Index = -1,
        [int]$X = -1,
        [int]$Y = -1,
        [string]$Direction = ''
    )
    $adb = Get-LegoAdb
    $driver = 'com.legogod.uiauto/.DriverInstrumentation'
    $argv = @('shell', 'am', 'instrument', '-w', '-e', 'action', $Action)
    if ($Text -ne '') {
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Text))
        $argv += @('-e', 'text', $b64, '-e', 'b64', '1')
    }
    if ($Name -ne '') { $argv += @('-e', 'name', $Name) }
    if ($TimeoutMs -gt 0) { $argv += @('-e', 'timeoutMs', "$TimeoutMs") }
    if ($Index -ge 0) { $argv += @('-e', 'index', "$Index") }
    if ($X -ge 0) { $argv += @('-e', 'x', "$X") }
    if ($Y -ge 0) { $argv += @('-e', 'y', "$Y") }
    if ($Direction -ne '') { $argv += @('-e', 'direction', $Direction) }
    $argv += $driver
    & $adb logcat -c 2>$null | Out-Null
    & $adb @argv 2>&1 | Out-Null
    $chunks = @()
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        Start-Sleep -Milliseconds 700
        $lines = & $adb logcat -d -s LegoUIAuto:I 2>&1
        $chunks = @()
        foreach ($line in $lines) {
            $idx = $line.IndexOf('RESULT|')
            if ($idx -ge 0) { $chunks += $line.Substring($idx + 7) }
        }
        if ($chunks.Count -gt 0) { break }
    }
    return ($chunks -join '')
}

function Run-UiDump {
    $raw = Run-UiAction -Action dump
    return ($raw -replace '^OK\|dump\|', '')
}

function Run-UiDumpAll {
    $raw = Run-UiAction -Action dumpall
    return ($raw -replace '^OK\|dumpall\|', '')
}

function Find-DumpNode {
    param([string]$Dump, [string]$Text, [switch]$Exact)
    foreach ($part in ($Dump -split 'NODE\|')) {
        if (-not $part) { continue }
        $textMatch = [regex]::Match($part, '\|text=([^|]*)\|')
        $descMatch = [regex]::Match($part, '\|desc=([^|]*)\|')
        $t = if ($textMatch.Success) { $textMatch.Groups[1].Value } else { '' }
        $d = if ($descMatch.Success) { $descMatch.Groups[1].Value } else { '' }
        if ($Exact) {
            if ($t -eq $Text -or $d -eq $Text) { return "NODE|$part" }
        } else {
            if (($t -and $t.Contains($Text)) -or ($d -and $d.Contains($Text))) { return "NODE|$part" }
        }
    }
    return $null
}

function Get-Screenshot {
    param([string]$Path)
    $adb = Get-LegoAdb
    $dir = Split-Path -Parent $Path
    if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    & $adb shell screencap -p /sdcard/legogod_shot.png 2>&1 | Out-Null
    & $adb pull /sdcard/legogod_shot.png $Path 2>&1 | Out-Null
    Write-Host "[e2e] 截图 $Path"
}

function Invoke-LegoApi {
    param([string]$Path, [string]$Token = '')
    $headers = @{}
    if ($Token) { $headers['Authorization'] = "Bearer $Token" }
    $base = if ($env:LEGO_API_BASE) { $env:LEGO_API_BASE.TrimEnd('/') } else { 'http://127.0.0.1:8600' }
    return Invoke-RestMethod -Uri "$base$Path" -Headers $headers -Method Get -TimeoutSec 20
}

function Save-Evidence {
    param([string]$CaseId, [string]$Name, [string]$Content)
    $dir = "$global:E2eEvidence\android\$CaseId"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    [System.IO.File]::WriteAllText("$dir\$Name", $Content, (New-Object System.Text.UTF8Encoding($false)))
}

function Get-E2eTokenPath {
    return "$global:E2eEvidence\token.txt"
}

function Get-E2eToken {
    $path = Get-E2eTokenPath
    if (-not (Test-Path $path)) { return '' }
    return (Get-Content $path -Raw).Trim()
}

# ---------- 输入与等待辅助 ----------

# 向第 Index 个可编辑节点设置文本（Flutter 语义暴露为 EditText，走 ACTION_SET_TEXT）。
function Set-UiText {
    param([int]$Index = 0, [Parameter(Mandatory = $true)][string]$Text)
    return Run-UiAction -Action setTextIndex -Index $Index -Text $Text
}

# 等待某个文本出现在当前界面（超时返回 NB 前缀）。
function Wait-UiText {
    param([Parameter(Mandatory = $true)][string]$Text, [int]$TimeoutMs = 8000)
    return Run-UiAction -Action waitText -Text $Text -TimeoutMs $TimeoutMs
}

# 拍摄当前屏幕并保存到证据目录。
function Save-Screenshot {
    param([Parameter(Mandatory = $true)][string]$CaseId, [Parameter(Mandatory = $true)][string]$Name)
    $dir = "$global:E2eEvidence\android\$CaseId"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Get-Screenshot -Path "$dir\$Name.png"
}

# 系统返回键。
function Press-Back {
    return Run-UiAction -Action back
}

# 上下滚动（direction: up/down）。
function Scroll-Ui {
    param([string]$Direction = 'down')
    return Run-UiAction -Action scroll -Direction $Direction
}

# 下拉刷新/上滑手势（比例坐标，0~1）。
function Swipe-Ui {
    param([int]$X1, [int]$Y1, [int]$X2, [int]$Y2, [int]$DurationMs = 300)
    return Run-UiAction -Action swipe -X $X1 -Y $Y1 -Text "$X2,$Y2" -TimeoutMs $DurationMs
}

# 按无障碍节点文本获取其中心坐标与原始节点串。
function Get-UiNode {
    param([Parameter(Mandatory = $true)][string]$Text, [switch]$Exact)
    $dump = Run-UiDump
    return Find-DumpNode -Dump $dump -Text $Text -Exact:$Exact
}

function Launch-LegoApp {
    $adb = Get-LegoAdb
    & $adb shell am start -n com.legogod.app/.MainActivity 2>&1 | Out-Null
    Start-Sleep -Seconds 3
}

function Click-Text {
    param([string]$Text, [int]$Index = -1)
    if ($Index -ge 0) {
        return Run-UiAction -Action clickText -Text $Text -Index $Index
    }
    return Run-UiAction -Action clickText -Text $Text
}

function Click-UiText {
    param([string]$Text, [int]$Retries = 4)
    for ($i = 0; $i -lt $Retries; $i++) {
        $dump = Run-UiDump
        $node = Find-DumpNode -Dump $dump -Text $Text
        if ($node) {
            $m = [regex]::Match($node, 'bounds=(\d+),(\d+),(\d+),(\d+)')
            if ($m.Success) {
                $x = [int](([int]$m.Groups[1].Value + [int]$m.Groups[3].Value) / 2)
                $y = [int](([int]$m.Groups[2].Value + [int]$m.Groups[4].Value) / 2)
                $r = Run-UiAction -Action clickPointNode -X $x -Y $y
                if ($r -like 'OK*') { return $r }
            }
        }
        Start-Sleep -Milliseconds 800
    }
    return "NB|not_found|$Text"
}
