$ErrorActionPreference='Stop'
function Hash($p) { (Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant() }
function Check-GameClosed { if (Get-Process xrEngine -ErrorAction SilentlyContinue) { throw 'Exit the game first.' } }
function Open-InstallLock($root,$bin) {
  $folder=Join-Path $root '_ixray_stallwork_backup'
  New-Item -ItemType Directory -Path $folder -Force | Out-Null
  $sha=[Security.Cryptography.SHA256]::Create()
  try { $id=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($bin.TrimEnd('\').ToLowerInvariant())))).Replace('-','').Substring(0,24) } finally { $sha.Dispose() }
  $script:centralState=Join-Path $folder ('state_'+$id+'.json')
  try { return [IO.File]::Open((Join-Path $folder ('lock_'+$id)),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None) }
  catch { throw 'Another INSTALL or RESTORE is using this game folder. Wait for it to finish.' }
}
function Write-State($state,$path) {
  $temp=$path+'.'+[guid]::NewGuid().ToString('N')+'.tmp'
  try {
    [IO.File]::WriteAllText($temp,($state | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $path) { [IO.File]::Replace($temp,$path,($path+'.'+[guid]::NewGuid().ToString('N')+'.previous')) } else { [IO.File]::Move($temp,$path) }
  } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp } }
}
function Check-Backup($state) {
  foreach ($r in $state.modules) {
    if ([IO.Path]::GetFileName($r.name) -ne $r.name) { throw 'Invalid module name in backup.' }
    if ($r.existed -and ((Hash (Join-Path $state.backup $r.name)) -ne $r.old_sha256)) { throw "Backup checksum mismatch: $($r.name)" }
  }
}
function Snapshot-Current($state,$folder) {
  New-Item -ItemType Directory -Path $folder -Force | Out-Null
  $records=@()
  foreach ($r in $state.modules) {
    $target=Join-Path $state.bin $r.name;$exists=Test-Path -LiteralPath $target;$hash=$null
    if ($exists) {
      $hash=Hash $target;Copy-Item -LiteralPath $target -Destination (Join-Path $folder $r.name)
      if ((Hash (Join-Path $folder $r.name)) -ne $hash) { throw 'Transaction backup verification failed.' }
    }
    $records += [PSCustomObject]@{name=$r.name;existed=$exists;old_sha256=$hash}
  }
  return [PSCustomObject]@{bin=$state.bin;backup=$folder;modules=$records}
}
function Restore-Records($state) {
  $index=0
  foreach ($r in $state.modules) {
    ++$index;Write-Host "[$index/$(@($state.modules).Count)] Restore $($r.name)"
    $target=Join-Path $state.bin $r.name
    if ($r.existed) {
      if (-not ((Test-Path -LiteralPath $target) -and ((Hash $target) -eq $r.old_sha256))) { Copy-Item -LiteralPath (Join-Path $state.backup $r.name) -Destination $target -Force }
      if ((Hash $target) -ne $r.old_sha256) { throw "Restore verification failed: $($r.name)" }
    } elseif (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target }
  }
}
function Read-Installation {
  $local=Get-Content (Join-Path $PSScriptRoot 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($local.central_state -and (Test-Path -LiteralPath $local.central_state)) { return Get-Content -LiteralPath $local.central_state -Raw -Encoding UTF8 | ConvertFrom-Json }
  return $local
}
