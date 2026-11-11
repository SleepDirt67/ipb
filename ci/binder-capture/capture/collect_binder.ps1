param([string]$Profile = (Join-Path $PSScriptRoot 'binder_profile.json'))
$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Profile "' + $Profile + '"'
    $elevated = Start-Process -FilePath "$PSHOME\powershell.exe" -ArgumentList $arguments -Verb RunAs -Wait -PassThru
    exit $elevated.ExitCode
}
. (Join-Path $PSScriptRoot 'installation_common.ps1')
. (Join-Path $PSScriptRoot 'binder_transaction.ps1')
. (Join-Path $PSScriptRoot 'stop_presentmon.ps1')

function Save-Directory([string]$Root) {
    $entries = @{'$fs_root$'=$Root}
    foreach ($line in [IO.File]::ReadAllLines((Join-Path $Root 'fsgame.ltx'), [Text.Encoding]::Default)) {
        if ($line -notmatch '^\s*(\$[^$]+\$)\s*=\s*(.*)$') { continue }
        $key = $Matches[1]
        $fields = @($Matches[2] -split '\|' | ForEach-Object { $_.Trim() })
        if ($fields.Count -lt 3) { continue }
        $value = [Environment]::ExpandEnvironmentVariables($fields[2])
        if ($value.StartsWith('$')) {
            if (-not $entries.ContainsKey($value)) { continue }
            $value = $entries[$value]
        } elseif (-not [IO.Path]::IsPathRooted($value)) {
            $value = Join-Path $Root $value
        }
        if ($fields.Count -ge 4 -and $fields[3]) { $value = Join-Path $value $fields[3] }
        $entries[$key] = [IO.Path]::GetFullPath($value).TrimEnd('\')
    }
    if (-not $entries.ContainsKey('$game_saves$')) { throw 'Cannot resolve $game_saves$ in fsgame.ltx.' }
    return $entries['$game_saves$']
}

function Find-Installation($ProfileData, $Manifest) {
    $roots = @()
    $old = $null
    if ($ProfileData.game_root) { $roots += $ProfileData.game_root }
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'installation.json')) {
        $old = Read-Installation
        $roots += $old.game_root
    }
    $roots += (Get-Location).Path, $PSScriptRoot, (Split-Path -Parent $PSScriptRoot)
    foreach ($key in @('HKLM:\SOFTWARE\WOW6432Node\GOG.com\Games', 'HKLM:\SOFTWARE\GOG.com\Games')) {
        foreach ($property in @(Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue | Get-ItemProperty)) {
            if ($property.gameName -match 'S\.?T\.?A\.?L\.?K\.?E\.?R\.?[.: -]+Call of Pripyat' -and $property.path) {
                $roots += $property.path
            }
        }
    }
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall')) {
        foreach ($property in @(Get-ChildItem -LiteralPath $key -ErrorAction SilentlyContinue | Get-ItemProperty)) {
            if ($property.DisplayName -match 'S\.?T\.?A\.?L\.?K\.?E\.?R\.?[.: -]+Call of Pripyat' -and $property.InstallLocation) {
                $roots += $property.InstallLocation
            }
        }
    }
    $choices = @()
    foreach ($root in @($roots | Where-Object { $_ } | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath (Join-Path $root 'fsgame.ltx') -PathType Leaf)) { continue }
        $root = [IO.Path]::GetFullPath($root).TrimEnd('\')
        $dirs = @($root)
        $dirs += @('bin','bin_x64','bin\x64','bin\Win64') | ForEach-Object { Join-Path $root $_ }
        if ($old -and $old.game_root -eq $root) { $dirs = @($old.bin) }
        if ($ProfileData.bin -and $ProfileData.game_root -eq $root) { $dirs = @($ProfileData.bin) }
        $dirs = @($dirs | Where-Object {
            (Test-Path -LiteralPath (Join-Path $_ 'xrEngine.exe')) -and
            (Test-Path -LiteralPath (Join-Path $_ 'xrGame.dll'))
        } | Select-Object -Unique)
        if ($dirs.Count -ne 1) { continue }
        $saves = Save-Directory $root
        if (-not (Test-Path -LiteralPath $saves -PathType Container)) { continue }
        $pinned = @(Get-ChildItem -LiteralPath $saves -File -Filter '*.scop' |
            Where-Object { $_.Name -notmatch '^ixbinder_' -and (Hash $_.FullName) -eq $ProfileData.save_sha256 })
        if ($pinned.Count) {
            $choices += [pscustomobject]@{
                game_root=$root; bin=[IO.Path]::GetFullPath($dirs[0]).TrimEnd('\')
                save_directory=$saves; save=($pinned | Sort-Object Name | Select-Object -First 1).FullName
                modules=$Manifest.modules
            }
        }
    }
    $choices = @($choices | Sort-Object bin -Unique)
    if ($choices.Count -ne 1) { throw 'The verified save and a unique IX-Ray installation could not be located.' }
    return $choices[0]
}

