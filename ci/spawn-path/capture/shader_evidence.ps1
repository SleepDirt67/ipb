param(
    [string]$GameRoot,
    [string]$OutputDirectory,
    [DateTime]$StartedUtc
)

# Only metadata from the IX-Ray app-data folders is read, after the game has exited.
$roots = @('_appdata_ixray_', '_appdata_', 'appdata')
$foundRoots = @()
$changes = @()
$settings = @()
foreach ($root in $roots) {
    $folder = Join-Path $GameRoot $root
    $cache = Join-Path $folder 'shaders_cache'
    if (Test-Path -LiteralPath $cache -PathType Container) {
        $foundRoots += $root
        $changes += @(Get-ChildItem -LiteralPath $cache -File -Recurse |
            Where-Object { $_.LastWriteTimeUtc -ge $StartedUtc } |
            ForEach-Object {
                [PSCustomObject]@{
                    app_data = $root
                    shader_variant = $_.FullName.Substring($cache.Length + 1)
                    modified_utc = $_.LastWriteTimeUtc.ToString('o')
                    bytes = $_.Length
                }
            })
    }
    $config = Join-Path $folder 'user.ltx'
    if (Test-Path -LiteralPath $config -PathType Leaf) {
        $settings += @(Select-String -LiteralPath $config -Pattern '^\s*r__shader_cache\s+(on|off|0|1)(?:\s|$)' |
            ForEach-Object { [PSCustomObject]@{ app_data = $root; saved_value = $_.Matches[0].Groups[1].Value } })
    }
}
[PSCustomObject]@{
    since_utc = $StartedUtc.ToString('o')
    cache_roots = $foundRoots
    changed_files = @($changes | Sort-Object modified_utc)
    saved_settings = $settings
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'shader_cache_changes.json') -Encoding UTF8
