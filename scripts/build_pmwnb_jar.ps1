$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$baseJar = Join-Path $repo "backend\lib\pmwnb-service.jar"
$buildRoot = Join-Path $repo "java\.build-pmwnb-service"
$classes = Join-Path $buildRoot "classes"
$baseSnapshot = Join-Path $buildRoot "pmwnb-base.jar"
$serviceSource = Join-Path $repo "java\pmwnb-service\PmwnbService.java"
$targetJar = Join-Path $repo "backend\lib\pmwnb-service.jar"

if (-not (Test-Path -LiteralPath $baseJar)) { throw "找不到 PMWNB JAR: $baseJar" }
if (-not (Test-Path -LiteralPath $serviceSource)) { throw "找不到 PMWNB 服务源码: $serviceSource" }

if (Test-Path -LiteralPath $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $classes -Force | Out-Null
Copy-Item -LiteralPath $baseJar -Destination $baseSnapshot -Force

Write-Host "Compiling configurable PMWNB service from $serviceSource ..."
& javac -encoding UTF-8 -cp $baseSnapshot -d $classes $serviceSource (Join-Path $repo "java\common\AlgorithmServiceSupport.java")
if ($LASTEXITCODE -ne 0) { throw "PMWNB service javac 编译失败" }

# Keep the original PMWNB implementation and shaded dependencies. Replace only
# the HTTP service so filtering is part of the serialized training pipeline.
Copy-Item -LiteralPath $baseSnapshot -Destination $targetJar -Force
& jar uf $targetJar -C $classes .
if ($LASTEXITCODE -ne 0) { throw "PMWNB JAR 更新失败" }

Write-Host "Created $targetJar"
