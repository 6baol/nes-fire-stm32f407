param([string]$KeilExe = "$env:LOCALAPPDATA\Keil_v5\UV4\UV4.exe", [string]$Version = '0.20-core-preview', [switch]$Embedded)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid release version.' }
$project = Join-Path $PSScriptRoot 'Project\Fire_F407ZG.uvprojx'
if ($Embedded) {
    & python (Join-Path $PSScriptRoot 'tools/embed_roms.py') check-embedded
    if ($LASTEXITCODE -ne 0) { throw 'Embedded ROM budget exceeded; use the default SD build.' }
    $contents = [System.IO.File]::ReadAllText($project).Replace('USE_HAL_DRIVER,STM32F407xx,NES_SD_LIBRARY','USE_HAL_DRIVER,STM32F407xx')
    $project = Join-Path $PSScriptRoot 'Project\Fire_F407ZG_embedded.uvprojx'
    [System.IO.File]::WriteAllText($project,$contents,[System.Text.UTF8Encoding]::new($false))
    if ($Version -eq '0.20-core-preview') { $Version = '0.20-embedded-preview' }
}
if (-not $Embedded) {
    & python (Join-Path $PSScriptRoot 'tools/prepare_sd.py')
    if ($LASTEXITCODE -ne 0) { throw 'SD resource preparation failed.' }
}
$firmwarePrefix = 'NesFire_v' + $Version
$log = Join-Path $PSScriptRoot 'Project\build.log'
if (-not (Test-Path -LiteralPath $KeilExe)) { throw "Keil UV4 not found: $KeilExe" }
$started = Get-Date
$arguments = @('-r', ('"{0}"' -f $project), '-j0', '-o', ('"{0}"' -f $log))
$process = Start-Process -FilePath $KeilExe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
$result = Get-Content -LiteralPath $log -Raw
Write-Output $result
if ($result -notmatch '0 Error\(s\), 0 Warning\(s\)') { throw 'Build failed or emitted warnings; see Project/build.log.' }
$hex = Join-Path $PSScriptRoot 'Project\Output\Fire_F407ZG.hex'
if ((Get-Item -LiteralPath $hex).LastWriteTime -lt $started) { throw 'HEX was not refreshed by this build.' }
$release = Join-Path $PSScriptRoot 'Release'
New-Item -ItemType Directory -Path $release -Force | Out-Null
Copy-Item -LiteralPath $hex -Destination (Join-Path $release ($firmwarePrefix + '.hex'))
$fromelf = Join-Path (Split-Path (Split-Path $KeilExe -Parent) -Parent) 'ARM\ARMCLANG\bin\fromelf.exe'
& $fromelf --bin --output (Join-Path $release ($firmwarePrefix + '.bin')) (Join-Path $PSScriptRoot 'Project\Output\Fire_F407ZG.axf')
if ($LASTEXITCODE -ne 0) { throw 'BIN conversion failed.' }
Get-FileHash -LiteralPath (Join-Path $release ($firmwarePrefix + '.hex')) -Algorithm SHA256
$files = [ordered]@{}
foreach ($name in @(($firmwarePrefix + '.hex'), ($firmwarePrefix + '.bin'))) {
    $path = Join-Path $release $name
    $files[$name] = [ordered]@{
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    version = $Version
    target = 'STM32F407ZGT6 / Batianhu V2 / 480x800 MCU LCD'
    compiler = 'Arm Compiler 6.24 (Keil project selection)'
    build = '0 errors, 0 warnings (full rebuild)'
    hardware_tested = $false
    storage_mode = $(if ($Embedded) {'all games and posters embedded'} else {'SD library; first game embedded as fallback'})
    embedded_game_count = $(if ($Embedded) {(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Roms/roms.json') -Raw | ConvertFrom-Json).games.Count} else {1})
    wiring = 'VRx=PA4 (CN3-25), VRy=PA6 (CN3-21), SW=PB7 (CN3-23), 3V3/GND; camera disconnected'
    firmware_prefix = $firmwarePrefix
    rom = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Roms/current.json') -Raw | ConvertFrom-Json)
    files = $files
}
$biosManifest = Join-Path $PSScriptRoot 'Roms/bios.json'
if (Test-Path -LiteralPath $biosManifest) {
    $manifest['bios'] = Get-Content -LiteralPath $biosManifest -Raw | ConvertFrom-Json
}
$manifest['fds_mode'] = 'read-only disk; Select+left/right side swap; NES APU plus FDS wavetable/envelopes/modulation'
$manifest['save_mode'] = 'SD battery cartridge SRAM; CRC-checked dual slots; save on menu exit; no instant states or FDS disk writes'
$manifest['audio_default'] = 'SPEAKER; Settings can select HEADPHONES / SPEAKER / MUTE; reset returns to SPEAKER'
$posterManifest = Join-Path $PSScriptRoot 'Assets/posters/manifest.json'
if (Test-Path -LiteralPath $posterManifest) {
    $manifest['posters'] = Get-Content -LiteralPath $posterManifest -Raw | ConvertFrom-Json
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $release 'manifest.json') -Encoding utf8
