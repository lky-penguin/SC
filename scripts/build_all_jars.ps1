$ErrorActionPreference = "Stop"

# Rebuild the two JAR groups in dependency order:
#   1) NB algorithm service JARs (the 8 non-PMWNB algorithms share one daemon)
#   2) pmwnb-service.jar (recompile PMWNB algorithm class with view/evidence methods)
#
# Prerequisite: stop the services that hold file locks on these JARs first.

$repo = Split-Path -Parent $PSScriptRoot
$lib = Join-Path $repo "backend\lib"
$buildRoot = Join-Path $repo "java\.build-all"
$pmwnbJar = Join-Path $lib "pmwnb-service.jar"

# 1) NB algorithm JARs
Write-Host "==> [1/2] Rebuilding NB algorithm JARs ..."
& (Join-Path $PSScriptRoot "build_nb_algorithm_jars.ps1")

if (Test-Path $buildRoot) { Remove-Item -LiteralPath $buildRoot -Recurse -Force }
New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null

# 2) pmwnb-service.jar: recompile PMWNB algorithm class
$pmwnbSource = Join-Path $repo "java\algorithm-src\PMWNB\weka-src\src\main\java\weka\classifiers\bayes\PMWNB\PMWNB\PMWNB.java"
$pmwnbLineSource = Join-Path $repo "java\algorithm-src\PMWNB\weka-src\src\main\java\weka\classifiers\bayes\PMWNB\PMWNB\PMWNB_L.java"
$pmwnbServiceSource = Join-Path $repo "java\pmwnb-service\PmwnbService.java"
$pmwnbClasses = Join-Path $buildRoot "pmwnb-classes"
New-Item -ItemType Directory -Path $pmwnbClasses -Force | Out-Null
Write-Host "==> [2/2] Compiling and updating pmwnb-service.jar ..."
if (-not (Test-Path -LiteralPath $pmwnbSource)) { throw "PMWNB source not found: $pmwnbSource" }
if (-not (Test-Path -LiteralPath $pmwnbLineSource)) { throw "PMWNB_L source not found: $pmwnbLineSource" }
if (-not (Test-Path -LiteralPath $pmwnbServiceSource)) { throw "PMWNB service source not found: $pmwnbServiceSource" }
& javac -encoding UTF-8 -cp $pmwnbJar -d $pmwnbClasses $pmwnbSource $pmwnbLineSource $pmwnbServiceSource (Join-Path $repo "java\common\AlgorithmServiceSupport.java")
if ($LASTEXITCODE -ne 0) { throw "PMWNB.java compile failed" }
& jar uf $pmwnbJar -C $pmwnbClasses .
if ($LASTEXITCODE -ne 0) { throw "pmwnb-service.jar update failed" }
Write-Host "     Updated $pmwnbJar"

Write-Host ""
Write-Host "All JARs built successfully." -ForegroundColor Green
