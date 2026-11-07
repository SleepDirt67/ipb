param([ValidateSet('Performance','Trace')][string]$Mode='Trace',[string[]]$EngineArguments=@())
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'installation_common.ps1')
$state=Read-Installation
$flag=if ($Mode -eq 'Trace') {'1'} else {'0'}
$env:IXRAY_TRACE_FRAME_STALLS=$flag
$env:IXRAY_TRACE_ALL_FRAMES=$flag
$env:IXRAY_TRACE_HUMAN_LOG='0'
$env:IXRAY_PACING='0'
$env:IXRAY_PACING_DEEP='0'
$params=@{FilePath=(Join-Path $state.bin 'xrEngine.exe');WorkingDirectory=$state.game_root;Wait=$true}
if ($EngineArguments.Count) { $params.ArgumentList=$EngineArguments }
Start-Process @params
