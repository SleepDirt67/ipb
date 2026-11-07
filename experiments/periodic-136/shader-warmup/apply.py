"""Prewarm the traced DX11 variants through the ordinary compiler and cache."""
from pathlib import Path
import sys

engine = Path(sys.argv[1] if len(sys.argv) > 1 else "ixray")
folder = engine / "src/Layers/xrRenderPC_R4"


def edit(name, replacements):
    path = folder / name
    data = path.read_bytes()
    source = data.decode("utf-8").replace("\r\n", "\n")
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError(f"{name}: expected exactly one {before[:85]!r}")
        source = source.replace(before, after, 1)
    if b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""):
        source = source.replace("\n", "\r\n")
    path.write_bytes(source.encode("utf-8"))


edit("r4.h", [
    ("\txr_string_map<xr_string, xr_string>\t\t\t\t\t\t\tm_ShaderOptions;",
     """\tusing ShaderOptions = xr_string_map<xr_string, xr_string>;
\tShaderOptions m_ShaderOptions;
\ttemplate<class Options> static xr_string ShaderParams(const Options& options);
\ttemplate<class Options>
\tHRESULT CompileShader(LPCSTR name, DWORD const* source, UINT size, LPCSTR entry, LPCSTR target,
\t\tDWORD flags, void*& result, const Options& options, int skinning, bool cacheOnly);
\tvoid PrewarmPacingShaderCache();"""),
])

edit("r4_loader.cpp", [
    ("\t// Components\n\tWallmarks", "\tPrewarmPacingShaderCache();\n\n\t// Components\n\tWallmarks"),
])

