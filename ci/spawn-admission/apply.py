"""Install detached spawn preparation over the PR27 activation patch."""
from pathlib import Path
import shutil
import sys

source = Path(__file__).resolve().parent
engine = Path(sys.argv[1]) / "src"
physics = engine / "xrPhysics"
game = engine / "xrGame"

def edit(directory, filename, pairs):
    path = directory / filename
    original = path.read_bytes()
    text = original.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in pairs:
        if text.count(before) != 1:
            raise ValueError((filename, before, text.count(before)))
        text = text.replace(before, after, 1)
    data = text.encode("latin-1")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        data = data.replace(b"\n", b"\r\n")
    path.write_bytes(data)

for name in ("SpawnPreparationQueue.h", "SpawnActivationWork.h", "ActivationGeometry.inc", "SpawnPreparedGeometry.h"):
    shutil.copyfile(source / name, physics / name)
shutil.copyfile(source / "SpawnAdmission.inc", game / "SpawnAdmission.inc")

edit(engine / "xrCore/Collision", "xrCDB.h", [
    ("\t\tvoid\t\t\tbox_query\t\t(const MODEL *m_def, const Fvector& b_center, const Fvector& b_dim);",
     """\t\tvoid\t\t\tbox_query\t\t(const MODEL *m_def, const Fvector& b_center, const Fvector& b_dim);
        bool box_query_bounded(const MODEL* model, const Fvector& center, const Fvector& extent,
            u32 maxNodes, u32 maxResults);"""),
])
edit(engine / "xrCore/Collision", "xrCDB_box.cpp", [
    ("\tvoid\t\t\t_prim\t\t(DWORD prim)\n\t{",
     """    template<bool Bounded = false>
    bool _prim(DWORD prim, u32 maxResults = 0)
    {"""),
    ("\t\tif (!_tri())\t\t\treturn;\n\t\tRESULT& R", """        if (!_tri())
            return true;
        if constexpr (Bounded)
            if (static_cast<u32>(dest->r_count()) >= maxResults)
                return false;
\t\tRESULT& R"""),
    ("""\t\tR.dummy\t\t= T.dummy;
\t}
\tvoid\t\t\t_stab\t\t(const AABBNoLeafNode* node)""", """\t\tR.dummy\t\t= T.dummy;
        return true;
\t}
\tvoid\t\t\t_stab\t\t(const AABBNoLeafNode* node)"""),
    ("\n};\n\nvoid COLLIDER::box_query", """
    bool _stab_bounded(const AABBNoLeafNode* node, u32& remaining, u32 maxResults)
    {
        if (!remaining)
            return false;
        --remaining;
        if (!_box((Fvector&)node->mAABB.mCenter, (Fvector&)node->mAABB.mExtents))
            return true;
        const bool first = node->HasPosLeaf() ? _prim<true>(node->GetPosPrimitive(), maxResults) :
            _stab_bounded(node->GetPos(), remaining, maxResults);
        if (!first)
            return false;
        if (bFirst && dest->r_count())
            return true;
        return node->HasNegLeaf() ? _prim<true>(node->GetNegPrimitive(), maxResults) :
            _stab_bounded(node->GetNeg(), remaining, maxResults);
    }
};

void COLLIDER::box_query"""),
    ("\nstruct obb_collider", """
bool COLLIDER::box_query_bounded(const MODEL* model, const Fvector& center,
    const Fvector& extent, u32 maxNodes, u32 maxResults)
{
    r_clear();
    // The worker owns a read-only level model published after loading.
    // A model that is still building is a miss, never a sync point.
    if (!model || model->status != MODEL::S_READY || !model->tree)
        return false;
    const auto* tree = static_cast<const AABBNoLeafTree*>(model->tree->GetTree());
    if (!tree || !tree->GetNodes())
        return false;
    cform_box_collider query(!!(box_mode & OPT_FULL_TEST), !!(box_mode & OPT_ONLYFIRST));
    query._init(this, model->verts, model->tris, center, extent);
    if (query._stab_bounded(tree->GetNodes(), maxNodes, maxResults))
        return true;
    r_clear();
    return false;
}

struct obb_collider"""),
])

