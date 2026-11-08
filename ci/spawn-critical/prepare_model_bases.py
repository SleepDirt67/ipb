"""Replace the PR27 preview clone with loading of the renderer model reference."""
import argparse
from pathlib import Path


def patch(root):
    edits = {}

    def edit(relative, old, new):
        path = root / relative
        original, data = edits.get(path, (None, None))
        if original is None:
            original = path.read_bytes()
            data = original.replace(b"\r\n", b"\n")
        old, new = old.encode(), new.encode()
        if data.count(old) != 1:
            raise ValueError(f"{relative}: expected one patch anchor, found {data.count(old)}")
        edits[path] = original, data.replace(old, new, 1)

    pool = "src/Layers/xrRender/ModelPool."
    edit(pool + "h",
         "\t\t\t\t\t\tDestroy\t();",
         """\t\t\t\t\t\tDestroy\t();
    std::map<std::string, dxRender_Visual*, std::less<>> preparedReferences;
    dxRender_Visual* LoadReference(const char* name, IReader* data, BOOL registerReference);
    void ClearPreparedReferences();""")
    edit(pool + "h", "\tvoid\t\t\t\t\tPrefetch\t\t\t();",
         """    // The caller is the level loader on the renderer-owning thread.
    bool PrepareReference(const char* name);
\tvoid\t\t\t\t\tPrefetch\t\t\t();""")
    edit(pool + "cpp", "dxRender_Visual* CModelPool::Create(const char* name, IReader* data)",
         """dxRender_Visual* CModelPool::LoadReference(const char* name, IReader* data, BOOL registerReference)
{
    bAllowChildrenDuplicate = FALSE;
    auto* reference = data ? Instance_Load(name, data, registerReference) :
        Instance_Load(name, registerReference);
    bAllowChildrenDuplicate = TRUE;
    return reference;
}

bool CModelPool::PrepareReference(const char* name)
{
    // PrepareSpawnVisuals supplies the normalized keys used by Create.
    // Keep unpublished references separate from live and pooled models.
    if (!name || !*name || Instance_Find(name) || preparedReferences.find(name) != preparedReferences.end())
        return false;

    auto* reference = LoadReference(name, nullptr, FALSE);
    if (!reference)
        return false;
    preparedReferences.emplace(name, reference);
    return true;
}

void CModelPool::ClearPreparedReferences()
{
    for (auto& entry : preparedReferences)
    {
        entry.second->Release();
        xr_delete(entry.second);
    }
    preparedReferences.clear();
}

dxRender_Visual* CModelPool::Create(const char* name, IReader* data)""")
    edit(pool + "cpp", """\t\t\tbAllowChildrenDuplicate\t= FALSE;
\t\t\tif (data)\t\tBase = Instance_Load(low_name,data,TRUE);
            else\t\t\tBase = Instance_Load(low_name,TRUE);
\t\t\tbAllowChildrenDuplicate\t= TRUE;""",
         """            if (!data)
            {
                const auto prepared = preparedReferences.find(low_name);
                if (prepared != preparedReferences.end())
                {
                    Base = prepared->second;
                    Instance_Register(low_name, Base);
                    preparedReferences.erase(prepared);
                }
            }
            if (!Base)
                Base = LoadReference(low_name, data, TRUE);""")
    edit(pool + "cpp", "void CModelPool::Destroy()\n{",
         "void CModelPool::Destroy()\n{\n    ClearPreparedReferences();")
    edit(pool + "cpp", "void CModelPool::ClearPool( BOOL b_complete)\n{",
         "void CModelPool::ClearPool( BOOL b_complete)\n{\n    if (b_complete)\n        ClearPreparedReferences();")
    render = "src/Layers/xrRenderPC_R4/r4."
    edit(render + "h", "\t// Models\n",
         """\t// Models
    bool PrepareSpawnModelReference(const char* name);
""")
    edit(render + "cpp", "IRenderVisual* CRender::model_Create(LPCSTR name, IReader* data) {",
         """bool CRender::PrepareSpawnModelReference(const char* name)
{
    return Models && Models->PrepareReference(name);
}

#ifdef _WIN32
extern "C" __declspec(dllexport) bool __cdecl xrPrepareSpawnModelReference(const char* name)
{
    return RImplementation.PrepareSpawnModelReference(name);
}
#endif

IRenderVisual* CRender::model_Create(LPCSTR name, IReader* data) {""")
    preload = "src/xrGame/PrepareSpawnVisuals.inc"
    edit(preload, """    xr_set<xr_string> visuals;""",
         """#ifndef _WIN32
    return;
#else
    using PrepareReference = bool (__cdecl*)(const char*);
    const auto renderer = GetModuleHandleW(L"xrRender_R4.dll");
    const auto prepareReference = renderer ? reinterpret_cast<PrepareReference>(
        GetProcAddress(renderer, "xrPrepareSpawnModelReference")) : nullptr;
    if (!prepareReference)
        return;

    xr_set<xr_string> visuals;""")
    edit(preload, """        auto* visual = Render->model_Create(model.c_str());
        if (visual)
        {
            Render->model_Delete(visual);
            ++prepared;
        }
    }
    Msg("* spawn visuals: %u of %zu candidates prepared in %.1f ms", prepared, visuals.size(),
        timer.GetElapsed_sec() * 1000.0f);
}""",
         """        if (prepareReference(model.c_str()))
            ++prepared;
    }
    Msg("* spawn model references: %u of %zu candidates loaded in %.1f ms", prepared, visuals.size(),
        timer.GetElapsed_sec() * 1000.0f);
#endif
}""")
    for path, (original, data) in edits.items():
        if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
            data = data.replace(b"\n", b"\r\n")
        path.write_bytes(data)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("engine", type=Path)
    patch(cli.parse_args().engine)
