[CmdletBinding()]
param([int]$Port = 8792)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "run\handy-voice.pid"
$HealthUrl = "http://127.0.0.1:$Port/healthz"

$health = $null
try { $health = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 3 } catch {}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  Where-Object { $_.LocalAddress -in @("127.0.0.1","::1","0.0.0.0","::") } |
  Select-Object -First 1

$rootPid = $null
if (Test-Path -LiteralPath $PidFile) {
  $raw = (Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
  $parsed = 0
  if ([int]::TryParse([string]$raw,[ref]$parsed)) { $rootPid = $parsed }
}

if (-not $health -or -not $health.ok -or $health.provider -ne "handy-local-faster-whisper") {
  Write-Output "HANDY_VOICE_HEALTHY=0"
  if ($rootPid) { Write-Output "ROOT_PID=$rootPid" }
  if ($listener) { Write-Output "LISTENER_PID=$($listener.OwningProcess)" }
  exit 1
}

Write-Output "HANDY_VOICE_HEALTHY=1"
if ($rootPid) { Write-Output "ROOT_PID=$rootPid" }
if ($listener) { Write-Output "LISTENER_PID=$($listener.OwningProcess)" }
$health | ConvertTo-Json -Compress
exit 0
