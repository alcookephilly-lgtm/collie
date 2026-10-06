[CmdletBinding()]
param([int]$Port = 8792)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Server = (Join-Path $Root "handy_stt_server.py").Replace("/", "\")

$serverProcesses = @()
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_.CommandLine -and $_.CommandLine.Contains($Server) -and $_.CommandLine -match "(?:--port\s+)$Port(?:\s|$)") {
    $serverProcesses += $_
  }
}

if ($serverProcesses.Count -eq 0) {
  Write-Output "No matching Handy Voice process is running on port $Port."
  exit 0
}

# Stop child/listener before its launcher parent when both exist.
foreach ($proc in ($serverProcesses | Sort-Object ParentProcessId -Descending)) {
  Write-Output "STOPPING_PID=$($proc.ProcessId)"
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Milliseconds 500

$left = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($left) { throw "Port $Port is still listening after stopping the matching Handy Voice processes" }

Write-Output "HANDY_VOICE_STOPPED=1"
exit 0