function Check-BinderPackage($Manifest) {
    if ($Manifest.binder_capture.schema -ne 4 -or
        $Manifest.binder_capture.base -ne '886337084c8fd851a4fff186b453ae7cc6450821') {
        throw 'Unexpected diagnostic package.'
    }
    $seal = Join-Path $PSScriptRoot 'SHA256SUMS.txt'
    $names = @{}
    foreach ($line in [IO.File]::ReadLines($seal)) {
        if ($line -notmatch '^([a-f0-9]{64})  ([^\\:]+)$') { throw 'Invalid package checksum entry.' }
        $expected = $Matches[1]
        $relative = $Matches[2]
        if ($relative.Split('/') -contains '..' -or $relative.StartsWith('/') -or $names.ContainsKey($relative)) {
            throw 'Unsafe or repeated package checksum path.'
        }
        $names[$relative] = $true
        if ((Hash (Join-Path $PSScriptRoot $relative)) -ne $expected) { throw "Package checksum mismatch: $relative" }
    }
    foreach ($module in $Manifest.modules) {
        if ($module.name -notmatch '^[A-Za-z0-9_.-]+\.(dll|exe)$' -or -not $names.ContainsKey("bin/$($module.name)") -or
            (Hash (Join-Path $PSScriptRoot "bin/$($module.name)")) -ne $module.sha256) {
            throw 'Invalid or mismatched module manifest.'
        }
    }
    foreach ($file in @('BUILD_MANIFEST.json','collect_binder.ps1','binder_transaction.ps1','analyze_binder.py',
                        'IXRayBinderCpu.wprp','instrumentation_map.json','capture-tools/binder_capture_runtime_test.exe',
                        'capture-tools/lua51.dll','capture-tools/PresentMon-2.6.0-x64.exe','capture-tools/ixray_etw_decode.exe')) {
        if (-not $names.ContainsKey($file)) { throw "Unsealed required file: $file" }
    }
}

function Start-BinderPresent([string]$PresentMon, [string]$Decoder, [string]$Session, [string]$Output) {
    $arguments = '--process_name xrEngine.exe --qpc_time --write_display_metadata --no_track_input --no_console_stats' +
        ' --session_name ' + $Session + ' --output_file "' + (Join-Path $Output 'presentmon.csv') + '"'
    $options = @{
        FilePath=$PresentMon; ArgumentList=$arguments; PassThru=$true
        RedirectStandardOutput=(Join-Path $Output 'presentmon_stdout.txt')
        RedirectStandardError=(Join-Path $Output 'presentmon_stderr.txt')
    }
    $process = Start-Process @options
    $null = $process.Handle
    $timer = [Diagnostics.Stopwatch]::StartNew()
    try {
        do {
            if ($process.HasExited) { throw "PresentMon exited before game start ($($process.ExitCode))." }
            & $Decoder --session-active $Session
            if ($LASTEXITCODE -eq 0) { return $process }
            Start-Sleep -Milliseconds 100
        } while ($timer.Elapsed.TotalSeconds -lt 10)
        throw 'PresentMon ETW session did not become ready.'
    } catch {
        Stop-PacingPresentMon $process $PresentMon $Session $Output
        throw
    }
}

