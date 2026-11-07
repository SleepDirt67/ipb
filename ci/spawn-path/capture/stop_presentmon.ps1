function Stop-PacingPresentMon($Process,[string]$Executable,[string]$SessionName,[string]$Directory) {
  if (-not $Process.WaitForExit(3000)) {
    Write-Host 'Saving PresentMon: stopping this capture session and flushing CSV...'
    $stop=Start-Process -FilePath $Executable -ArgumentList ('--session_name '+$SessionName+' --terminate_existing_session') -Wait -PassThru -RedirectStandardOutput (Join-Path $Directory 'presentmon_stop_stdout.txt') -RedirectStandardError (Join-Path $Directory 'presentmon_stop_stderr.txt')
    Write-Host "PresentMon stop-session exit=$($stop.ExitCode)"
  }
  if (-not $Process.WaitForExit(15000)) { throw 'PresentMon did not finish flushing this session; keep the complete capture directory.' }
  if ($Process.ExitCode -ne 0) { throw "PresentMon exit=$($Process.ExitCode); see its stdout/stderr and stop-session logs." }
}
