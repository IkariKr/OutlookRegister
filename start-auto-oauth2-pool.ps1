param(
    [int]$TaskCount = 6,
    [int]$Concurrency = 3,
    [ValidateSet("patchright", "playwright")]
    [string]$Browser = "patchright",
    [ValidateSet("direct", "system", "pool_system")]
    [string]$ProxyMode = "pool_system",
    [string]$SystemProxy = "127.0.0.1:7890",
    [ValidateSet("https", "socks5")]
    [string]$ProxyType = "https",
    [string]$FallbackProxyTypes = "socks5,http",
    [string]$PoolApiBase = "http://127.0.0.1:5010",
    [int]$MaxProxyRetries = 8,
    [int]$FetchProxyRetries = 6,
    [int]$FetchProxyRetryIntervalSeconds = 2,
    [switch]$DisableProbe
)

$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001 > $null

function Convert-ToProxyUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProxyRaw,
        [string]$ProxyTypeRaw = "http"
    )

    $proxyText = $ProxyRaw.Trim()
    if ([string]::IsNullOrWhiteSpace($proxyText)) {
        throw "Proxy pool returned an empty proxy."
    }

    if ($proxyText -match "^[a-zA-Z0-9]+://") {
        return $proxyText
    }

    $typeText = ""
    if ($null -ne $ProxyTypeRaw) {
        $typeText = $ProxyTypeRaw.Trim().ToLowerInvariant()
    }

    if ($typeText -eq "socks5") {
        return "socks5://$proxyText"
    }

    return "http://$proxyText"
}

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $projectRoot "config.json"
$pythonPath = Join-Path $projectRoot ".venv\\Scripts\\python.exe"
$poolApiBaseNorm = $PoolApiBase.TrimEnd("/")
$poolGetUrl = "$poolApiBaseNorm/get/?type=$ProxyType"
$poolDeleteUrl = "$poolApiBaseNorm/delete/"

if (!(Test-Path -LiteralPath $pythonPath)) {
    throw "Python in .venv is missing: $pythonPath"
}

$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json

if (-not $config.oauth2) {
    $config | Add-Member -NotePropertyName oauth2 -NotePropertyValue ([PSCustomObject]@{})
}
if (-not $config.oauth2.client_id -or [string]::IsNullOrWhiteSpace([string]$config.oauth2.client_id)) {
    throw "oauth2.client_id is empty. Please fill it in config.json first."
}
if (-not $config.proxy_pool) {
    $config | Add-Member -NotePropertyName proxy_pool -NotePropertyValue ([PSCustomObject]@{})
}
if (-not $config.manual_captcha) {
    $config | Add-Member -NotePropertyName manual_captcha -NotePropertyValue ([PSCustomObject]@{})
}
if (-not $config.playwright) {
    $config | Add-Member -NotePropertyName playwright -NotePropertyValue ([PSCustomObject]@{})
}

$proxyValue = ""
$proxySource = "direct"
$selectedGetUrl = $poolGetUrl

if ($ProxyMode -eq "direct") {
    $proxyValue = ""
    $proxySource = "direct"
}
elseif ($ProxyMode -eq "system") {
    $proxyValue = Convert-ToProxyUrl -ProxyRaw $SystemProxy -ProxyTypeRaw "http"
    $proxySource = "system"
}
else {
    $typeCandidates = @()
    $typeCandidates += $ProxyType
    if (-not [string]::IsNullOrWhiteSpace($FallbackProxyTypes)) {
        foreach ($item in $FallbackProxyTypes.Split(",")) {
            $t = $item.Trim().ToLowerInvariant()
            if ([string]::IsNullOrWhiteSpace($t)) { continue }
            if (-not ($typeCandidates -contains $t)) {
                $typeCandidates += $t
            }
        }
    }

    $proxyResp = $null
    $lastError = ""
    $lastPayloadJson = ""
    $maxFetchRounds = [Math]::Max(1, $FetchProxyRetries)

    for ($round = 1; $round -le $maxFetchRounds; $round++) {
        foreach ($candidateType in $typeCandidates) {
            $candidateGetUrl = "$poolApiBaseNorm/get/?type=$candidateType"
            Write-Host "Proxy fetch round $round/$maxFetchRounds, type=$candidateType"
            try {
                $candidate = Invoke-RestMethod -Uri $candidateGetUrl -TimeoutSec 15
                if ($null -ne $candidate) {
                    $lastPayloadJson = ($candidate | ConvertTo-Json -Depth 10 -Compress)
                }
                if ($candidate -and $candidate.proxy) {
                    $proxyResp = $candidate
                    $selectedGetUrl = $candidateGetUrl
                    break
                }
            } catch {
                $lastError = $_.Exception.Message
            }
        }

        if ($proxyResp) { break }
        if ($round -lt $maxFetchRounds) {
            Start-Sleep -Seconds $FetchProxyRetryIntervalSeconds
        }
    }

    if ($null -eq $proxyResp -or -not $proxyResp.proxy) {
        if ([string]::IsNullOrWhiteSpace($SystemProxy)) {
            $serviceReachable = $true
            try {
                $poolUri = [System.Uri]$poolApiBaseNorm
                $poolPort = if ($poolUri.Port -gt 0) { $poolUri.Port } else { 80 }
                $serviceReachable = Test-NetConnection -ComputerName $poolUri.Host -Port $poolPort -InformationLevel Quiet -WarningAction SilentlyContinue
            } catch {
                $serviceReachable = $true
            }

            if (-not $serviceReachable) {
                throw "Proxy pool service unreachable: $poolApiBaseNorm (tcp check failed)"
            }
            if ($lastError -and ($lastError -like "*actively refused*" -or $lastError -like "*积极拒绝*" -or $lastError -like "*无法连接*")) {
                throw "Proxy pool service unreachable: $poolApiBaseNorm (error: $lastError)"
            }
            throw "Proxy pool has no available proxy after $FetchProxyRetries retries (types=$($typeCandidates -join ',')). Last payload: $lastPayloadJson"
        }

        $proxyValue = Convert-ToProxyUrl -ProxyRaw $SystemProxy -ProxyTypeRaw "http"
        $proxySource = "pool_fallback_system"
        Write-Warning "Proxy pool unavailable, fallback to system proxy: $proxyValue"
    }
    else {
        $proxyRaw = [string]$proxyResp.proxy
        $proxyTypeRaw = [string]$proxyResp.proxy_type
        if ([string]::IsNullOrWhiteSpace($proxyTypeRaw)) {
            if ($ProxyType -eq "socks5") {
                $proxyTypeRaw = "socks5"
            } else {
                $proxyTypeRaw = "http"
            }
        }
        $proxyValue = Convert-ToProxyUrl -ProxyRaw $proxyRaw -ProxyTypeRaw $proxyTypeRaw
        $proxySource = "pool"
    }
}

