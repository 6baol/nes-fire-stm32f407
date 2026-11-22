param(
    [Parameter(Mandatory=$true)][string]$Rom,
    [string]$Name,
    [string]$Cover,
    [switch]$Build,
    [string]$PythonExe = 'python'
)
$ErrorActionPreference = 'Stop'
$importArgs = @((Join-Path $PSScriptRoot 'tools/add_game.py'), $Rom)
if ($Name) { $importArgs += @('--name', $Name) }
if ($Cover) { $importArgs += @('--cover', $Cover) }
& $PythonExe @importArgs
if ($LASTEXITCODE -ne 0) { throw 'Import rejected; the existing game list was preserved.' }
if ($Build) { & (Join-Path $PSScriptRoot 'build.ps1') }
Write-Output 'Done. No firmware was downloaded to the board.'
