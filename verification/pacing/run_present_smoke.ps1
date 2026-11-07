param([string]$PresentMon,[string]$Marker,[string]$Fixture,[string]$Output)
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force $Output | Out-Null
$directory=(Resolve-Path $Output).Path
$fixtureProcess=Start-Process -FilePath (Resolve-Path $Fixture).Path -ArgumentList ('"'+$directory+'"') -PassThru -RedirectStandardOutput (Join-Path $directory 'fixture_stdout.txt') -RedirectStandardError (Join-Path $directory 'fixture_stderr.txt')
$watch=[Diagnostics.Stopwatch]::StartNew()
while (-not (Test-Path (Join-Path $directory 'ready.txt'))) {
  if ($fixtureProcess.HasExited -or $watch.Elapsed.TotalSeconds -gt 15) { throw 'DXGI fixture did not become ready; inspect fixture stdout/stderr.' }
  Start-Sleep -Milliseconds 50
}
$sessionName='IXRayPacingSmoke_'+$fixtureProcess.Id
# Hosted WARP CI has no physical display. Validate the CPU/QPC boundary here;
# user capture.ps1 deliberately retains full GPU/display tracking.
$pmArguments='--process_id '+$fixtureProcess.Id+' --qpc_time --no_track_display --no_track_gpu --no_track_input --no_console_stats --terminate_on_proc_exit --session_name '+$sessionName+' --output_file "'+(Join-Path $directory 'presentmon.csv')+'"'
$presentProcess=Start-Process -FilePath (Resolve-Path $PresentMon).Path -ArgumentList $pmArguments -PassThru -RedirectStandardOutput (Join-Path $directory 'pm_stdout.txt') -RedirectStandardError (Join-Path $directory 'pm_stderr.txt')
$markerProcess=Start-Process -FilePath (Resolve-Path $Marker).Path -ArgumentList ('"'+(Join-Path $directory 'markers.csv')+'" '+$fixtureProcess.Id) -PassThru -RedirectStandardOutput (Join-Path $directory 'marker_stdout.txt') -RedirectStandardError (Join-Path $directory 'marker_stderr.txt')
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class PacingSmokeMessage {
 [DllImport("user32.dll",SetLastError=true)]
 public static extern bool PostThreadMessage(uint threadId,uint message,UIntPtr wParam,IntPtr lParam);
}
'@
Start-Sleep -Milliseconds 400
if ($markerProcess.HasExited) { throw ('Marker registration failed: '+(Get-Content (Join-Path $directory 'marker_stderr.txt') -Raw)) }
$markerProcess.Refresh();$threadId=$markerProcess.Threads[0].Id
# Exercise the real registered helper/message path without injecting keyboard input.
foreach ($id in 100..104) {
  if (-not [PacingSmokeMessage]::PostThreadMessage([uint32]$threadId,0x0312,[UIntPtr]$id,[IntPtr]::Zero)) { throw 'Cannot post controlled marker message.' }
}
if (-not $markerProcess.WaitForExit(5000) -or $markerProcess.ExitCode -ne 0) { throw 'Marker helper did not save its controlled messages.' }
if (-not $fixtureProcess.WaitForExit(30000) -or $fixtureProcess.ExitCode -ne 0) { throw ('DXGI/square fixture failed: '+(Get-Content (Join-Path $directory 'fixture_stdout.txt') -Raw)) }
. (Join-Path $PSScriptRoot '../../experiments/periodic-136/stop_presentmon.ps1')
Stop-PacingPresentMon $presentProcess (Resolve-Path $PresentMon).Path $sessionName $directory
Get-Content (Join-Path $directory 'presentmon.csv') -TotalCount 3
Get-Content (Join-Path $directory 'fixture_stdout.txt')