edit("r4.cpp", [
    ('#include "r4.h"', '#include "r4.h"\n#include <span>'),
    ("""xr_string CRender::getShaderParams() 
{
\tif(!m_ShaderOptions.empty()) """, """xr_string CRender::getShaderParams()
{
\treturn ShaderParams(m_ShaderOptions);
}

template<class Options>
xr_string CRender::ShaderParams(const Options& options)
{
\tif(!options.empty())"""),
    ("\t\tfor(auto& [Name, Value] : m_ShaderOptions)", "\t\tfor(const auto& [Name, Value] : options)"),
    ("""\tvoid*& result) 
{
\tD3D_SHADER_MACRO defines[128];""", """\tvoid*& result)
{
\treturn CompileShader(name, pSrcData, SrcDataLen, pFunctionName, pTarget, Flags, result,
\t\tm_ShaderOptions, Engine.External.GetSkinningMode(), false);
}

template<class Options>
HRESULT CRender::CompileShader(LPCSTR name, DWORD const* pSrcData, UINT SrcDataLen,
\tLPCSTR pFunctionName, LPCSTR pTarget, DWORD Flags, void*& result,
\tconst Options& options, int m_skinning, bool cacheOnly)
{
\tD3D_SHADER_MACRO defines[128];"""),
    ("\tfor(auto& [Name, Value] : m_ShaderOptions)", "\tfor(const auto& [Name, Value] : options)"),
    ("\tconst int m_skinning = Engine.External.GetSkinningMode();\n\t{", "\t{"),
    ("\t\tif(file->length() > 4) {", "\t\tif(file && file->length() > 8) {"),
    ("""\t\t\t\t\t_result = create_shader(pTarget, (DWORD*)file->pointer(), file->elapsed(), file_name, result, o.disasm);""",
     """\t\t\t\t\t_result = cacheOnly ? S_FALSE :
\t\t\t\t\t\tcreate_shader(pTarget, (DWORD*)file->pointer(), file->elapsed(), file_name, result, o.disasm);"""),
    ("\t\tfile->close();\n\t}\n\n\tif(FAILED(_result))", "\t\tFS.r_close(file);\n\t}\n\n\tif(FAILED(_result))"),
    ("""\t\t\tif(/*ps_r__common_flags.test(RFLAG_USE_CACHE)*/1) {
\t\t\t\tIWriter* file = FS.w_open(file_name);
\t\t\t\tu32 const crc = crc32(pShaderBuf->GetBufferPointer(), pShaderBuf->GetBufferSize());
\t\t\t\tfile->w_u32(crc);
\t\t\t\tfile->w_u32(RealCodeCRC);
\t\t\t\tfile->w(pShaderBuf->GetBufferPointer(), (u32)pShaderBuf->GetBufferSize());
\t\t\t\tFS.w_close(file);
\t\t\t}
\t\t\t_result = create_shader(pTarget, (DWORD*)pShaderBuf->GetBufferPointer(), (u32)pShaderBuf->GetBufferSize(), file_name, result, o.disasm);""",
     """\t\t\tIWriter* file = FS.w_open(file_name);
\t\t\tconst bool writable = file && file->valid();
\t\t\tif (writable) {
\t\t\t\tconst u32 crc = crc32(pShaderBuf->GetBufferPointer(), pShaderBuf->GetBufferSize());
\t\t\t\tfile->w_u32(crc);
\t\t\t\tfile->w_u32(RealCodeCRC);
\t\t\t\tfile->w(pShaderBuf->GetBufferPointer(), (u32)pShaderBuf->GetBufferSize());
\t\t\t}
\t\t\tFS.w_close(file);
\t\t\tif (cacheOnly)
\t\t\t\t_result = writable ? S_OK : HRESULT_FROM_WIN32(ERROR_WRITE_FAULT);
\t\t\telse
\t\t\t\t_result = create_shader(pTarget, (DWORD*)pShaderBuf->GetBufferPointer(), (u32)pShaderBuf->GetBufferSize(), file_name, result, o.disasm);"""),
    ("""\t\t\t\tMsg("Can't compile shader hr=0x%08x", _result);
\t\t\t}
\t\t}
\t}

\treturn _result;
}""", """\t\t\t\tMsg("Can't compile shader hr=0x%08x", _result);
\t\t\t}
\t\t}
\t\t_RELEASE(pShaderBuf);
\t\t_RELEASE(pErrorBuf);
\t}

\treturn _result;
}

void CRender::PrewarmPacingShaderCache()
{
\tif (g_dedicated_server || !ps_r__common_flags.test(RFLAG_USE_CACHE) ||
\t\tCore.ParamsData.test(ECoreParams::renderdoc) || Core.ParamsData.test(ECoreParams::dxdebug))
\t\treturn;

\tconst auto& defaults = EngineExternal().ShadersOptions;
\tconst auto legacy = defaults.find(xr_string("USE_LEGACY_LIGHT"));
\tif (defaults.size() != 1 || legacy == defaults.end() || legacy->second != "1")
\t\treturn;

\tstruct Variant {
\t\tLPCSTR name;
\t\tint skinning;
\t\tbool pixel;
\t\tbool bumpedHighQuality;
\t};
\tconstexpr Variant observed[] = {
\t\t{ "model_distort", 3, false, false },
\t\t{ "model_distort", 4, false, false },
\t\t{ "model_distort4ghost", 0, false, false },
\t\t{ "model_distort4ghost", 1, false, false },
\t\t{ "deffer_model", 4, false, true },
\t\t{ "particle_hard", 4, true, false },
\t};
\t// The current cache hashes options in iteration order. Match the order in the captured keys.
\tconst std::pair<xr_string, xr_string> measuredOptions[] = {
\t\t{ "USE_LEGACY_LIGHT", "1" }, { "USE_BUMP", "1" }, { "USE_HIGH_QUALITY", "1" },
\t};

\tfor (const auto& variant : observed) {
\t\tconst std::span options(measuredOptions, variant.bumpedHighQuality ? 3u : 1u);
\t\tstring_path path;
\t\txr_strconcat(path, getShaderPath(), variant.name, variant.pixel ? ".ps.hlsl" : ".vs.hlsl");
\t\tIReader* file = FS.r_open("$game_shaders$", path);
\t\tif (!file)
\t\t\tcontinue;
\t\tconst u32 size = file->length();
\t\txr_string source;
\t\tif (size)
\t\t\tsource.assign(static_cast<LPCSTR>(file->pointer()), size);
\t\tFS.r_close(file);

\t\t// These stock variants use main. Defer alternate entry points to their normal loader.
\t\tif (!size || source.find(variant.pixel ? "main_ps_" : "main_vs_") != xr_string::npos)
\t\t\tcontinue;
\t\txr_string name = variant.name;
\t\tif (!variant.pixel) {
\t\t\tname += "_";
\t\t\tname += xr_string::ToString(variant.skinning);
\t\t}
\t\tname += ShaderParams(options);
\t\tvoid* unused = nullptr;
\t\tconst HRESULT hr = CompileShader(name.c_str(), reinterpret_cast<const DWORD*>(source.data()),
\t\t\tsize, "main", variant.pixel ? "ps_2_0" : "vs_2_0", D3DCOMPILE_PACK_MATRIX_ROW_MAJOR,
\t\t\tunused, options, variant.skinning, true);
\t\tMsg("* shader prewarm: %s %s (0x%08x)", name.c_str(),
\t\t\thr == S_FALSE ? "cache hit" : (SUCCEEDED(hr) ? "compiled during loading" : "deferred"), hr);
\t}
}"""),
])
