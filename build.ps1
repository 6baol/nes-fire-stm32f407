param(
    [string]$KeilExe,
    [string]$Version,
    [switch]$Embedded,
    [string]$PythonExe = 'python',
    [string]$FromElfExe
)
$ErrorActionPreference = 'Stop'

$release = Join-Path $PSScriptRoot 'Release'
if (-not $Version) {
    $Version = (Get-Content -LiteralPath (Join-Path $release 'VERSION') -Raw).Trim()
    if ($Embedded) { $Version += '-embedded' }
}
if ($Version -notmatch '^[A-Za-z0-9._-]+$') { throw 'Invalid release version.' }

if (-not $KeilExe) {
    $installedCommand = Get-Command UV4.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $keilCandidates = @(
        $installedCommand.Source,
        "$env:LOCALAPPDATA\Keil_v5\UV4\UV4.exe",
        "$env:SystemDrive\Keil_v5\UV4\UV4.exe"
    )
    $KeilExe = $keilCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $KeilExe -or -not (Test-Path -LiteralPath $KeilExe -PathType Leaf)) {
    throw 'Keil UV4.exe not found. Set -KeilExe to the Keil MDK installation path.'
}
$KeilExe = (Resolve-Path -LiteralPath $KeilExe).ProviderPath
if (-not $FromElfExe) {
    $compilerDir = Join-Path (Split-Path (Split-Path $KeilExe -Parent) -Parent) 'ARM\ARMCLANG\bin'
    $FromElfExe = Join-Path $compilerDir 'fromelf.exe'
}
if (-not (Test-Path -LiteralPath $FromElfExe -PathType Leaf)) {
    throw "Arm Compiler fromelf.exe not found. Set -FromElfExe to the compiler executable path: $FromElfExe"
}

$commit = $null
$sourceDirty = $null
if (Get-Command git -CommandType Application -ErrorAction SilentlyContinue) {
    $commit = & git -C $PSScriptRoot rev-parse --verify HEAD 2>$null
    if ($LASTEXITCODE -eq 0) {
        $sourceChanges = & git -C $PSScriptRoot status --porcelain
        if ($LASTEXITCODE -eq 0) { $sourceDirty = [bool]$sourceChanges }
    } else { $commit = $null }
}

