#Requires -RunAsAdministrator
<#
.SYNOPSIS
  One-time IIS setup for SmartTradeAI: enables IIS + WebSocket support,
  then creates an IIS site that reverse-proxies to the app process on
  127.0.0.1:5000 (see ../serve.py).

.NOTES
  Run this AFTER you've manually installed, from the official Microsoft/IIS
  download pages (no silent/automated install available for these two):
    - Application Request Routing (ARR):
      https://www.iis.net/downloads/microsoft/application-request-routing
    - URL Rewrite:
      https://www.iis.net/downloads/microsoft/url-rewrite

  Safe to re-run — every step checks current state first.
#>

param(
    [string]$SiteName = "SmartTradeAI",
    [int]$Port = 80,
    [string]$PhysicalPath = (Join-Path $PSScriptRoot "iis_site")
)

$ErrorActionPreference = "Stop"

Write-Host "== 1. Enabling required Windows features (IIS + WebSocket Protocol) ==" -ForegroundColor Cyan
$features = @(
    "IIS-WebServerRole",
    "IIS-WebServer",
    "IIS-CommonHttpFeatures",
    "IIS-HttpErrors",
    "IIS-ApplicationDevelopment",
    "IIS-Security",
    "IIS-RequestFiltering",
    "IIS-StaticContent",
    "IIS-WebSockets",          # required for the live price stream / Socket.IO
    "IIS-HttpCompressionStatic",
    "IIS-ManagementConsole"
)
foreach ($f in $features) {
    $state = (Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue).State
    if ($state -ne "Enabled") {
        Write-Host "  Enabling $f..."
        Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart | Out-Null
    } else {
        Write-Host "  $f already enabled"
    }
}

Write-Host "== 2. Checking for ARR + URL Rewrite ==" -ForegroundColor Cyan
$arrInstalled = Test-Path "$env:SystemRoot\System32\inetsrv\requestRouter.dll"
$rewriteInstalled = Test-Path "$env:SystemRoot\System32\inetsrv\rewrite.dll"
if (-not $arrInstalled) {
    Write-Warning "Application Request Routing not found. Install it first from:"
    Write-Warning "  https://www.iis.net/downloads/microsoft/application-request-routing"
    Write-Warning "Then re-run this script."
    exit 1
}
if (-not $rewriteInstalled) {
    Write-Warning "URL Rewrite module not found. Install it first from:"
    Write-Warning "  https://www.iis.net/downloads/microsoft/url-rewrite"
    Write-Warning "Then re-run this script."
    exit 1
}
Write-Host "  ARR and URL Rewrite both present"

Import-Module WebAdministration -ErrorAction Stop

Write-Host "== 3. Enabling ARR's reverse-proxy feature server-wide ==" -ForegroundColor Cyan
Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "enabled" -Value "True"
try {
    # Rewrites Location/Set-Cookie domain in proxied responses to match the
    # public-facing host — optional tuning, don't fail setup if this
    # particular ARR build doesn't expose it.
    Set-WebConfigurationProperty -PSPath "MACHINE/WEBROOT/APPHOST" -Filter "system.webServer/proxy" -Name "reverseRewriteHostInResponseHeaders" -Value "True" -ErrorAction Stop
} catch {
    Write-Host "  (skipped optional reverseRewriteHostInResponseHeaders setting)"
}

Write-Host "== 4. Creating IIS app pool + site ==" -ForegroundColor Cyan
if (-not (Test-Path "IIS:\AppPools\$SiteName")) {
    New-WebAppPool -Name $SiteName | Out-Null
    # No .NET/CLR needed — this pool only hosts static web.config + URL Rewrite,
    # the actual app runs as its own separate Python process.
    Set-ItemProperty "IIS:\AppPools\$SiteName" -Name managedRuntimeVersion -Value ""
    Write-Host "  App pool '$SiteName' created"
} else {
    Write-Host "  App pool '$SiteName' already exists"
}

if (-not (Test-Path "IIS:\Sites\$SiteName")) {
    New-Website -Name $SiteName -Port $Port -PhysicalPath $PhysicalPath -ApplicationPool $SiteName | Out-Null
    Write-Host "  Site '$SiteName' created on port $Port -> $PhysicalPath"
} else {
    Write-Host "  Site '$SiteName' already exists — updating physical path/port"
    Set-ItemProperty "IIS:\Sites\$SiteName" -Name physicalPath -Value $PhysicalPath
}

Write-Host ""
Write-Host "Done. Next: start the app process itself (deploy/install_service.ps1)," -ForegroundColor Green
Write-Host "then browse to http://localhost:$Port/ (or http://<this-machine's-LAN-IP>:$Port/ from another device)." -ForegroundColor Green
