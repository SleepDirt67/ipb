$ErrorActionPreference = 'Stop'
$manifest = Get-Content package/BUILD_MANIFEST.json -Raw | ConvertFrom-Json
if ($manifest.commit -ne $env:GITHUB_SHA -or $manifest.build_repository -ne $env:GITHUB_REPOSITORY) {
    throw 'Source/run identity mismatch'
}
$game = Join-Path $env:RUNNER_TEMP 'IX-Ray Release install QA'
$bin = Join-Path $game 'bin'
New-Item -ItemType Directory -Force $bin | Out-Null
$before = @{}
foreach ($module in $manifest.modules) {
    $source = Join-Path package/bin $module.name
    if ((Get-FileHash -LiteralPath $source).Hash -ne $module.sha256) { throw "Invalid package $source" }
    $target = Join-Path $bin $module.name
    [IO.File]::WriteAllBytes($target, [Text.Encoding]::UTF8.GetBytes("original " + $module.name))
    $before[$module.name] = (Get-FileHash -LiteralPath $target).Hash
}
& ./package/install.ps1 -GameRoot $game -BinDirectory $bin
foreach ($module in $manifest.modules) {
    if ((Get-FileHash -LiteralPath (Join-Path $bin $module.name)).Hash -ne $module.sha256) {
        throw "Invalid installed $($module.name)"
    }
}
& ./package/restore.ps1
foreach ($name in $before.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $bin $name)).Hash -ne $before[$name]) {
        throw "Invalid restored $name"
    }
}
Remove-Item package/installation.json -ErrorAction SilentlyContinue
foreach ($line in Get-Content package/SHA256SUMS.txt) {
    $expected, $name = $line -split '  ', 2
    if ((Get-FileHash -LiteralPath (Join-Path package $name)).Hash -ne $expected) {
        throw "Final package hash mismatch at $name"
    }
}
'PASS: actual Release installed and exact original 36-file fixture restored' | Set-Content checks/PUBLIC_WINDOWS_QA.txt
