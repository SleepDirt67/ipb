$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argsForUac = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '"'
    $elevated = Start-Process -FilePath "$PSHOME\powershell.exe" -ArgumentList $argsForUac -Verb RunAs -Wait -PassThru
    exit $elevated.ExitCode
}

. (Join-Path $PSScriptRoot 'installation_common.ps1')
. (Join-Path $PSScriptRoot 'stop_presentmon.ps1')
Check-GameClosed
$state = Read-Installation
$manifestPath = Join-Path $PSScriptRoot 'BUILD_MANIFEST.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.capture_kind -ne 'spawn-path-v1') {
    throw 'Run this launcher from the matching installed spawn path package.'
}
$stackDecoder = Join-Path $PSScriptRoot 'capture-tools\ixray_stack_extract.exe'
$stackAnalyzer = Join-Path $PSScriptRoot 'analyze_stacks.py'
$symbolIndex = Join-Path $PSScriptRoot 'capture-tools\stack-symbols'
foreach ($path in @($stackDecoder,$stackAnalyzer,$symbolIndex)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Incomplete stack overlay: $path" }
}
foreach ($module in $manifest.modules) {
    if ((Hash (Join-Path $state.bin $module.name)) -ne $module.sha256) {
        throw "Installed file differs from this package: $($module.name). Run INSTALL.cmd first."
    }
}

$pm = Join-Path $PSScriptRoot 'capture-tools\PresentMon-2.6.0-x64.exe'
$decoder = Join-Path $PSScriptRoot 'capture-tools\ixray_etw_decode.exe'
$python = Join-Path $PSScriptRoot 'capture-tools\python\python.exe'
$analyzer = Join-Path $PSScriptRoot 'analyze_capture.py'
$wpr = Join-Path $env:SystemRoot 'System32\wpr.exe'
if ((Hash $pm) -ne 'b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af') {
    throw 'PresentMon checksum mismatch.'
}
foreach ($path in @($decoder,$python,$analyzer)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Unpack the entire diagnostic package: $path" }
}

$name = (Get-Date -Format 'yyyyMMdd_HHmmss_fff') + '_SpawnPath'
$directory = Join-Path $PSScriptRoot "captures\$name"
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot 'captures') -Force | Out-Null
New-Item -ItemType Directory -Path $directory | Out-Null
$session = 'IXRayAuto_' + [guid]::NewGuid().ToString('N')
$started = [DateTime]::UtcNow
$issues = New-Object 'System.Collections.Generic.List[string]'
$metadata = [ordered]@{
    schema = 1; mode = 'SpawnPath'; resource_mode = 'Both'; binary_commit = $manifest.commit
    diagnostic_commit = $manifest.commit
    start_utc = $started.ToString('o'); qpc_frequency = [Diagnostics.Stopwatch]::Frequency
    launch_qpc = $null; exit_qpc = $null; pid = $null; game_exit_code = $null
    pixel_probe_requested = $true; module_snapshot_qpc = $null
    wpr_instance = $session; presentmon_session = $session; cpu_only_fixture = $false
}
$env:IXRAY_AUDIO_WARMUP = '1'
$env:IXRAY_SCRIPT_INI_CACHE = '1'
$env:IXRAY_SPAWN_PATH = '1'
$env:IXRAY_PACING = '1'
$env:IXRAY_PACING_DEEP = '0'
$env:IXRAY_PACING_PIXELS = '1'
$env:IXRAY_PACING_DIR = $directory
$env:IXRAY_TRACE_FRAME_STALLS = '0'
$env:IXRAY_TRACE_ALL_FRAMES = '0'
$env:IXRAY_TRACE_HUMAN_LOG = '0'

