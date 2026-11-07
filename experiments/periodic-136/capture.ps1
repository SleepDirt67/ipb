param([ValidateSet('Baseline','Light','Deep')][string]$Mode='Light',[string[]]$EngineArguments=@())
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'installation_common.ps1')
. (Join-Path $PSScriptRoot 'stop_presentmon.ps1')
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this capture CMD as Administrator (PresentMon/ETW need access).' }
$state=Read-Installation
Check-GameClosed
$manifest=Get-Content (Join-Path $PSScriptRoot 'BUILD_MANIFEST.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($m in $manifest.modules) { if ((Hash (Join-Path $state.bin $m.name)) -ne $m.sha256) { throw 'Install the complete pacing package before capture; installed module hashes differ.' } }
$pm=Join-Path $PSScriptRoot 'capture-tools/PresentMon-2.6.0-x64.exe'
if ((Hash $pm) -ne 'b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af') { throw 'PresentMon checksum mismatch.' }
$directory=Join-Path $PSScriptRoot ('captures/'+(Get-Date -Format 'yyyyMMdd_HHmmss_fff')+'_'+$Mode)
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$directory=(Resolve-Path -LiteralPath $directory).Path
$start=[DateTime]::UtcNow
$env:IXRAY_PACING=if ($Mode -eq 'Baseline') {'0'} else {'1'}
$env:IXRAY_PACING_DEEP=if ($Mode -eq 'Deep') {'1'} else {'0'}
$env:IXRAY_PACING_DIR=$directory
$env:IXRAY_TRACE_FRAME_STALLS=if ($Mode -eq 'Deep') {'1'} else {'0'}
$env:IXRAY_TRACE_ALL_FRAMES=$env:IXRAY_TRACE_FRAME_STALLS
$env:IXRAY_TRACE_HUMAN_LOG='0'
$wprStarted=$false;$present=$null;$marker=$null;$game=$null
try {
  if ($Mode -eq 'Deep') {
    & wpr.exe -start GeneralProfile -start GPU -start ((Join-Path $PSScriptRoot 'IXRayPacing.wprp')+'!IXRayPacing') 2>&1 | Out-File (Join-Path $directory 'wpr_start.txt') -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { throw 'WPR start failed. See wpr_start.txt. Existing sessions were not cancelled.' }
    $wprStarted=$true
  }
  $params=@{FilePath=(Join-Path $state.bin 'xrEngine.exe');WorkingDirectory=$state.game_root;PassThru=$true}
  if ($EngineArguments.Count) { $params.ArgumentList=$EngineArguments }
  $game=Start-Process @params
  $markerArgs='"'+(Join-Path $directory 'markers.csv')+'" '+$game.Id
  $marker=Start-Process -FilePath (Join-Path $PSScriptRoot 'capture-tools/ixray_pacing_marks.exe') -ArgumentList $markerArgs -PassThru
  $sessionName='IXRayPacing_'+$game.Id+'_'+[guid]::NewGuid().ToString('N')
  $pmArgs='--process_id '+$game.Id+' --qpc_time --write_display_metadata --no_console_stats --terminate_on_proc_exit --session_name '+$sessionName+' --output_file "'+(Join-Path $directory 'presentmon.csv')+'"'
  $present=Start-Process -FilePath $pm -ArgumentList $pmArgs -PassThru -RedirectStandardOutput (Join-Path $directory 'presentmon_stdout.txt') -RedirectStandardError (Join-Path $directory 'presentmon_stderr.txt')
  [PSCustomObject]@{mode=$Mode;pid=$game.Id;start_utc=$start.ToString('o');binary_commit=$manifest.commit;presentmon_arguments=$pmArgs;deep_etw=$wprStarted;trace_changes_timing=($Mode -ne 'Baseline')} | ConvertTo-Json | Set-Content (Join-Path $directory 'capture.json') -Encoding UTF8
  Write-Host "Capture: $directory"
  Write-Host 'Load the save, wait 15 seconds, and play for 60-90 seconds where the issue occurs.'
  Write-Host 'Recording runs continuously. No symptom hotkeys are needed. For camera sync in Light/Deep, use Win+F8 once before and once after the test. Exit normally to save.'
  $game.WaitForExit()
  Stop-PacingPresentMon $present $pm $sessionName $directory
  $presentCsv=Join-Path $directory 'presentmon.csv'
  if (-not (Test-Path -LiteralPath $presentCsv)) { throw 'PresentMon produced no CSV. This capture is invalid; keep its stdout/stderr for diagnosis.' }
  $presentLines=@(Get-Content -LiteralPath $presentCsv -TotalCount 2)
  if ($presentLines.Count -lt 2 -or $presentLines[0] -notmatch 'CPUStartQPC') { throw 'PresentMon has no frame rows or no raw QPC column; this capture is invalid.' }

  if (-not $marker.WaitForExit(5000)) { Write-Host 'Use Win+F12 to stop and save the marker helper.' }
  elseif ($marker.ExitCode -ne 0) { throw 'Marker helper failed (possibly reserved Win hotkeys). Keep its console error and the capture folder.' }
} finally {
  if ($wprStarted) {
    Write-Host 'Saving raw CPU/GPU ETL...'
    & wpr.exe -stop (Join-Path $directory 'engine_cpu_gpu.etl') 'IXRay periodic pacing diagnostic' 2>&1 | Out-File (Join-Path $directory 'wpr_stop.txt') -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { Write-Warning 'WPR save failed. Keep wpr_stop.txt; do not substitute aggregate tables for the raw trace.' }
  }
  Copy-Item (Join-Path $PSScriptRoot 'BUILD_MANIFEST.json') $directory
  foreach ($relative in @('_appdata_/logs','appdata/logs','logs')) {
    $logs=Join-Path $state.game_root $relative
    if (Test-Path -LiteralPath $logs) {
      Get-ChildItem -LiteralPath $logs -File | Where-Object { $_.LastWriteTimeUtc -ge $start -and ($_.Extension -eq '.log' -or $_.Name -like 'ixray_frames_*.csv') } | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $directory }
    }
  }
  Write-Host "Capture files: $directory. Keep the complete directory and optional camera video."
}
