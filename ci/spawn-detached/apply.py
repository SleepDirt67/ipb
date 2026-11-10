"""Build detached animated NPC visuals before runtime admission."""
from pathlib import Path
import sys

root = Path(sys.argv[1])


def edit(path, replacements):
    path = root / path
    raw = path.read_bytes()
    text = raw.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError((path, before[:95], text.count(before)))
        text = text.replace(before, after, 1)
    output = text.encode("latin-1")
    if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    path.write_bytes(output)
    return text


model = "src/Layers/xrRender/ModelPool"
edit(model + ".h", [
    ("    std::map<std::string, dxRender_Visual*, std::less<>> preparedReferences;",
     """    struct PreparedReference
    {
        dxRender_Visual* reference = nullptr;
        bool registered = false;
        xr_vector<xr_unique_ptr<dxRender_Visual>> clones;
    };
    std::map<std::string, PreparedReference, std::less<>> preparedReferences;
    void DiscardPreparedClones(dxRender_Visual* reference, const shared_str& name);
    void IncrementReference(dxRender_Visual* reference);"""),
    ("    bool PrepareReference(const char* name);",
     "    bool PrepareReference(const char* name, unsigned copies = 0);"),
])

methods = edit(model + ".cpp", [
    ("""    // inc ref counter
\tfor (xr_vector<ModelDef>::iterator I=Models.begin(); I!=Models.end(); I++) 
\t\tif (I->model==V)
\t\t{ 
\t\t\tI->refs++; 
\t\t\tbreak;
\t\t}
\treturn N;
}""",
     """    IncrementReference(V);
\treturn N;
}

void CModelPool::IncrementReference(dxRender_Visual* reference)
{
    for (auto& model : Models)
        if (model.model == reference)
        {
            ++model.refs;
            break;
        }
}"""),
    ("bool CModelPool::PrepareReference(const char* name)",
     "bool CModelPool::PrepareReference(const char* name, unsigned copies)"),
    ("    preparedReferences.emplace(name, reference);",
     """    auto& prepared = preparedReferences.try_emplace(name).first->second;
    prepared.reference = reference;

    // Copy creates child instances through the renderer. Only leaf
    // geometry with a no-op Spawn is eligible. The actor's own Spawn
    // remains at normal admission.
    if (copies && reference->Type == MT_SKELETON_ANIM)
    {
        const auto& skeleton = *static_cast<CKinematicsAnimated*>(reference);
        const auto leaf = [this](const dxRender_Visual* visual) {
            const auto type = visual->Type;
            const bool geometry = type == MT_SKELETON_GEOMDEF_PM || type == MT_SKELETON_GEOMDEF_ST ||
                type == MT_NORMAL || type == MT_PROGRESSIVE || type == MT_LOD;
            return geometry && std::none_of(Models.begin(), Models.end(), [visual](const ModelDef& model) {
                return model.model == visual;
            });
        };
        if ((!skeleton.m_lod || leaf(skeleton.m_lod)) &&
            std::all_of(skeleton.children.begin(), skeleton.children.end(), leaf))
        {
            copies = std::min(copies, 4u);
            prepared.clones.reserve(copies);
            for (unsigned i = 0; i < copies; ++i)
            {
                xr_unique_ptr<dxRender_Visual> instance(Instance_Create(reference->Type));
                instance->Copy(reference);
                prepared.clones.push_back(std::move(instance));
            }
        }
    }"""),
    ("""        entry.second->Release();
        xr_delete(entry.second);""",
     """        auto& prepared = entry.second;
        prepared.clones.clear();
        if (!prepared.registered)
        {
            prepared.reference->Release();
            xr_delete(prepared.reference);
        }"""),
    ("dxRender_Visual* CModelPool::Create(const char* name, IReader* data)",
     """void CModelPool::DiscardPreparedClones(dxRender_Visual* reference, const shared_str& name)
{
    const auto entry = preparedReferences.find(*name);
    if (entry != preparedReferences.end() && entry->second.reference == reference)
        preparedReferences.erase(entry);
}

dxRender_Visual* CModelPool::Create(const char* name, IReader* data)"""),
    ("""\t\tdxRender_Visual* Base\t\t= Instance_Find\t\t(low_name);

\t\tif (0==Base){""",
     """\t\tdxRender_Visual* Base\t\t= Instance_Find\t\t(low_name);
        const auto prepared = data ? preparedReferences.end() : preparedReferences.find(low_name);

\t\tif (0==Base){"""),
    ("""            if (!data)
            {
                const auto prepared = preparedReferences.find(low_name);
                if (prepared != preparedReferences.end())
                {
                    Base = prepared->second;
                    Instance_Register(low_name, Base);
                    preparedReferences.erase(prepared);
                }
            }""",
     """            if (prepared != preparedReferences.end() && !prepared->second.registered)
            {
                Base = prepared->second.reference;
                Instance_Register(low_name, Base);
                prepared->second.registered = true;
            }"""),
    ("""        // 3. If found - return (cloned) reference
        dxRender_Visual*\t\tModel\t= Instance_Duplicate(Base);""",
     """        if (prepared != preparedReferences.end() && prepared->second.reference == Base)
        {
            auto& clones = prepared->second.clones;
            if (!clones.empty())
            {
                auto& clone = clones.back();
                clone->Spawn();
                Registry.emplace(clone.get(), low_name);
                IncrementReference(Base);
                auto* instance = clone.release();
                clones.pop_back();
                if (clones.empty())
                    preparedReferences.erase(prepared);
                return instance;
            }
            preparedReferences.erase(prepared);
        }
        // 3. If found - return (cloned) reference
        dxRender_Visual*\t\tModel\t= Instance_Duplicate(Base);"""),
    ("\t\t\t\t\t\tbForceDiscard = TRUE;\n\t\t\t\t\t\tI->model->Release();",
     """\t\t\t\t\t\tbForceDiscard = TRUE;
                        DiscardPreparedClones(I->model, name);
\t\t\t\t\t\tI->model->Release();"""),
])