$project = Join-Path $PSScriptRoot 'Project\Fire_F407ZG.uvprojx'
if ($Embedded) {
    & $PythonExe (Join-Path $PSScriptRoot 'tools/embed_roms.py') check-embedded
    if ($LASTEXITCODE -ne 0) { throw 'Embedded ROM budget exceeded; use the default SD build.' }
    $contents = [System.IO.File]::ReadAllText($project).Replace('USE_HAL_DRIVER,STM32F407xx,NES_SD_LIBRARY','USE_HAL_DRIVER,STM32F407xx')
    $project = Join-Path $PSScriptRoot 'Project\Fire_F407ZG_embedded.uvprojx'
    [System.IO.File]::WriteAllText($project,$contents,[System.Text.UTF8Encoding]::new($false))
}
if (-not $Embedded) {
    & $PythonExe (Join-Path $PSScriptRoot 'tools/prepare_sd.py')
    if ($LASTEXITCODE -ne 0) { throw 'SD resource preparation failed.' }
}
$firmwarePrefix = 'NesFire_v' + $Version
$log = Join-Path $PSScriptRoot 'Project\build.log'
$started = [DateTime]::UtcNow
$arguments = @('-r', ('"{0}"' -f $project), '-j0', '-sg', '-o', ('"{0}"' -f $log))
$process = Start-Process -FilePath $KeilExe -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
$result = Get-Content -LiteralPath $log -Raw
Write-Output $result
if ($process.ExitCode -ne 0 -or $result -notmatch '0 Error\(s\), 0 Warning\(s\)') {
    throw 'Build failed or emitted warnings. See Project/build.log.'
}
$configuredCompiler = [regex]::Match((Get-Content -LiteralPath $project -Raw), '<pCCUsed>\d+::V([\d.]+)::ARMCLANG</pCCUsed>')
$actualCompiler = [regex]::Match($result, "Using Compiler 'V([\d.]+)'")
if (-not $actualCompiler.Success -or -not $configuredCompiler.Success -or
    $actualCompiler.Groups[1].Value -ne $configuredCompiler.Groups[1].Value) {
    throw 'Compiler version does not match the Keil project. See Project/build.log.'
}
$hex = Join-Path $PSScriptRoot 'Project\Output\Fire_F407ZG.hex'
$axf = Join-Path $PSScriptRoot 'Project\Output\Fire_F407ZG.axf'
foreach ($artifact in @($hex, $axf)) {
    if ((Get-Item -LiteralPath $artifact).LastWriteTimeUtc -lt $started) {
        throw "Build output was not refreshed: $artifact"
    }
}
New-Item -ItemType Directory -Path $release -Force | Out-Null
$binary = Join-Path $release ($firmwarePrefix + '.bin')
& $FromElfExe --bin --output $binary $axf
if ($LASTEXITCODE -ne 0) { throw 'BIN conversion failed.' }
Copy-Item -LiteralPath $hex -Destination (Join-Path $release ($firmwarePrefix + '.hex'))
Copy-Item -LiteralPath $axf -Destination (Join-Path $release ($firmwarePrefix + '.axf'))
$artifactSuffixes = @('.hex', '.bin', '.axf')
$map = Join-Path $PSScriptRoot 'Project\Listings\Fire_F407ZG.map'
if ((Test-Path -LiteralPath $map -PathType Leaf) -and (Get-Item -LiteralPath $map).LastWriteTimeUtc -ge $started) {
    Copy-Item -LiteralPath $map -Destination (Join-Path $release ($firmwarePrefix + '.map'))
    $artifactSuffixes += '.map'
}
Get-FileHash -LiteralPath $binary -Algorithm SHA256
$files = [ordered]@{}
foreach ($suffix in $artifactSuffixes) {
    $name = $firmwarePrefix + $suffix
    $path = Join-Path $release $name
    $files[$name] = [ordered]@{
        bytes = (Get-Item -LiteralPath $path).Length
        sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$manifest = [ordered]@{
    version = $Version
    git_commit = $commit
    source_dirty = $sourceDirty
    target = 'STM32F407ZGT6 / Batianhu V2 / 480x800 MCU LCD'
    compiler = "Arm Compiler $($actualCompiler.Groups[1].Value) (Keil project selection)"
    build = '0 errors, 0 warnings (full rebuild)'
    hardware_tested = $false
    hardware_acceptance = 'separate board measurement required'
    storage_mode = $(if ($Embedded) {'all games and posters embedded'} else {'SD library; first game embedded as fallback'})
    embedded_game_count = $(if ($Embedded) {(Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Roms/roms.json') -Raw | ConvertFrom-Json).games.Count} else {1})
    wiring = 'VRx=PA4 (CN3-25), VRy=PA6 (CN3-21), SW=PB7 (CN3-23), 3V3/GND; camera disconnected'
    firmware_prefix = $firmwarePrefix
    rom = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Roms/current.json') -Raw | ConvertFrom-Json)
    files = $files
}
$memory = [regex]::Match($result, 'Program Size: Code=(\d+)\s+RO-data=(\d+)\s+RW-data=(\d+)\s+ZI-data=(\d+)')
if ($memory.Success) {
    $manifest['linker_bytes'] = [ordered]@{
        code = [int]$memory.Groups[1].Value
        read_only = [int]$memory.Groups[2].Value
        read_write = [int]$memory.Groups[3].Value
        zero_initialized = [int]$memory.Groups[4].Value
    }
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
$manifestText = $manifest | ConvertTo-Json -Depth 5
$manifestText | Set-Content -LiteralPath (Join-Path $release ($firmwarePrefix + '.manifest.json')) -Encoding utf8
$manifestText | Set-Content -LiteralPath (Join-Path $release 'manifest.json') -Encoding utf8