$config.choose_browser = $Browser
$config.proxy = $proxyValue
$config.concurrent_flows = $Concurrency
$config.max_tasks = $TaskCount

$config.manual_captcha.enabled = $false
$config.manual_captcha.timeout_seconds = 600
$config.manual_captcha.poll_interval_seconds = 2

$config.oauth2.enable_oauth2 = $true
if (-not $config.oauth2.redirect_url -or [string]::IsNullOrWhiteSpace([string]$config.oauth2.redirect_url)) {
    $config.oauth2.redirect_url = "http://localhost:8000"
}

$config.proxy_pool.enable_auto_rotate = [bool]($ProxyMode -eq "pool_system" -and $proxySource -eq "pool")
$config.proxy_pool.api_url = $selectedGetUrl
$config.proxy_pool.delete_api_url = $poolDeleteUrl
$config.proxy_pool.retry_interval_seconds = 2
$config.proxy_pool.max_proxy_retries = $MaxProxyRetries
$config.proxy_pool.fetch_retries_per_round = 6
$config.proxy_pool.report_bad_proxy_on_probe_fail = $true
$config.proxy_pool.report_bad_proxy_on_register_fail = $true
$config.proxy_pool.enable_probe_before_switch = (-not [bool]$DisableProbe)
if (-not $config.proxy_pool.probe_url -or [string]::IsNullOrWhiteSpace([string]$config.proxy_pool.probe_url)) {
    $config.proxy_pool.probe_url = "https://outlook.live.com/mail/0/?prompt=create_account"
}
if (-not $config.proxy_pool.probe_timeout_seconds) {
    $config.proxy_pool.probe_timeout_seconds = 8
}
if (-not $config.proxy_pool.probe_success_status_codes) {
    $config.proxy_pool.probe_success_status_codes = @(200, 301, 302, 303, 307, 308, 401, 403, 405)
}
if ($null -eq $config.proxy_pool.probe_accept_non_5xx) {
    $config.proxy_pool.probe_accept_non_5xx = $true
}

if ($ProxyMode -eq "direct") {
    $config.playwright.no_system_proxy = $true
}
else {
    $config.playwright.no_system_proxy = $false
}
if ($Browser -eq "playwright") {
    $browserPath = [string]$config.playwright.browser_path
    if ([string]::IsNullOrWhiteSpace($browserPath) -or !(Test-Path -LiteralPath $browserPath)) {
        throw "choose_browser=playwright requires a valid playwright.browser_path."
    }
}

$configJson = $config | ConvertTo-Json -Depth 20
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

Write-Host "Auto mode config has been written:"
Write-Host "  Browser=$Browser Concurrency=$Concurrency TaskCount=$TaskCount"
Write-Host "  OAuth2=ON ManualCaptcha=OFF"
Write-Host "  ProxyMode=$ProxyMode Source=$proxySource"
Write-Host "  ProxyPoolGet=$($config.proxy_pool.api_url)"
Write-Host "  InitProxy=$proxyValue"
Write-Host "Starting main.py ..."

& $pythonPath "-u" "main.py"
