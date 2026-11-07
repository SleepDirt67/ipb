"""Exercise the exact patched renderer source with stock HLSL and the Windows compiler."""
from pathlib import Path
import sys

engine, output = map(Path, sys.argv[1:])
source = (engine / "src/Layers/xrRenderPC_R4/r4.cpp").read_text(encoding="utf-8")
params = source[source.index("xr_string CRender::getShaderParams()"):source.index("xr_string CRender::getShaderParamsDebug()")]
compile_start = source.index("class includer : public ID3DInclude")
warm = source.index("void CRender::PrewarmPacingShaderCache()", compile_start)
compile_end = source.index("\n}", warm) + 2
output.write_text(params + source[compile_start:compile_end] + "\n", encoding="utf-8")
