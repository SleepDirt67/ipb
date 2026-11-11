$ErrorActionPreference = 'Stop'
. (Resolve-Path package/installation_common.ps1)
. (Resolve-Path ci/binder-capture/capture/binder_transaction.ps1)
$cyrillic = -join [char[]]@(0x41f,0x440,0x43e,0x431,0x435,0x43b)
$root = Join-Path (Resolve-Path checks).Path "$cyrillic Binder Transaction"
$bin = Join-Path $root 'bin'
$saves = Join-Path $root 'save files'
$tx = Join-Path $root 'transaction'
$journalPath = Join-Path $tx 'journal.json'
New-Item -ItemType Directory -Path $bin,$saves,$tx -Force | Out-Null
$old = Join-Path $bin 'xrGame.dll'
$added = Join-Path $bin 'lua51.dll'
$save = Join-Path $saves "$cyrillic original [1].scop"
$alias = Join-Path $saves 'ixbinder_0123456789abcdef01234567.scop'
$diagnostic = (Resolve-Path package/bin/xrGame.dll).Path
$lua = (Resolve-Path package/bin/lua51.dll).Path
[IO.File]::WriteAllText($old, 'original bytes')
[IO.File]::WriteAllText($save, 'private fixture bytes')
$oldHash = Hash $old
$saveHash = Hash $save
$manifest = [pscustomobject]@{ modules=@(
    [pscustomobject]@{name='xrGame.dll';sha256=(Hash $diagnostic)},
    [pscustomobject]@{name='lua51.dll';sha256=(Hash $lua)}
)}
$installation = [pscustomobject]@{bin=$bin;modules=$manifest.modules}
$journal = New-BinderTransaction $installation $manifest $tx $journalPath $alias $saveHash
Set-BinderBinary $save $alias $saveHash
Set-BinderBinary $diagnostic $old $manifest.modules[0].sha256
Set-BinderBinary $lua $added $manifest.modules[1].sha256
$journal.pid = $PID
$journal.process_start = (Get-Process -Id $PID).StartTime.ToUniversalTime().Ticks
Write-BinderJournal $journal $journalPath
$blocked = $false
try { $null = Restore-BinderTransaction $journal $journalPath $bin $saves } catch { $blocked = $true }
if (-not $blocked) { throw 'Recovery accepted a live matching process.' }
$journal.process_start--
Write-BinderJournal $journal $journalPath
$pending = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
$receipt = Restore-BinderTransaction $pending $journalPath $bin $saves
if (-not $receipt.restored -or (Hash $old) -ne $oldHash -or (Hash $save) -ne $saveHash -or
    (Test-Path -LiteralPath $alias) -or (Test-Path -LiteralPath $added)) {
    throw 'Interrupted transaction did not restore exact bytes.'
}
Write-Host 'Verified binary rollback, file removal, private save alias and PID reuse in a Cyrillic path.'
