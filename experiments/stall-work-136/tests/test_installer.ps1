$ErrorActionPreference='Stop'
$testRoot=Join-Path $env:RUNNER_TEMP ('ixray_installer_'+[guid]::NewGuid().ToString('N'))
$game=Join-Path $testRoot 'game'; $destination=Join-Path $game 'bin'; $package=Join-Path $testRoot 'package'; $payload=Join-Path $package 'bin'
New-Item -ItemType Directory -Path $destination,$payload -Force | Out-Null
$source=Split-Path $PSScriptRoot -Parent
Copy-Item (Join-Path $source 'install.ps1'),(Join-Path $source 'restore.ps1') -Destination $package
[IO.File]::WriteAllText((Join-Path $destination 'xrEngine.exe'),'original engine')
[IO.File]::WriteAllText((Join-Path $destination 'xrGame.dll'),'original game')
$modules=@()
foreach ($name in @('xrEngine.exe','xrGame.dll','extra.dll')) {
  $path=Join-Path $payload $name
  [IO.File]::WriteAllText($path,('new '+$name))
  $modules += [PSCustomObject]@{name=$name;sha256=(Get-FileHash -Algorithm SHA256 $path).Hash.ToLowerInvariant()}
}
[PSCustomObject]@{commit='test';modules=$modules} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $package 'BUILD_MANIFEST.json') -Encoding UTF8
& (Join-Path $package 'install.ps1') -GameRoot $game
foreach ($m in $modules) { if ((Get-FileHash -Algorithm SHA256 (Join-Path $destination $m.name)).Hash.ToLowerInvariant() -ne $m.sha256) { throw 'Installed hash mismatch' } }
& (Join-Path $package 'restore.ps1')
if ([IO.File]::ReadAllText((Join-Path $destination 'xrEngine.exe')) -ne 'original engine') { throw 'Engine was not restored' }
if ([IO.File]::ReadAllText((Join-Path $destination 'xrGame.dll')) -ne 'original game') { throw 'Game was not restored' }
if (Test-Path (Join-Path $destination 'extra.dll')) { throw 'Added module was not removed' }
# A corrupt package must be rejected before any installed byte changes.
[IO.File]::WriteAllText((Join-Path $payload 'xrGame.dll'),'corrupted')
$rejected=$false
try { & (Join-Path $package 'install.ps1') -GameRoot $game } catch { $rejected=$true }
if (-not $rejected) { throw 'Corrupt package accepted' }
if ([IO.File]::ReadAllText((Join-Path $destination 'xrEngine.exe')) -ne 'original engine') { throw 'Failed preflight changed installed files' }
Write-Host 'Installer/rollback fixture passed: original bytes restored, new module removed, corrupt package rejected before writes.'
Remove-Item -LiteralPath $testRoot -Recurse -Force
