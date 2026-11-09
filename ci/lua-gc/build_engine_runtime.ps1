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
cmake -S luajit -B gc-build -A x64 -DLUAJIT_TARGET_ARCH=x64
if ($LASTEXITCODE -ne 0) { throw 'LuaJIT configure failed' }
cmake --build gc-build --config Release --target libluajit --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'LuaJIT compile failed' }

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
    stock_dll_sha256 = $original
    candidate_dll_sha256 = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate_pdb_sha256 = (Get-FileHash -LiteralPath $symbols -Algorithm SHA256).Hash.ToLowerInvariant()
}
$identity | ConvertTo-Json | Set-Content checks/LUAJIT_RUNTIME.json -Encoding utf8
Copy-Item -LiteralPath $candidate -Destination $runtime -Force
"LUAJIT_RUNTIME_SHA256=$($identity.candidate_dll_sha256)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
