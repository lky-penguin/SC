[CmdletBinding()]
param(
    [switch]$SkipFrontendBuild
)

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
$StartedServices = New-Object System.Collections.Generic.List[string]

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host "==> $Message"
}

function Assert-Command([string]$Name, [string]$Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "找不到命令 '$Name'。$Hint"
    }
}

function Assert-RequiredJars {
    $required = @(
        @{ Name = 'pmwnb-service.jar'; Hint = '请从原始分发包复制到 backend\lib\' },
        @{ Name = 'nb-algorithm-service.jar'; Hint = '请运行 scripts\build_nb_algorithm_jars.ps1 或复制到 backend\lib\' },
        @{ Name = 'commons-math3-3.6.1.jar'; Hint = '请从 KFDB 原始分发包复制到 backend\lib\' },
        @{ Name = 'MLTools.jar'; Hint = '请从 KFDB 原始分发包的 lib\ 目录复制到 backend\lib\' }
    )

    $missing = @()
    foreach ($item in $required) {
        $path = Join-Path $LibDir $item.Name
        if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or (Get-Item -LiteralPath $path).Length -eq 0) {
            $missing += "  - $($item.Name)：$($item.Hint)"
        }
    }
    if ($missing.Count -gt 0) {
        throw ("缺少 Java 运行依赖：`n{0}`n依赖目录：{1}" -f ($missing -join "`n"), $LibDir)
    }
}

function Assert-PythonDependencies {
    $check = 'import fastapi, uvicorn, sqlalchemy, psycopg2, dotenv, requests'
    & python -c $check
    if ($LASTEXITCODE -ne 0) {
        throw "Python 依赖不完整。请先运行：python -m pip install -r backend\requirements.txt"
    }
}

function Test-Port([int]$Port) {
    [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Get-TrackedProcessId([string]$Name) {
    $pidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }

    $trackedId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($trackedId -match '^\d+$' -and (Get-Process -Id ([int]$trackedId) -ErrorAction SilentlyContinue)) {
        return [int]$trackedId
    }

    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    return $null
}

function Get-LogTail([string]$Name, [int]$Lines = 30) {
    $parts = @()
    foreach ($kind in @('out', 'err')) {
        $path = Join-Path $LogDir "$Name.$kind.log"
        if (Test-Path -LiteralPath $path) {
            $parts += "--- $Name.$kind.log ---"
            $parts += (Get-Content -LiteralPath $path -Tail $Lines -ErrorAction SilentlyContinue)
        }
    }
    return ($parts -join "`n")
}

function Wait-Http([string]$Name, [string]$Url, [int]$ProcessId, [int]$Seconds = 90) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            $tail = Get-LogTail $Name
            throw "$Name 进程已退出（PID=$ProcessId）。健康检查地址：$Url`n$tail"
        }
        try {
            $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
            if ($null -ne $response) { return $response }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    } while ((Get-Date) -lt $deadline)

    $tail = Get-LogTail $Name
    throw "健康检查超时：$Url`n$tail"
}

function Quote-Argument([string]$Value) {
    if ($Value -notmatch '[\s"]') { return $Value }
    return '"' + ($Value -replace '(\\*)"', '$1$1\"' -replace '(\\+)$', '$1$1') + '"'
}

function Start-Tracked([string]$Name, [string]$File, [string[]]$ArgList, [string]$WorkDir, [int]$Port) {
    $existingId = Get-TrackedProcessId $Name
    if ($null -ne $existingId) {
        Write-Host "[$Name] 已在运行 PID=$existingId"
        return [pscustomobject]@{ Id = $existingId; Started = $false }
    }

    if (Test-Port $Port) {
        throw "端口 $Port 已被其他进程占用，但未找到 $Name 的 PID 记录。请先运行 .\stop.ps1，或检查占用端口的进程。"
    }

    $argLine = ($ArgList | ForEach-Object { Quote-Argument ([string]$_) }) -join ' '
    $process = Start-Process -FilePath $File -ArgumentList $argLine -WorkingDirectory $WorkDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LogDir "$Name.out.log") `
        -RedirectStandardError (Join-Path $LogDir "$Name.err.log")

    Set-Content -LiteralPath (Join-Path $RunDir "$Name.pid") -Value $process.Id -Encoding ascii
    $StartedServices.Add($Name)
    Write-Host "[$Name] 已启动 PID=$($process.Id)"
    return [pscustomobject]@{ Id = $process.Id; Started = $true }
}

function Stop-ServiceStartedByThisRun([string]$Name) {
    $pidFile = Join-Path $RunDir "$Name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { return }
    $trackedId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
    if ($trackedId -match '^\d+$') {
        Stop-Process -Id ([int]$trackedId) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

function Stop-ServicesStartedByThisRun {
    for ($i = $StartedServices.Count - 1; $i -ge 0; $i--) {
        Stop-ServiceStartedByThisRun $StartedServices[$i]
    }
    $StartedServices.Clear()
}

Push-Location $Root
try {
    Write-Step '检查运行环境'
    Assert-Command docker '请安装 Docker Desktop 并确认 docker 命令可用。'
    Assert-Command python '请安装 Python 3.12 并加入 PATH。'
    Assert-Command java '请安装 JDK 17 或更高版本并加入 PATH。'
    if (-not $SkipFrontendBuild) { Assert-Command npm '请安装 Node.js/npm 并加入 PATH。' }
    Assert-RequiredJars

    Write-Step '启动 PostgreSQL'
    docker compose up -d --wait
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL 启动失败。请确认 Docker Desktop 正在运行。' }

    if (-not $SkipFrontendBuild) {
        Write-Step '构建前端'
        Push-Location $Frontend
        try {
            if (-not (Test-Path -LiteralPath (Join-Path $Frontend 'node_modules'))) {
                Write-Host '未找到 node_modules，正在安装前端依赖...'
                npm install
                if ($LASTEXITCODE -ne 0) { throw '前端依赖安装失败。' }
            }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
        } finally {
            Pop-Location
        }
    }

    Write-Step '检查 Python 依赖并初始化数据库'
    Assert-PythonDependencies
    Push-Location $Backend
    try {
        python -m app.init_db
        if ($LASTEXITCODE -ne 0) { throw '数据库初始化失败。' }
    } finally {
        Pop-Location
    }

    $java = (Get-Command java -ErrorAction Stop).Source
    $python = (Get-Command python -ErrorAction Stop).Source
    $lib = $LibDir

    Write-Step '启动 Java 算法服务'
    $pmwnb = Start-Tracked 'pmwnb' $java @('-Xmx1024m', '-jar', (Join-Path $lib 'pmwnb-service.jar'), [string]$PmwnbPort) $Backend $PmwnbPort
    Wait-Http 'pmwnb' "http://127.0.0.1:$PmwnbPort/health" $pmwnb.Id | Out-Null

    $nb = Start-Tracked 'nb' $java @('-Xmx1024m', '-jar', (Join-Path $lib 'nb-algorithm-service.jar'), [string]$NbPort) $Backend $NbPort
    Wait-Http 'nb' "http://127.0.0.1:$NbPort/health" $nb.Id | Out-Null

    Write-Step '启动 FastAPI'
    $api = Start-Tracked 'api' $python @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$ApiPort) $Backend $ApiPort
    $health = Wait-Http 'api' "http://127.0.0.1:$ApiPort/api/health" $api.Id

    if (-not $health.java_ready) {
        throw "Java 服务健康检查未全部通过：$($health.java | ConvertTo-Json -Compress)"
    }

    Write-Host ''
    Write-Host ("启动完成：http://127.0.0.1:{0}" -f $ApiPort) -ForegroundColor Green
    Write-Host ("健康状态：{0}；Java 服务：{1}" -f $health.status, ($health.java | ConvertTo-Json -Compress))
} catch {
    Write-Host ''
    Write-Warning $_.Exception.Message
    if ($StartedServices.Count -gt 0) {
        Write-Host '正在清理本次启动的服务进程...'
        Stop-ServicesStartedByThisRun
    }
    exit 1
} finally {
    Pop-Location
}