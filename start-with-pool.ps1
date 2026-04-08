$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$poolApi = "http://127.0.0.1:5010"
$configPath = Join-Path $projectRoot "config.json"
$pythonPath = Join-Path $projectRoot ".venv\\Scripts\\python.exe"

if (!(Test-Path -LiteralPath $pythonPath)) {
    throw "未找到虚拟环境 Python: $pythonPath"
}

$proxyResp = Invoke-RestMethod -Uri "$($poolApi.TrimEnd('/'))/get/?type=https" -TimeoutSec 15
if (-not $proxyResp.proxy) {
    throw "代理池未返回可用代理，请先检查池子状态: $poolApi"
}

$proxyValue = "http://$($proxyResp.proxy)"
$config = Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json
$config.proxy = $proxyValue
$configJson = $config | ConvertTo-Json -Depth 10
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($configPath, $configJson, $utf8NoBom)

Write-Host "当前代理: $proxyValue"
& $pythonPath "main.py"
