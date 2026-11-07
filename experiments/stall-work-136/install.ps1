param([string]$GameRoot='C:\GOG Games\S.T.A.L.K.E.R. Call of Pripyat',[string]$BinDirectory)
. (Join-Path $PSScriptRoot 'installation_common.ps1')
Write-Host 'IX-Ray: checking package and destination...'
Check-GameClosed
$manifest=Get-Content (Join-Path $PSScriptRoot 'BUILD_MANIFEST.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $BinDirectory) {
  $candidates=@('', 'bin', 'bin_x64', 'bin\x64', 'bin\Win64') | ForEach-Object { Join-Path $GameRoot $_ } | Where-Object { Test-Path (Join-Path $_ 'xrEngine.exe') } | Select-Object -Unique
  if (@($candidates).Count -eq 1) { $BinDirectory=@($candidates)[0] } else { $BinDirectory=Read-Host 'Folder containing the currently used xrEngine.exe' }
}
$BinDirectory=(Resolve-Path -LiteralPath $BinDirectory).Path;$GameRoot=(Resolve-Path -LiteralPath $GameRoot).Path
if (-not (Test-Path (Join-Path $BinDirectory 'xrEngine.exe'))) { throw 'xrEngine.exe was not found.' }
foreach ($m in $manifest.modules) {
  if ([IO.Path]::GetFileName($m.name) -ne $m.name) { throw 'Invalid module name in manifest.' }
  if ((Hash (Join-Path (Join-Path $PSScriptRoot 'bin') $m.name)) -ne $m.sha256) { throw "Package checksum mismatch: $($m.name)" }
}
$lock=Open-InstallLock $GameRoot $BinDirectory
try {
  Check-GameClosed;$state=$null
  if (Test-Path -LiteralPath $script:centralState) { $state=Get-Content -LiteralPath $script:centralState -Raw -Encoding UTF8 | ConvertFrom-Json }
  else {
    $old=@(Get-ChildItem (Join-Path $GameRoot '_ixray_stallwork_backup') -Directory | Sort-Object Name | ForEach-Object {
      $path=Join-Path $_.FullName 'installation.json'
      if (Test-Path -LiteralPath $path) { $s=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json; if ($s.bin -eq $BinDirectory) { $s } }
    })
    if ($old.Count) { $state=$old[0];Check-Backup $state;Write-Host "Preserving earliest backup: $($state.backup)" }
  }
  $stamp=(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+[guid]::NewGuid().ToString('N')
  if (-not $state) {
    $backup=Join-Path $GameRoot ('_ixray_stallwork_backup\'+$stamp)
    $snapshot=Snapshot-Current ([PSCustomObject]@{bin=$BinDirectory;modules=$manifest.modules}) $backup
    $state=[PSCustomObject]@{bin=$BinDirectory;game_root=$GameRoot;backup=$backup;modules=$snapshot.modules}
    Write-State $state (Join-Path $backup 'installation.json')
  }
  Check-Backup $state
  if ($state.bin -ne $BinDirectory) { throw 'Backup destination mismatch.' }
  foreach ($m in $manifest.modules) {
    if (-not @($state.modules | Where-Object { $_.name -eq $m.name }).Count) {
      $target=Join-Path $BinDirectory $m.name;$exists=Test-Path -LiteralPath $target;$hash=$null
      if ($exists) {
        $hash=Hash $target;Copy-Item -LiteralPath $target -Destination (Join-Path $state.backup $m.name)
        if ((Hash (Join-Path $state.backup $m.name)) -ne $hash) { throw 'New module backup mismatch.' }
      }
      $state.modules += [PSCustomObject]@{name=$m.name;existed=$exists;old_sha256=$hash}
    }
    $r=@($state.modules | Where-Object { $_.name -eq $m.name })[0]
    $accepted=@($r.accepted_sha256)+@($r.new_sha256)+@($m.sha256)
    $r | Add-Member -Force NoteProperty accepted_sha256 @($accepted | Where-Object { $_ } | Select-Object -Unique)
  }
  $state | Add-Member -Force NoteProperty central_state $script:centralState
  $state | Add-Member -Force NoteProperty commit $manifest.commit
  $state | Add-Member -Force NoteProperty schema 2
  Write-State $state $script:centralState
  Write-State $state (Join-Path $PSScriptRoot 'installation.json')
  $tx=Snapshot-Current $state (Join-Path $GameRoot ('_ixray_stallwork_backup\transaction_'+$stamp))
  try {
    $i=0
    foreach ($m in $manifest.modules) {
      ++$i;Write-Host "[$i/$(@($manifest.modules).Count)] Install $($m.name)"
      $target=Join-Path $BinDirectory $m.name
      Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'bin') $m.name) -Destination $target -Force
      if ((Hash $target) -ne $m.sha256) { throw "Installation checksum failed: $($m.name)" }
    }
  } catch { $failure=$_;Write-Host 'Installation failed; rolling back this attempt...';Restore-Records $tx;throw $failure }
  Write-Host "Installed and verified $(@($manifest.modules).Count) matching Release modules."
  Write-Host "Original backup remains: $($state.backup)"
} finally { $lock.Dispose() }
