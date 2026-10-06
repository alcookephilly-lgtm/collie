[CmdletBinding()]
param([int]$Port = 8792)
$ErrorActionPreference = "Stop"
$r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/healthz" -Method Get -TimeoutSec 3
$r | ConvertTo-Json -Depth 5
