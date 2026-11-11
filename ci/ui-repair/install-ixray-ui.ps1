param([string]$GameRoot = $PSScriptRoot)
$ErrorActionPreference = 'Stop'

function Hash([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$GameRoot = (Resolve-Path -LiteralPath $GameRoot).Path
if (!(Test-Path -LiteralPath (Join-Path $GameRoot 'fsgame.ltx') -PathType Leaf) -or
    !(Test-Path -LiteralPath (Join-Path $GameRoot 'bin/xrEngine.exe') -PathType Leaf)) {
    throw 'Extract the archive to the game directory containing fsgame.ltx and bin/xrEngine.exe.'
}
if (Get-Process -Name xrEngine -ErrorAction SilentlyContinue) {
    throw 'Close the game before installing the UI repair.'
}

$payload = Join-Path $PSScriptRoot 'ixray-ui-repair-payload'
$manifest = Get-Content -LiteralPath (Join-Path $payload 'manifest.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$module = 'bin/xrGame.dll'
$locale = 'gamedata/configs/text/rus/ui_st_ixray_loot_monsters.xml'
$assets = @(
    $locale,
    'gamedata/textures/ui/ui_flags.dds',
    'gamedata/textures/ui/ui_ix-ray_team_logo.dds',
    'gamedata/textures/ui/ui_ixray_ex.dds',
    'gamedata/textures/ui/ui_ixray_mutant_portrets.dds'
)
$files = @($module) + $assets
foreach ($file in $files) {
    $expected = $manifest.files.PSObject.Properties[$file].Value
    if ($expected -notmatch '^[a-f0-9]{64}$' -or (Hash (Join-Path $payload $file)) -ne $expected) {
        throw "Package checksum mismatch for $file."
    }
}

$dll = Join-Path $GameRoot $module
$oldHash = '2c70ee3a9894f0d02ec00a4e38ad7c59f69ec9e624699841825a641f1195d70a'
$newHash = $manifest.files.PSObject.Properties[$module].Value
$backup = "$dll.before-ui-repair.bak"
$lockFile = Join-Path $GameRoot 'bin/ixray-ui-repair.lock'
$lock = [IO.File]::Open($lockFile, 'OpenOrCreate', 'ReadWrite', 'None')
$added = [Collections.Generic.List[string]]::new()
$temporary = $null
try {
    $installed = Hash $dll
    if ($installed -notin @($oldHash, $newHash)) {
        throw "Unsupported xrGame.dll SHA-256 $installed. This update is for build 8863370."
    }
    if ((Test-Path -LiteralPath $backup) -and (Hash $backup) -ne $oldHash) {
        throw 'An unrelated backup file already exists.'
    }
    $localizedFile = Join-Path $GameRoot $locale
    if ((Test-Path -LiteralPath $localizedFile) -and
        (Hash $localizedFile) -ne $manifest.files.PSObject.Properties[$locale].Value) {
        throw 'A different monster-name resource already exists.'
    }
    foreach ($file in $assets) {
        $target = Join-Path $GameRoot $file
        if (Test-Path -LiteralPath $target) { continue }
        [IO.Directory]::CreateDirectory((Split-Path -Parent $target)) | Out-Null
        $temporary = "$target.ixray-ui-$PID"
        [IO.File]::Copy((Join-Path $payload $file), $temporary)
        [IO.File]::Move($temporary, $target)
        $added.Add($target)
        $temporary = $null
    }
    if ($installed -eq $oldHash) {
        $temporary = "$dll.ixray-ui-$PID"
        [IO.File]::Copy((Join-Path $payload $module), $temporary)
        if ((Hash $dll) -ne $oldHash) { throw 'xrGame.dll changed during installation.' }
        if ([IO.File]::Exists($backup)) {
            [IO.File]::Replace($temporary, $dll, [NullString]::Value)
        } else {
            [IO.File]::Replace($temporary, $dll, $backup)
        }
        $temporary = $null
    }
} catch {
    if ($temporary -and [IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) }
    foreach ($path in $added) { [IO.File]::Delete($path) }
    throw
} finally {
    $lock.Dispose()
}
Write-Host 'UI repair installed.'
Write-Host "Original game DLL backup: $backup"