$wprStarted = $false
$present = $null
$game = $null
try {
    try {
        $profileArgument = (Join-Path $PSScriptRoot 'IXRayCpuStacks.wprp') + '!IXRayCpuStacks'
        & $wpr -start $profileArgument -instancename $session *> (Join-Path $directory 'wpr_start.txt')
        if ($LASTEXITCODE -ne 0) { throw "WPR start exit=$LASTEXITCODE" }
        $wprStarted = $true
    } catch { $issues.Add("CPU ETW start: $_") }

    try {
        # Track the executable name before it exists, then validate the exact PID offline.
        $options = '--process_name xrEngine.exe --qpc_time --write_display_metadata --no_track_input --no_console_stats'
        $options += ' --session_name ' + $session + ' --output_file "' + (Join-Path $directory 'presentmon.csv') + '"'
        $metadata.presentmon_arguments = $options
        $presentArgs = @{
            FilePath = $pm; ArgumentList = $options; PassThru = $true
            RedirectStandardOutput = (Join-Path $directory 'presentmon_stdout.txt')
            RedirectStandardError = (Join-Path $directory 'presentmon_stderr.txt')
        }
        $present = Start-Process @presentArgs
        # Windows PowerShell 5.1 needs the process handle retained until ExitCode is read.
        $null = $present.Handle
        $watch = [Diagnostics.Stopwatch]::StartNew()
        do {
            if ($present.HasExited) { throw "PresentMon exited before game start: $($present.ExitCode)" }
            & $decoder --session-active $session
            if ($LASTEXITCODE -eq 0) { break }
            if ($watch.Elapsed.TotalSeconds -gt 10) { throw 'PresentMon session did not become ready within 10 seconds.' }
            Start-Sleep -Milliseconds 50
        } while ($true)
    } catch { $issues.Add("PresentMon start: $_") }

    Write-Host 'Play normally for 2-3 minutes where the issue occurs, then exit the game normally.'
    $metadata.launch_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $game = Start-Process -FilePath (Join-Path $state.bin 'xrEngine.exe') -WorkingDirectory $state.game_root -PassThru
    $null = $game.Handle
    $metadata.pid = $game.Id
    # Take one startup snapshot once the game's modules are loaded.
    try {
        $deadline = [Diagnostics.Stopwatch]::StartNew()
        $required = @('xrGame.dll','xrRender_R4.dll','xrCore.dll')
        do {
            $game.Refresh()
            if ($game.HasExited) { break }
            $modules = @($game.Modules)
            $found = @($required | Where-Object { $_ -in $modules.ModuleName })
            if ($found.Count -eq $required.Count) {
                $stamp = [Diagnostics.Stopwatch]::GetTimestamp()
                $modules | ForEach-Object {
                    [PSCustomObject]@{name=$_.ModuleName;base_hex=$_.BaseAddress.ToInt64().ToString('x');size=$_.ModuleMemorySize}
                } | Export-Csv -NoTypeInformation -Encoding UTF8 (Join-Path $directory 'module_snapshot.csv')
                $metadata.module_snapshot_qpc = $stamp
                break
            }
            Start-Sleep -Milliseconds 800
        } while ($deadline.Elapsed.TotalSeconds -lt 55)
        if (-not $metadata.module_snapshot_qpc) { $issues.Add('Module snapshot did not find the expected game images.') }
    } catch { $issues.Add("Module snapshot: $_") }
    $game.WaitForExit()
    $metadata.exit_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
    $metadata.game_exit_code = $game.ExitCode
    if ($game.ExitCode -ne 0) { $issues.Add("Game exit code: $($game.ExitCode)") }
} catch {
    $issues.Add("Game: $_")
} finally {
    if ($wprStarted) {
        try {
            Write-Host 'Saving sampled CPU stacks...'
            & $wpr -stop (Join-Path $directory 'cpu_samples.etl') 'IX-Ray gameplay pacing' -skipPdbGen -instancename $session *> (Join-Path $directory 'wpr_stop.txt')
            if ($LASTEXITCODE -ne 0) { throw "WPR stop exit=$LASTEXITCODE" }
        } catch {
            $issues.Add("CPU ETW stop: $_")
            # Release only this unique recording on a failed save; retain its logs.
            & $wpr -cancel -instancename $session *> (Join-Path $directory 'wpr_cancel.txt')
        }
    }
    if ($null -ne $present) {
        try { Stop-PacingPresentMon $present $pm $session $directory }
        catch { $issues.Add("PresentMon save: $_") }
    }

    Copy-Item -LiteralPath $manifestPath -Destination $directory
    foreach ($relative in @('_appdata_ixray_\logs','_appdata_\logs','appdata\logs','logs')) {
        $logs = Join-Path $state.game_root $relative
        if (Test-Path -LiteralPath $logs) {
            try {
                Get-ChildItem -LiteralPath $logs -Filter '*.log' -File | Where-Object { $_.LastWriteTimeUtc -ge $started } |
                    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $directory }
            } catch { $issues.Add("Game log copy: $_") }
        }
    }
    try {
        & (Join-Path $PSScriptRoot 'shader_evidence.ps1') $state.game_root $directory $started
    } catch { Write-Warning "Shader cache metadata could not be collected: $_" }
    $metadata.capture_errors = @($issues.ToArray())
    $metadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $directory 'capture.json') -Encoding UTF8
    Write-Host 'Analyzing and packaging capture after game exit...'
    & $python $stackAnalyzer $directory $stackDecoder $symbolIndex
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Automatic analysis failed. The raw capture will still be archived.' }
    if (Test-Path -LiteralPath (Join-Path $directory 'frame_timeline.csv')) {
        & $python (Join-Path $PSScriptRoot 'analyze_display_path.py') $directory (Join-Path $PSScriptRoot 'capture-tools\ixray_display_path.exe')
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Graphics path analysis failed. The raw capture will still be archived.' }
    }
    & $python (Join-Path $PSScriptRoot 'analyze_spawn_path.py') $directory
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Spawn path analysis failed. The raw capture will still be archived.' }
    & $python $analyzer $directory --pack
    if ($LASTEXITCODE -ne 0) { throw "Archive creation failed. Keep the complete directory: $directory" }
    foreach ($issue in $issues) { Write-Warning $issue }
    Write-Host "Send this archive: $directory.zip"
}
if ($null -eq $game) { exit 1 }
