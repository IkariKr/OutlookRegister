param(
    [switch]$NoBrowser,
    [switch]$DryRun,
    [int]$BrowserDelaySeconds = 3
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$url = "http://127.0.0.1:5175"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm not found. Please install Node.js first."
}

if (-not (Test-Path -LiteralPath (Join-Path $scriptDir "node_modules"))) {
    Write-Host "node_modules not found, running npm install ..."
    if (-not $DryRun) {
        & npm install --prefix $scriptDir
    }
}

$serverCmd = "Set-Location -LiteralPath '$scriptDir'; npm run server"
$devCmd = "Set-Location -LiteralPath '$scriptDir'; npm run dev"

Write-Host "Starting manager API terminal: npm run server"
Write-Host "Starting Vite dev terminal: npm run dev"

if (-not $DryRun) {
    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $serverCmd
    )

    Start-Sleep -Seconds 1

    Start-Process -FilePath "powershell" -ArgumentList @(
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-Command", $devCmd
    )

    if (-not $NoBrowser) {
        Start-Sleep -Seconds ([Math]::Max(0, $BrowserDelaySeconds))
        Start-Process $url
    }
}

Write-Host "Done."
Write-Host "API:  http://127.0.0.1:8787"
Write-Host "Web:  $url"
Write-Host "Tip:  stop with task manager or close both PowerShell windows."