function Save-Modules($Process, $Manifest, [string]$Bin, [string]$Output) {
    $Process.Refresh()
    $images = @($Process.Modules)
    $mandatory = @('xrEngine.exe','xrGame.dll','xrAbstractions.dll','xrScripts.dll','lua51.dll','xrRender_R4.dll')
    if (@($mandatory | Where-Object { $_ -notin $images.ModuleName }).Count) { return $false }
    $expected = @{}
    foreach ($module in $Manifest.modules) { $expected[$module.name] = $module.sha256 }
    $images | ForEach-Object {
        $name = $_.ModuleName
        $digest = $null
        if ($expected.ContainsKey($name)) {
            $digest = Hash $_.FileName
            if ($digest -ne $expected[$name] -or $_.FileName -ne (Join-Path $Bin $name)) {
                throw "Unexpected loaded module: $name"
            }
        }
        [pscustomobject]@{
            name=$name; base_hex=$_.BaseAddress.ToInt64().ToString('x'); size=$_.ModuleMemorySize; sha256=$digest
        }
    } | Export-Csv -NoTypeInformation -Encoding UTF8 -LiteralPath (Join-Path $Output 'module_snapshot.csv')
    return $true
}

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'BUILD_MANIFEST.json') -Encoding UTF8 -Raw | ConvertFrom-Json
$profileData = Get-Content -LiteralPath $Profile -Encoding UTF8 -Raw | ConvertFrom-Json
if ($profileData.save_sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Missing SHA-256 of the approved save.' }
Check-BinderPackage $manifest
$install = Find-Installation $profileData $manifest
$tools = Join-Path $PSScriptRoot 'capture-tools'
$python = Join-Path $tools 'python\python.exe'
$pm = Join-Path $tools 'PresentMon-2.6.0-x64.exe'
$decoder = Join-Path $tools 'ixray_etw_decode.exe'
$probe = Join-Path $tools 'binder_capture_runtime_test.exe'
$wpr = Join-Path $env:SystemRoot 'System32\wpr.exe'
$wprp = Join-Path $PSScriptRoot 'IXRayBinderCpu.wprp'
foreach ($file in @($python, $pm, $decoder, $probe, $wpr, $wprp)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required capture file missing: $(Split-Path -Leaf $file)" }
}
foreach ($folder in @($PSScriptRoot, $install.game_root, $env:TEMP)) {
    $drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($folder))
    if ($drive.AvailableFreeSpace -lt 8GB) { throw 'Capture requires 8 GiB of free space on each recording volume.' }
}
Check-GameClosed
$lock = Open-InstallLock $install.game_root $install.bin
$txRoot = Join-Path (Split-Path -Parent $script:centralState) ([IO.Path]::GetFileNameWithoutExtension($script:centralState) + '_binder')
$journalPath = Join-Path $txRoot 'journal.json'
$session = 'IXRayBinder_' + [Guid]::NewGuid().ToString('N')
$id = $session.Substring($session.Length - 24).ToLowerInvariant()
$output = Join-Path $PSScriptRoot ("captures\" + (Get-Date -Format yyyyMMdd_HHmmss_fff) + "_Binder_$id")
$stopEventName = "Local\$session"
$stopEvent = $null
$alias = "ixbinder_$id"
$savePath = Join-Path $install.save_directory "$alias.scop"
$issues = [Collections.Generic.List[string]]::new()
$meta = [ordered]@{
    capture_id=$id; commit=$manifest.commit; qpc_frequency=[Diagnostics.Stopwatch]::Frequency
    save_sha256=$profileData.save_sha256; startup_verified=$false; modules_verified=$false
    start_utc=[DateTime]::UtcNow.ToString('o'); issues=$issues; observer='UNVERIFIED_ON_TARGET'
}
$game = $null
$present = $null
$journal = $null
$wprStarted = $false
$rolledBack = $false

function Stop-BinderRecording {
    if ($script:wprStarted) {
        try {
            & $wpr -stop (Join-Path $output 'cpu_scheduling.etl') 'IX-Ray binder capture' -skipPdbGen -instancename $session *> (Join-Path $output 'wpr_stop.txt')
            if ($LASTEXITCODE -ne 0) { throw "WPR stop returned $LASTEXITCODE" }
        } catch {
            $issues.Add("CPU ETW stop failed: $_")
            & $wpr -cancel -instancename $session *> (Join-Path $output 'wpr_cancel.txt')
        } finally { $script:wprStarted = $false }
    }
    if ($script:present) {
        try { Stop-PacingPresentMon $script:present $pm $session $output }
        catch { $issues.Add("PresentMon stop failed: $_") }
        finally { $script:present = $null }
    }
}

try {
    if ([IO.File]::Exists($journalPath)) {
        $pending = Get-Content -LiteralPath $journalPath -Encoding UTF8 -Raw | ConvertFrom-Json
        if ($pending.session -match '^IXRayBinder_[0-9a-f]{32}$') {
            # A terminated launcher may leave system and PresentMon sessions running.
            & $wpr -cancel -instancename $pending.session 2>$null | Out-Null
            & $pm --session_name $pending.session --terminate_existing_session 2>$null | Out-Null
        }
        $null = Restore-BinderTransaction $pending $journalPath $install.bin $install.save_directory
        Remove-Item -LiteralPath $txRoot -Recurse -Force
    } elseif (Test-Path -LiteralPath $txRoot) {
        Remove-Item -LiteralPath $txRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $output,$txRoot -Force | Out-Null
    $meta.profile_sha256 = Hash $wprp
    $meta.presentmon_sha256 = Hash $pm
    $meta.etw_decoder_sha256 = Hash $decoder
    $meta.analyzer_sha256 = Hash (Join-Path $PSScriptRoot 'analyze_binder.py')
    foreach ($file in @('BUILD_MANIFEST.json', 'instrumentation_map.json')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination $output
    }
    Copy-Item -LiteralPath (Join-Path $tools 'stack-symbols\INDEX_MANIFEST.json') -Destination (Join-Path $output 'symbol_identity.json')

    # Check real LuaJIT marks, QPC accounting, error recovery and allocator counters.
    & $probe *> (Join-Path $output 'runtime_preflight.txt')
    if ($LASTEXITCODE -ne 0) { throw "Diagnostic LuaJIT preflight failed ($LASTEXITCODE)." }
    $calibration = & $probe --calibrate
    if ($LASTEXITCODE -ne 0 -or @($calibration).Count -ne 9) { throw 'QPC calibration failed.' }
    $calibration | Set-Content -LiteralPath (Join-Path $output 'observer_calibration.txt') -Encoding ASCII
    & $wpr -profiles $wprp *> (Join-Path $output 'wpr_profiles.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Windows rejected the CPU scheduling profile.' }
    if ([IO.File]::Exists($savePath)) { throw 'Temporary save name collision.' }
    $journal = New-BinderTransaction $install $manifest $txRoot $journalPath $savePath $profileData.save_sha256
    $journal | Add-Member NoteProperty session $session
    Write-BinderJournal $journal $journalPath
    & $wpr -start "$wprp!IXRayBinderCpu" -filemode -instancename $session *> (Join-Path $output 'wpr_start.txt')
    if ($LASTEXITCODE -ne 0) { throw 'CPU scheduling ETW session could not start.' }
    $wprStarted = $true
    $present = Start-BinderPresent $pm $decoder $session $output
    $stopEvent = [Threading.EventWaitHandle]::new($false, 'ManualReset', $stopEventName)
    $meta.startup_verified = $true

    Set-BinderBinary $install.save $savePath $profileData.save_sha256
    foreach ($record in $journal.modules) {
        Set-BinderBinary (Join-Path $PSScriptRoot "bin/$($record.name)") (Join-Path $install.bin $record.name) $record.diagnostic_sha256
    }

    $env:IXRAY_BINDER_CAPTURE = '1'
    $env:IXRAY_BINDER_STOP_EVENT = $stopEventName
    $env:IXRAY_BINDER_SAVE_ALIAS = $alias
    $env:IXRAY_PACING = '1'
    $env:IXRAY_PACING_DIR = $output
    $env:IXRAY_SPAWN_PATH = '1'
    $env:IXRAY_SPAWN_LUA = '0'
    $env:IXRAY_PACING_DEEP = '0'
    $env:IXRAY_PACING_PIXELS = '0'
    $env:IXRAY_TRACE_FRAME_STALLS = '0'
    $env:IXRAY_TRACE_ALL_FRAMES = '0'
    $env:IXRAY_TRACE_HUMAN_LOG = '0'

    $meta.launch_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $options = @{
        FilePath=(Join-Path $install.bin 'xrEngine.exe'); WorkingDirectory=$install.game_root
        ArgumentList="-start server($alias/single/alife/load)"; PassThru=$true
    }
    $game = Start-Process @options
    $null = $game.Handle
    $meta.pid = $game.Id
    $journal.pid = $game.Id
    $journal.process_start = $game.StartTime.ToUniversalTime().Ticks
    Write-BinderJournal $journal $journalPath
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while (-not $game.HasExited -and $timer.Elapsed.TotalSeconds -lt 55) {
        if (Save-Modules $game $manifest $install.bin $output) {
            $meta.modules_verified = $true
            $meta.module_snapshot_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
            break
        }
        Start-Sleep -Milliseconds 400
    }
    if (-not $meta.modules_verified) { $issues.Add('The required game images did not load or could not be verified.') }
    Write-Host 'Play normally. Recording stops automatically. Close the game to restore the installation and save the ZIP.'
    while (-not $game.HasExited) {
        if ($stopEvent.WaitOne(200)) {
            $meta.recording_stop_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
            break
        }
        if ($timer.Elapsed.TotalMinutes -ge 15) {
            $issues.Add('Wall-clock recording limit reached before the required active-play window.')
            break
        }
        if ($present.HasExited) { $issues.Add('PresentMon exited during the capture.'); break }
    }
    Stop-BinderRecording
    if (-not $game.HasExited) { Write-Host 'Recording stopped. The game is still running.' }
    $game.WaitForExit()
    $meta.exit_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $meta.game_exit_code = $game.ExitCode
    if ($game.ExitCode -ne 0) { $issues.Add("Game exit code $($game.ExitCode)") }
} catch {
    $issues.Add($_.Exception.Message)
    Write-Host $_.Exception.Message
    if ($game -and -not $game.HasExited) {
        Write-Host 'Close the game to restore the installation.'
        $game.WaitForExit()
    }
} finally {
    try { Stop-BinderRecording } catch { $issues.Add($_.Exception.Message) }
    if ($stopEvent) { $stopEvent.Dispose() }
    try {
        if ($journal) {
            $receipt = Restore-BinderTransaction $journal $journalPath $install.bin $install.save_directory
            Write-BinderJournal $receipt (Join-Path $output 'install_transaction.json')
            $rolledBack = $true
            Remove-Item -LiteralPath $txRoot -Recurse -Force
        }
    } catch {
        $issues.Add("Automatic restore failed; recovery journal retained: $($_.Exception.Message)")
        Write-Host $issues[$issues.Count - 1]
    } finally { $lock.Dispose() }
}
if (Test-Path -LiteralPath $output) {
    $meta.restored = $rolledBack
    Write-BinderJournal $meta (Join-Path $output 'capture.json')
    & $python (Join-Path $PSScriptRoot 'analyze_binder.py') $output $tools --pack
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if (-not $rolledBack) { exit 1 }
