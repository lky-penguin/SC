[CmdletBinding()]
param()
$ErrorActionPreference = 'Continue'
$Root = $PSScriptRoot
$RunDir = Join-Path $Root 'run'
foreach ($name in @('api','nb','pmwnb')) {
  $pidFile = Join-Path $RunDir "$name.pid"
  if (Test-Path -LiteralPath $pidFile) {
    $procId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($procId -match '^\d+$') { Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
  }
}
Push-Location $Root
try { docker compose stop; if ($LASTEXITCODE -ne 0) { Write-Warning 'PostgreSQL stop failed' } } finally { Pop-Location }
Write-Host 'C services stopped; database volume preserved.'
