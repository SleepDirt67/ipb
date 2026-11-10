$ErrorActionPreference = 'Stop'
$upstream = 'dbb6c39f7c69691f6bd9a8b5d6bf7c97b3dbe268'
$recipe = '02c62d81bc3ab8a46c37efa3c13af3217afa9e08'
if ((git -C luajit rev-parse HEAD) -ne $upstream -or (git -C recipe rev-parse HEAD) -ne $recipe) {
    throw 'Unexpected LuaJIT source or IX-Ray packaging recipe'
}
foreach ($patch in (Get-ChildItem recipe/pkg/LuaJIT/LuaJIT/1626960173/patch/*.patch | Sort-Object Name)) {
    git -C luajit apply $patch.FullName
    if ($LASTEXITCODE -ne 0) { throw "IX-Ray LuaJIT recipe rejected $($patch.Name)" }
}
$indexPatch = (Resolve-Path ci/lua-gc/userdata-index.patch).Path
git -C luajit apply $indexPatch
if ($LASTEXITCODE -ne 0) { throw 'Indexed userdata patch rejected' }
cmake -S luajit -B gc-reference-build -A x64 -DLUAJIT_TARGET_ARCH=x64 -DLUAJIT_ENABLE_APPLICATION=ON
if ($LASTEXITCODE -ne 0) { throw 'LuaJIT configure failed' }
cmake --build gc-reference-build --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Reference LuaJIT compile failed' }

New-Item -ItemType Directory -Path gc-reference,gc-candidate | Out-Null
Copy-Item gc-reference-build/bin/Release/lua51.dll,gc-reference-build/bin/Release/luajit.exe -Destination gc-reference
$headers = (Resolve-Path luajit/src).Path
$import = (Resolve-Path gc-reference-build/lib/Release/lua51.lib).Path
cmake -S ci/lua-gc -B gc-replay -A x64 "-DLUA_HEADERS=$headers" "-DLUA_IMPORT=$import"
if ($LASTEXITCODE -ne 0) { throw 'Lua GC replay configure failed' }
cmake --build gc-replay --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Lua GC replay compile failed' }

$tablePatch = (Resolve-Path ci/lua-gc/table-sweep.patch).Path
git -C luajit apply $tablePatch
if ($LASTEXITCODE -ne 0) { throw 'Dense table sweep patch rejected' }
# The generated VM embeds GCState offsets. Generate it in a fresh tree.
cmake -S luajit -B gc-build -A x64 -DLUAJIT_TARGET_ARCH=x64 -DLUAJIT_ENABLE_APPLICATION=ON
if ($LASTEXITCODE -ne 0) { throw 'Candidate LuaJIT configure failed' }
cmake --build gc-build --config Release --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'Candidate LuaJIT compile failed' }
Copy-Item gc-build/bin/Release/lua51.dll,gc-build/bin/Release/luajit.exe -Destination gc-candidate

foreach ($variant in @('reference', 'candidate')) {
    Copy-Item gc-replay/Release/*.exe -Destination "gc-$variant"
    & "gc-$variant/luajit.exe" ci/lua-gc/userdata_replay.lua > "checks/LUAJIT_FINALIZERS_$variant.txt"
    if ($LASTEXITCODE -ne 0) { throw "$variant userdata semantics failed" }
    & "gc-$variant/luajit.exe" ci/lua-gc/table_sweep_check.lua | Tee-Object checks/LUAJIT_TABLE_SEMANTICS.txt -Append
    if ($LASTEXITCODE -ne 0) { throw "$variant table sweep semantics failed" }
    & "gc-$variant/close_gc_check.exe"
    if ($LASTEXITCODE -ne 0) { throw "$variant shutdown semantics failed" }
}
if ((Get-FileHash checks/LUAJIT_FINALIZERS_reference.txt).Hash -ne (Get-FileHash checks/LUAJIT_FINALIZERS_candidate.txt).Hash) {
    throw 'Finalizer ordering differed'
}
for ($iteration = 0; $iteration -lt 4; ++$iteration) {
    $variants = if ($iteration % 2) { @('candidate', 'reference') } else { @('reference', 'candidate') }
    foreach ($tables in @(0, 150000)) {
        foreach ($variant in $variants) {
            $sample = & "gc-$variant/binder_gc_bench.exe" 60000 600 105 $tables
            if ($LASTEXITCODE -ne 0) { throw "$variant binder allocation replay failed" }
            "$iteration $variant $sample" | Tee-Object checks/LUAJIT_TABLE_SWEEP_WINDOWS.txt -Append
        }
    }
}

$packages = 'ixray/build/x64/Engine-Windows/packages'
$lib = Get-ChildItem $packages -Recurse -File -Filter lua51.lib
if (@($lib).Count -ne 1) { throw 'Expected one pinned LuaJIT import library' }
$runtime = Join-Path $lib.Directory.Parent.FullName 'bin/lua51.dll'
$expected = '09fd13282c381f5b9afae3debb986474656d466006c80591e9da251f0ddcc47c'
$original = (Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant()
if ($original -ne $expected) { throw 'Original Lua runtime mismatch' }
$candidate = (Resolve-Path gc-build/bin/Release/lua51.dll).Path
$symbols = (Resolve-Path gc-build/bin/Release/lua51.pdb).Path
python ci/lua-gc/verify_abi.py $runtime $candidate
if ($LASTEXITCODE -ne 0) { throw 'Rebuilt runtime changed the public Lua ABI' }
$identity = [ordered]@{
    upstream_commit = $upstream
    recipe_commit = $recipe
    patch_sha256 = (Get-FileHash -LiteralPath $indexPatch -Algorithm SHA256).Hash.ToLowerInvariant()
    table_sweep_patch_sha256 = (Get-FileHash -LiteralPath $tablePatch -Algorithm SHA256).Hash.ToLowerInvariant()
    stock_dll_sha256 = $original
    candidate_dll_sha256 = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_pdb_sha256 = (Get-FileHash -LiteralPath $symbols -Algorithm SHA256).Hash.ToLowerInvariant()
}
$identity | ConvertTo-Json | Set-Content checks/LUAJIT_RUNTIME.json -Encoding utf8
Copy-Item -LiteralPath $candidate -Destination $runtime -Force
"LUAJIT_RUNTIME_SHA256=$($identity.candidate_dll_sha256)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
