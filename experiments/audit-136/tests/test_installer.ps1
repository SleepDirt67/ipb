$ErrorActionPreference='Stop'
$testRoot=Join-Path $env:RUNNER_TEMP ('ixray_audit_install_'+[guid]::NewGuid().ToString('N'))
$game=Join-Path $testRoot ('game_'+[char]0x0422+[char]0x0435+[char]0x0441+[char]0x0442);$dest=Join-Path $game 'bin';$p1=Join-Path $testRoot 'package1';$p2=Join-Path $testRoot 'package2'
$source=Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'stall-work-136'
New-Item -ItemType Directory -Path $dest,$p1,$p2 -Force | Out-Null
function Assert($v,$why) { if (-not $v) { throw $why } }
function Make-Package($path,$version) {
 New-Item -ItemType Directory -Path (Join-Path $path 'bin') -Force | Out-Null
 Copy-Item (Join-Path $source 'install.ps1'),(Join-Path $source 'restore.ps1'),(Join-Path $source 'installation_common.ps1') -Destination $path
 $modules=@()
 foreach ($name in @('xrEngine.exe','xrGame.dll','extra.dll')) {
  $file=Join-Path (Join-Path $path 'bin') $name;[IO.File]::WriteAllText($file,($version+' '+$name))
  $modules += [PSCustomObject]@{name=$name;sha256=(Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant()}
 }
 [PSCustomObject]@{commit=$version;modules=$modules} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $path 'BUILD_MANIFEST.json') -Encoding UTF8
}
function Original {
 Assert ([IO.File]::ReadAllText((Join-Path $dest 'xrEngine.exe')) -eq 'original engine') 'Original engine lost'
 Assert ([IO.File]::ReadAllText((Join-Path $dest 'xrGame.dll')) -eq 'original game') 'Original game lost'
 Assert (-not (Test-Path (Join-Path $dest 'extra.dll'))) 'Added DLL not removed'
}
[IO.File]::WriteAllText((Join-Path $dest 'xrEngine.exe'),'original engine');[IO.File]::WriteAllText((Join-Path $dest 'xrGame.dll'),'original game')
Make-Package $p1 'v1';Make-Package $p2 'v2'
& (Join-Path $p1 'install.ps1') -GameRoot $game -BinDirectory $dest
$first=Get-Content (Join-Path $p1 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$backup=$first.backup
& (Join-Path $p1 'install.ps1') -GameRoot $game -BinDirectory $dest
& (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest
$second=Get-Content (Join-Path $p2 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert ($backup -eq $second.backup) 'Repeated/new-folder install changed first backup'
& (Join-Path $p1 'restore.ps1');Original
& (Join-Path $p2 'restore.ps1');Original
# Installer copy failure after the first changed module: rollback restores bytes.
$stream=[IO.File]::Open((Join-Path $dest 'xrGame.dll'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
$failed=$false
try { & (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest } catch { $failed=$true } finally { $stream.Dispose() }
Assert $failed 'Locked target accepted';Original
& (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest
# Restore failure must recover the current installed version, not leave a mixture.
$stream=[IO.File]::Open((Join-Path $dest 'xrGame.dll'),[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
$failed=$false
try { & (Join-Path $p2 'restore.ps1') } catch { $failed=$true } finally { $stream.Dispose() }
Assert $failed 'Locked restore target accepted'
Assert ([IO.File]::ReadAllText((Join-Path $dest 'xrEngine.exe')) -eq 'v2 xrEngine.exe') 'Restore rollback left mixed engine'
& (Join-Path $p2 'restore.ps1');Original
# Checksum preflights before writes.
[IO.File]::WriteAllText((Join-Path $p2 'bin\xrGame.dll'),'corrupted')
$failed=$false;try { & (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest } catch { $failed=$true };Assert $failed 'Corrupt package accepted';Original
Make-Package $p2 'v2'
# Cross-process lock shared by two independently extracted archives.
. (Join-Path $p1 'installation_common.ps1')
$lock=Open-InstallLock $game $dest
try {
 $argsText='-NoProfile -ExecutionPolicy Bypass -File "'+(Join-Path $p2 'install.ps1')+'" -GameRoot "'+$game+'" -BinDirectory "'+$dest+'"'
 $child=Start-Process powershell.exe -ArgumentList $argsText -Wait -PassThru -RedirectStandardOutput (Join-Path $testRoot 'concurrent.out') -RedirectStandardError (Join-Path $testRoot 'concurrent.err')
 Assert ($child.ExitCode -ne 0) 'Concurrent install acquired lock'
} finally { $lock.Dispose() }
Original
# Migrate earliest legacy backup even if the package-local state points to a later one.
Remove-Item -LiteralPath $second.central_state
& (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest
$migrated=Get-Content (Join-Path $p2 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
Assert ($migrated.backup -eq $backup) 'Legacy migration did not preserve earliest backup'
& (Join-Path $p2 'restore.ps1');Original
# Backup corruption rejects restore before touching installed modules.
& (Join-Path $p2 'install.ps1') -GameRoot $game -BinDirectory $dest
[IO.File]::WriteAllText((Join-Path $backup 'xrGame.dll'),'bad backup')
$failed=$false;try { & (Join-Path $p2 'restore.ps1') } catch { $failed=$true };Assert $failed 'Corrupt backup accepted'
Assert ([IO.File]::ReadAllText((Join-Path $dest 'xrEngine.exe')) -eq 'v2 xrEngine.exe') 'Restore preflight changed engine'
Write-Host 'PASS: repeated/new-folder installs, first backup, idempotent restore, install/restore failure rollback, package/backup corruption, cross-process lock, legacy migration.'
Remove-Item -LiteralPath $testRoot -Recurse -Force
