[CmdletBinding()]
param([switch]$SkipFrontendBuild)
$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$RunDir = Join-Path $Root 'run'
$LogDir = Join-Path $Root 'logs'
$LibDir = Join-Path $Backend 'lib'
$ApiPort = 18201
$PmwnbPort = 18211
$NbPort = 18212
New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

function Test-Port([int]$Port) { [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1) }
function Wait-Http([string]$Url, [int]$Seconds = 90) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  do { try { $r = Invoke-RestMethod -Uri $Url -TimeoutSec 3; if ($null -ne $r) { return $r } } catch { Start-Sleep -Milliseconds 750 } } while ((Get-Date) -lt $deadline)
  throw "健康检查超时: $Url"
}
function Start-Tracked([string]$Name, [string]$File, [string[]]$ArgList, [string]$WorkDir) {
  $pidFile = Join-Path $RunDir "$Name.pid"
  if (Test-Path -LiteralPath $pidFile) {
    $old = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($old -match '^\d+$' -and (Get-CimInstance Win32_Process -Filter "ProcessId = $old" -ErrorAction SilentlyContinue)) { Write-Host "[$Name] already running PID=$old"; return }
  }
  $p = Start-Process -FilePath $File -ArgumentList $ArgList -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $LogDir "$Name.out.log") -RedirectStandardError (Join-Path $LogDir "$Name.err.log")
  Set-Content -LiteralPath $pidFile -Value $p.Id -Encoding ascii
  Write-Host "[$Name] started PID=$($p.Id)"
}

Push-Location $Root
try {
  docker compose up -d --wait
  if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败' }
  if (-not $SkipFrontendBuild) {
    Push-Location $Frontend
    try { npm run build; if ($LASTEXITCODE -ne 0) { throw '前端构建失败' } } finally { Pop-Location }
  }
  Push-Location $Backend
  try { python -m app.init_db; if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败' } } finally { Pop-Location }
  foreach ($port in @($PmwnbPort, $NbPort, $ApiPort)) { if (Test-Port $port) { throw "端口 $port 已被占用" } }
  $java = (Get-Command java -ErrorAction Stop).Source
  Start-Tracked 'pmwnb' $java @('-Xmx1024m','-jar',(Join-Path $LibDir 'pmwnb-service.jar'),[string]$PmwnbPort) $Backend
  Start-Tracked 'nb' $java @('-Xmx1024m','-jar',(Join-Path $LibDir 'nb-algorithm-service.jar'),[string]$NbPort) $Backend
  Wait-Http "http://127.0.0.1:$PmwnbPort/health" | Out-Null
  Wait-Http "http://127.0.0.1:$NbPort/health" | Out-Null
  $python = (Get-Command python -ErrorAction Stop).Source
  Start-Tracked 'api' $python @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port',[string]$ApiPort) $Backend
  $health = Wait-Http "http://127.0.0.1:$ApiPort/api/health"
  Write-Host ("C ready: http://127.0.0.1:{0}  health={1}  java_ready={2}" -f $ApiPort, $health.status, $health.java_ready)
} finally { Pop-Location }