edit(engine / "xrEngine", "PacingDiagnostics.h", [
    ("OtherGameEvent, SpawnPublish, ALifeSwitchOnline",
     "OtherGameEvent, SpawnPublish, ALifeSwitchOnline,\n"
     "        SpawnPrepareSubmit, SpawnPrepareWorker, SpawnPrepareUse, SpawnPrepareMiss"),
])

edit(physics, "ActivationCollisionPlan.h", [
    ("    void ClearRows()", "public:\n    void ClearRows()"),
    ("public:\n    void Clear()", "    void Clear()"),
])

edit(physics, "SpawnActivationContacts.h", [
    ('#include "ActivationCollisionPlan.h"', '#include "ActivationCollisionPlan.h"\n#include "SpawnActivationWork.h"'),
    ("class Scope\n{", """} // namespace SpawnCollision

namespace SpawnPreparation
{
SpawnCollision::Face* TakeActivationGeometry(ActivationResult* result, const CDB::MODEL* model,
    const float* center, const Fvector& halfSize, const Fvector& queryExtent,
    unsigned fpMode, SpawnCollision::Plan<SpawnCollision::Face>& plan, xr_vector<int>& ids, bool& matched);
}

namespace SpawnCollision
{
class Scope
{"""),
    ("    dBodyID body_;", "    dBodyID body_;\n    SpawnPreparation::ActivationResult* prepared_;"),
    ("explicit Scope(dBodyID body) : parent_(current_), body_(body)",
     "explicit Scope(dBodyID body, SpawnPreparation::ActivationResult* prepared = nullptr)\n"
     "        : parent_(current_), body_(body), prepared_(prepared)"),
    ("    static unsigned FloatingPointMode()", """    static SpawnPreparation::ActivationResult* PreparedFor(dBodyID body)
    {
        return current_ && current_->body_ == body ? current_->prepared_ : nullptr;
    }

    static unsigned FloatingPointMode()"""),
])
edit(physics, "IActivationShape.cpp", [
    ('#include "SpawnActivationContacts.h"',
     '#include "SpawnActivationContacts.h"\n#include "console_vars.h"\n#include "ActivationGeometry.inc"'),
    ("SpawnCollision::Scope contacts(activation_shape.ODEBody());",
     "SpawnCollision::Scope contacts(activation_shape.ODEBody(), SpawnPreparation::ActivationScope::For(m_EntityAlife));"),
])
edit(physics, "tri-colliderknoopc/dSortTriPrimitive.h", [
    ("    bool newStaticQuery = false;",
     "    bool newStaticQuery = false;\n    SpawnCollision::Face* detachedFaces = nullptr;"),
    ("        if (newStaticQuery)\n        {",
     """        bool detached = false;
        if (newStaticQuery && activation)
            detachedFaces = SpawnPreparation::TakeActivationGeometry(
                SpawnCollision::Scope::PreparedFor(dGeomGetBody(o1)), model,
                p, AABB, aabb, fpMode, *activation, data->cashed_tries, detached);
        if (newStaticQuery && !detached)
        {"""),
    ("            if (activation)\n                activation->SetStaticQueryCount(data->cashed_tries.size());\n        }",
     "        }\n        if (activation && newStaticQuery)\n            activation->SetStaticQueryCount(data->cashed_tries.size());"),
    ("    if (activation && !activation->Select",
     "    if (activation && !detachedFaces && !activation->Select"),
    ("        auto* prepared = activation ? &activation->At(static_cast<std::size_t>(I - B)) : nullptr;",
     """        const auto faceIndex = static_cast<std::size_t>(I - B);
        auto* prepared = detachedFaces ? &detachedFaces[faceIndex] :
            activation ? &activation->At(faceIndex) : nullptr;"""),
])

