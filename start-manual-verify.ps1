param(
    [int]$TaskCount = 1,
    [int]$ManualTimeoutSeconds = 600,
    [switch]$SkipPoolProxy,
    [switch]$NoSystemProxy
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 > $null

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectRoot "config.json"
$pythonPath = Join-Path $projectRoot ".venv\\Scripts\\python.exe"
$poolApi = "http://127.0.0.1:5010/get/?type=https"

if (!(Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual env python not found: $pythonPath"
}

$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json

if (-not $config.manual_captcha) {
    $config | Add-Member -NotePropertyName manual_captcha -NotePropertyValue ([PSCustomObject]@{})
}
$config.manual_captcha.enabled = $true
$config.manual_captcha.timeout_seconds = $ManualTimeoutSeconds
$config.manual_captcha.poll_interval_seconds = 2

$config.concurrent_flows = 1
$config.max_tasks = $TaskCount

if (-not $config.proxy_pool) {
    $config | Add-Member -NotePropertyName proxy_pool -NotePropertyValue ([PSCustomObject]@{})
}
$config.proxy_pool.enable_auto_rotate = $true
if (-not $config.playwright) {
    $config | Add-Member -NotePropertyName playwright -NotePropertyValue ([PSCustomObject]@{})
}
$config.playwright.no_system_proxy = [bool]$NoSystemProxy

if (-not $SkipPoolProxy) {
    try {
        $proxyResp = Invoke-RestMethod -Uri $poolApi -TimeoutSec 15
        if ($proxyResp.proxy) {
            $config.proxy = "http://$($proxyResp.proxy)"
            Write-Host "Loaded proxy: $($config.proxy)"
        } else {
            Write-Warning "Proxy pool returned empty proxy. Keep existing proxy in config.json."
        }
    } catch {
        Write-Warning "Failed to fetch proxy from pool. Keep existing proxy. Error: $($_.Exception.Message)"
    }
}

$configJson = $config | ConvertTo-Json -Depth 10
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

Write-Host "Manual CAPTCHA mode enabled."
Write-Host "TaskCount=$TaskCount, ManualTimeoutSeconds=$ManualTimeoutSeconds"
Write-Host "NoSystemProxy=$([bool]$NoSystemProxy)"
Write-Host "Starting main.py ..."

& $pythonPath "-u" "main.py"
