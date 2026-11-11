# The backup here is the exact pre-capture state. It shares the installer's lock.
function Write-BinderJournal($Journal, [string]$Path) {
    $temporary = "$Path.new"
    $data = [Text.UTF8Encoding]::new($false).GetBytes(($Journal | ConvertTo-Json -Depth 8))
    $stream = [IO.File]::Open($temporary, 'Create', 'Write', 'None')
    try { $stream.Write($data, 0, $data.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    if ([IO.File]::Exists($Path)) { [IO.File]::Replace($temporary, $Path, $null) }
    else { [IO.File]::Move($temporary, $Path) }
}

function Set-BinderBinary([string]$Source, [string]$Target, [string]$Digest) {
    $staged = "$Target.ixbinder-stage"
    $inputStream = [IO.File]::OpenRead($Source)
    try {
        $out = [IO.File]::Open($staged, 'Create', 'Write', 'None')
        try { $inputStream.CopyTo($out); $out.Flush($true) } finally { $out.Dispose() }
    } finally { $inputStream.Dispose() }
    if ((Hash $staged) -ne $Digest) { throw 'Staged file checksum mismatch.' }
    if ([IO.File]::Exists($Target)) { [IO.File]::Replace($staged, $Target, $null) }
    else { [IO.File]::Move($staged, $Target) }
    if ((Hash $Target) -ne $Digest) { throw 'Installed file checksum mismatch.' }
}

function New-BinderTransaction($Installation, $Manifest, [string]$Root, [string]$Path,
                               [string]$SaveAlias, [string]$SaveHash) {
    $snapshot = Snapshot-Current $Installation (Join-Path $Root 'original')
    $expected = @{}
    foreach ($module in $Manifest.modules) { $expected[$module.name] = $module.sha256 }
    foreach ($record in $snapshot.modules) {
        if (-not $expected.ContainsKey($record.name)) { throw 'Unexpected module in capture transaction.' }
        $record | Add-Member NoteProperty diagnostic_sha256 $expected[$record.name]
    }
    $journal = [pscustomobject]@{
        schema=1; modules=$snapshot.modules; bin=$snapshot.bin; backup=$snapshot.backup
        save_alias=$SaveAlias; save_sha256=$SaveHash; pid=0; process_start=0
    }
    Write-BinderJournal $journal $Path
    return $journal
}

function Restore-BinderTransaction($Journal, [string]$Path, [string]$Bin, [string]$SaveDirectory) {
    if ($Journal.schema -ne 1 -or $Journal.bin -ne $Bin) { throw 'Transaction journal does not match this installation.' }
    if ($Journal.pid) {
        $owner = Get-Process -Id $Journal.pid -ErrorAction SilentlyContinue
        if ($owner -and $owner.StartTime.ToUniversalTime().Ticks -eq $Journal.process_start) {
            throw 'The diagnostic game process is still running.'
        }
    }
    Check-GameClosed
    $parent = [IO.Path]::GetDirectoryName($Path)
    if ($Journal.backup -ne (Join-Path $parent 'original')) { throw 'Unexpected transaction backup directory.' }
    Check-Backup $Journal
    foreach ($record in $Journal.modules) {
        if ($record.name -notmatch '^[A-Za-z0-9_.-]+\.(dll|exe)$') { throw 'Unexpected module name in recovery.' }
        $target = Join-Path $Bin $record.name
        $actual = if ([IO.File]::Exists($target)) { Hash $target } else { $null }
        if ($actual -ne $record.old_sha256) {
            if ($actual -and $actual -ne $record.diagnostic_sha256) {
                throw "File changed outside the capture transaction: $($record.name)"
            }
            if ($record.existed) {
                Set-BinderBinary (Join-Path $Journal.backup $record.name) $target $record.old_sha256
            } elseif ($actual) {
                [IO.File]::Delete($target)
            }
        }
        $restored = if ([IO.File]::Exists($target)) { Hash $target } else { $null }
        if ($restored -ne $record.old_sha256) { throw "Restoration checksum mismatch: $($record.name)" }
        [IO.File]::Delete("$target.ixbinder-stage")
    }
    if ($Journal.save_alias -and $SaveDirectory) {
        $alias = Split-Path -Leaf $Journal.save_alias
        if ($alias -notmatch '^ixbinder_[0-9a-f]{24}\.scop$' -or $Journal.save_alias -ne (Join-Path $SaveDirectory $alias)) {
            throw 'Unexpected temporary save path in recovery.'
        }
        if ([IO.File]::Exists($Journal.save_alias)) {
            if ((Hash $Journal.save_alias) -ne $Journal.save_sha256) { throw 'Temporary save contents changed.' }
            [IO.File]::Delete($Journal.save_alias)
        }
        [IO.File]::Delete("$($Journal.save_alias).ixbinder-stage")
    }
    return [pscustomobject]@{
        restored=$true
        modules=@($Journal.modules | Select-Object name,existed,old_sha256,diagnostic_sha256)
    }
}
