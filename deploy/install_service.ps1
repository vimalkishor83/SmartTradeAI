#Requires -RunAsAdministrator
<#
.SYNOPSIS
  Registers the SmartTradeAI app process (serve.py) as a Windows service
  via NSSM, so it starts automatically on boot and restarts itself if it
  ever crashes — IIS reverse-proxies to it, but doesn't run it.

.PARAMETER NssmPath
  Path to nssm.exe. Download it from https://nssm.cc/download (no official
  package manager release; grab the win64 build) and point this at it, e.g.
  -NssmPath "C:\tools\nssm-2.24\win64\nssm.exe"

.NOTES
  Don't have/want NSSM? Use Windows Task Scheduler instead — see the
  "No NSSM?" section in deploy/README.md.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$NssmPath,
    [string]$ServiceName = "SmartTradeAI",
    [string]$PythonExe = "C:\Program Files\Python312\python.exe"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$serveScript = Join-Path $repoRoot "serve.py"

if (-not (Test-Path $NssmPath)) { throw "nssm.exe not found at $NssmPath — download from https://nssm.cc/download" }
if (-not (Test-Path $serveScript)) { throw "serve.py not found at $serveScript" }
if (-not (Test-Path $PythonExe)) { throw "Python not found at $PythonExe — pass -PythonExe if it's installed elsewhere" }

$existing = & $NssmPath status $ServiceName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Service '$ServiceName' already registered (status: $existing) — stopping to reconfigure..."
    & $NssmPath stop $ServiceName | Out-Null
    & $NssmPath remove $ServiceName confirm | Out-Null
}

Write-Host "Registering '$ServiceName' -> $PythonExe $serveScript" -ForegroundColor Cyan
& $NssmPath install $ServiceName $PythonExe $serveScript
& $NssmPath set $ServiceName AppDirectory $repoRoot
& $NssmPath set $ServiceName AppStdout (Join-Path $repoRoot "logs\service_stdout.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $repoRoot "logs\service_stderr.log")
& $NssmPath set $ServiceName AppRotateFiles 1
& $NssmPath set $ServiceName AppRotateBytes 10485760
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppExit Default Restart   # auto-restart on crash
& $NssmPath set $ServiceName AppRestartDelay 3000       # 3s before restart

Write-Host "Starting service..." -ForegroundColor Cyan
& $NssmPath start $ServiceName

Start-Sleep -Seconds 3
& $NssmPath status $ServiceName

Write-Host ""
Write-Host "Done. Logs: $repoRoot\logs\service_std{out,err}.log" -ForegroundColor Green
Write-Host "Manage later with: nssm start|stop|restart $ServiceName" -ForegroundColor Green
