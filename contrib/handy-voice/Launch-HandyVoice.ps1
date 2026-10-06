[CmdletBinding()]
param(
  [int]$Port = 8792,
  [string]$Model = "base"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Server = Join-Path $Root "handy_stt_server.py"
$RunDir = Join-Path $Root "run"
$LogDir = Join-Path $Root "logs"
$PidFile = Join-Path $RunDir "handy-voice.pid"
$LegacyPidFile = Join-Path $Root "handy-voice.pid"
$Stdout = Join-Path $LogDir "handy-voice.log"
$Stderr = Join-Path $LogDir "handy-voice-error.log"
$HealthUrl = "http://127.0.0.1:$Port/healthz"

function Get-HandyHealth {
  try {
    $r = Invoke-RestMethod -Uri $HealthUrl -Method Get -TimeoutSec 2
    if ($r.provider -eq "handy-local-faster-whisper" -and $r.ok) { return $r }
  } catch {}
  return $null
}

$health = Get-HandyHealth
if ($health) {
  Write-Output "Handy Voice already running on 127.0.0.1:$Port (model=$($health.model))."
  exit 0
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -in @("127.0.0.1","::1","0.0.0.0","::") } | Select-Object -First 1
if ($listener) {
  throw "Port $Port is already owned by PID $($listener.OwningProcess); refusing to replace it."
}

if (-not (Test-Path -LiteralPath $Pythonw)) { throw "Handy Voice venv is missing: $Pythonw" }
if (-not (Test-Path -LiteralPath $Server)) { throw "Handy Voice server is missing: $Server" }

New-Item -ItemType Directory -Force -Path $RunDir,$LogDir | Out-Null
$env:HF_HUB_OFFLINE = "1"
$env:HANDY_STT_MODEL = $Model

$p = Start-Process -FilePath $Pythonw -ArgumentList @($Server,"--host","127.0.0.1","--port",[string]$Port,"--model",$Model) -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -PassThru
Set-Content -LiteralPath $PidFile -Value ([string]$p.Id) -Encoding ascii
Set-Content -LiteralPath $LegacyPidFile -Value ([string]$p.Id) -Encoding ascii

for ($i=0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  $health = Get-HandyHealth
  if ($health) {
    Write-Output "Handy Voice started: PID=$($p.Id) URL=http://127.0.0.1:$Port/v1 model=$($health.model)"
    exit 0
  }
  if ($p.HasExited) {
    throw "Handy Voice exited during startup with code $($p.ExitCode). See $Stderr"
  }
}
throw "Handy Voice did not become healthy. See $Stderr"
