param(
    [string]$PythonExe = (Join-Path (Split-Path $PSScriptRoot -Parent) '.tools\dap\Scripts\python.exe'),
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Workspace DAP environment not found.' }
$arguments = @((Join-Path $PSScriptRoot 'tools\dap_flash.py'))
if ($VerifyOnly) { $arguments += '--verify-only' }
& $PythonExe @arguments
if ($LASTEXITCODE -ne 0) { throw 'DAP programming or full Flash readback verification failed.' }
