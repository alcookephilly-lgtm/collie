[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$CollieRoot,
  [string]$StateDir,
  [string]$ConfigDir,
  [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
  [string[]]$SttArgs
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($CollieRoot)) {
  $CollieRoot = if ($env:COLLIE_ROOT) {
    $env:COLLIE_ROOT
  } else {
    Join-Path $env:USERPROFILE "herdr-collie-build\source\collie"
  }
}
if ([string]::IsNullOrWhiteSpace($StateDir)) {
  $StateDir = Join-Path $env:LOCALAPPDATA "herdr\plugins\herdr.collie"
}
if ([string]::IsNullOrWhiteSpace($ConfigDir)) {
  $ConfigDir = Join-Path $env:APPDATA "herdr\plugins\config\herdr.collie"
}

if (-not (Test-Path -LiteralPath (Join-Path $CollieRoot "cli\main.ts"))) {
  throw "Collie checkout not found at $CollieRoot"
}

$Bun = (Get-Command bun.exe -ErrorAction SilentlyContinue).Source
if (-not $Bun) {
  $WingetPackages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
  if (Test-Path -LiteralPath $WingetPackages) {
    $Bun = Get-ChildItem -LiteralPath $WingetPackages -Directory -Filter "Oven-sh.Bun_*" -ErrorAction SilentlyContinue |
      ForEach-Object { Join-Path $_.FullName "bun-windows-x64\bun.exe" } |
      Where-Object { Test-Path -LiteralPath $_ } |
      Select-Object -First 1
  }
}
if (-not $Bun) { throw "bun.exe was not found" }

$env:HERDR_PLUGIN_CONFIG_DIR = $ConfigDir
$env:HERDR_PLUGIN_STATE_DIR = $StateDir
$env:COLLIE_STATE_DIR = $StateDir

Push-Location $CollieRoot
try {
  & $Bun run cli/main.ts stt @SttArgs
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
