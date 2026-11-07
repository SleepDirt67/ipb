. (Join-Path $PSScriptRoot 'installation_common.ps1')
Write-Host 'IX-Ray: checking the original backup...'
Check-GameClosed
$state=Read-Installation
$lock=Open-InstallLock $state.game_root $state.bin
try {
  Check-GameClosed
  if (Test-Path -LiteralPath $script:centralState) { $state=Get-Content -LiteralPath $script:centralState -Raw -Encoding UTF8 | ConvertFrom-Json }
  Check-Backup $state
  foreach ($r in $state.modules) {
    $target=Join-Path $state.bin $r.name
    if ((Test-Path -LiteralPath $target) -and ((Hash $target) -notin (@($r.accepted_sha256)+@($r.new_sha256)+@($r.old_sha256)))) { throw "File changed outside this installer: $($r.name). Restore stopped before writes." }
  }
  $tx=Snapshot-Current $state (Join-Path $state.game_root ('_ixray_stallwork_backup\restore_'+[guid]::NewGuid().ToString('N')))
  try { Restore-Records $state } catch { $failure=$_;Write-Host 'Restore failed; recovering the previous set...';Restore-Records $tx;throw $failure }
  Write-Host 'The FIRST original module set is restored and SHA256-verified.'
} finally { $lock.Dispose() }