renderer = "src/Layers/xrRenderPC_R4/r4"
edit(renderer + ".h", [
    ("bool PrepareSpawnModelReference(const char* name);",
     "bool PrepareSpawnModelReference(const char* name);\n    bool PrepareSpawnModelClones(const char* name, unsigned copies);"),
])
edit(renderer + ".cpp", [
    ("""#ifdef _WIN32
extern "C" __declspec(dllexport) bool __cdecl xrPrepareSpawnModelReference""",
     """bool CRender::PrepareSpawnModelClones(const char* name, unsigned copies)
{
    return Models && Models->PrepareReference(name, copies);
}

#ifdef _WIN32
extern "C" __declspec(dllexport) bool __cdecl xrPrepareSpawnModelClones(const char* name, unsigned copies)
{
    return RImplementation.PrepareSpawnModelClones(name, copies);
}

extern "C" __declspec(dllexport) bool __cdecl xrPrepareSpawnModelReference"""),
])

edit("src/xrGame/PrepareSpawnVisuals.inc", [
    ("void AddSpawnVisual(xr_set<xr_string>& visuals, const char* name)",
     "const xr_string* AddSpawnVisual(xr_set<xr_string>& visuals, const char* name)"),
    ("""    if (!name || !*name)
        return;
    string_path model;
    if (xr_strlen(name) >= sizeof(model) - sizeof(".ogf"))
        return;""",
     """    if (!name || !*name)
        return {};
    string_path model;
    if (xr_strlen(name) >= sizeof(model) - sizeof(".ogf"))
        return {};"""),
    ("    if (*model)\n        visuals.emplace(model);", "    return *model ? &*visuals.emplace(model).first : nullptr;"),
    ("""    if (!prepareReference)
        return;""",
     """    if (!prepareReference)
        return;
    using PrepareClones = bool (__cdecl*)(const char*, unsigned);
    const auto prepareClones = reinterpret_cast<PrepareClones>(
        GetProcAddress(renderer, "xrPrepareSpawnModelClones"));"""),
    ("    xr_set<xr_string> visuals;", "    xr_set<xr_string> visuals;\n    xr_map<xr_string, unsigned> stalkerCopies;"),
    ("""        if (auto* visual = object->visual())
            AddSpawnVisual(visuals, visual->get_visual());""",
     """        if (auto* visual = object->visual())
        {
            const auto* name = AddSpawnVisual(visuals, visual->get_visual());
            if (name && smart_cast<const CSE_ALifeHumanStalker*>(object))
                ++stalkerCopies[*name];
        }"""),
    ("    unsigned prepared = 0;", """    unsigned prepared = 0;
    unsigned remainingCopies = 64;"""),
    ("""        if (prepareReference(model.c_str()))
            ++prepared;""",
     """        const auto found = stalkerCopies.find(model);
        const unsigned copies = !prepareClones || found == stalkerCopies.end() ? 0 :
            std::min({4u, found->second, remainingCopies});
        const bool loaded = copies ? prepareClones(model.c_str(), copies) : prepareReference(model.c_str());
        if (loaded)
        {
            ++prepared;
            remainingCopies -= copies;
        }"""),
])

if len(sys.argv) > 2:
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    start = methods.index("void CModelPool::IncrementReference")
    end = methods.index("dxRender_Visual*\tCModelPool::Instance_Load", start)
    counter = methods[start:end]
    start = methods.index("dxRender_Visual* CModelPool::LoadReference")
    end = methods.index("dxRender_Visual* CModelPool::CreateChild", start)
    (out / "model-methods.inc").write_text(counter + methods[start:end], encoding="latin-1")