edit(game, "Level.h", [
    ("class\tCSE_Abstract;", "class\tCSE_Abstract;\nclass CSE_ALifeDynamicObject;\nclass CALifeLevelRegistry;\n"
     "namespace SpawnPreparation { class ActivationWork; }"),
    ("\tNET_Queue_Event\t\t\t\t*game_events;",
     """    SpawnPreparation::ActivationWork* spawnActivationWork = nullptr;
    bool spawnActivationWorkInitialized = false;
    u16 spawnPreparationCursor = u16(-1);

\tNET_Queue_Event\t\t\t\t*game_events;"""),
    ("\tvoid\t\t\t\t\t\tcl_Process_Spawn", """    bool PrepareALifeSpawn(const CSE_ALifeDynamicObject& object, bool speculative);
    void PrepareALifeSpawns(const CALifeLevelRegistry& registry,
        const Fvector& actorPosition, float onlineDistance);

\tvoid\t\t\t\t\t\tcl_Process_Spawn"""),
])
edit(game, "Level.cpp", [
    ('#include "StdAfx.h"', '#include "StdAfx.h"\n#include "../xrPhysics/SpawnActivationWork.h"'),
    ('\tPROF_EVENT("CLevel::~CLevel");', '\tPROF_EVENT("CLevel::~CLevel");\n'
     '    SpawnPreparation::StopActivationWork(spawnActivationWork);'),
    ("    FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::LevelFrame);",
     """    FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::LevelFrame);
    if (!spawnActivationWorkInitialized && bReady && !g_dedicated_server &&
        IsGameTypeSingle() && OnServer() && !IsDemoPlay() && !IsDemoSave() &&
        g_loading_events.empty() && !Device.dwPrecacheFrame)
    {
        spawnActivationWorkInitialized = true;
        spawnActivationWork = SpawnPreparation::StartActivationWork(ObjectSpace.GetStaticModel());
    }"""),
])
edit(game, "Level_network.cpp", [
    ('#include "StdAfx.h"', '#include "StdAfx.h"\n#include "../xrPhysics/SpawnActivationWork.h"'),
    ('\tMsg("- Disconnect");', '\tMsg("- Disconnect");\n    SpawnPreparation::StopActivationWork(spawnActivationWork);'),
])
edit(game, "Level_network_spawn.cpp", [
    ('#include "patrol_path_params.h"', '''#include "patrol_path_params.h"
#include "entity_alive.h"
#include "alife_level_registry.h"
#include "../xrPhysics/SpawnActivationWork.h"
#include "SpawnAdmission.inc"'''),
    ("        spawnSucceeded = O->net_Spawn(E);", """        auto* alive = spawnActivationWork ? smart_cast<CEntityAlive*>(O) : nullptr;
        SpawnPreparation::ActivationScope preparation(spawnActivationWork, E->ID, alive);
        spawnSucceeded = O->net_Spawn(E);"""),
])
root = engine.parent
shutil.copyfile(source / "fixture.cpp", root / "ixray_spawn_admission_fixture.cpp")
with (root / "CMakeLists.txt").open("a", encoding="utf-8") as build:
    build.write("""
add_executable(ixray_spawn_admission_fixture ixray_spawn_admission_fixture.cpp)
target_link_libraries(ixray_spawn_admission_fixture PRIVATE xrCore)
""")


edit(game, "alife_update_manager.cpp", [
    ('#include "alife_simulator_header.h"',
     '#include "alife_simulator_header.h"\n#include "xrServer_Objects_ALife_Monsters.h"'),
    ("\tupdate_scheduled(false);",
     "\tupdate_scheduled(false);\n"
     "    if (!m_changing_level && g_pGameLevel && graph().actor())\n"
     "        Level().PrepareALifeSpawns(graph().level(), graph().actor()->o_Position, online_distance());"),
])
