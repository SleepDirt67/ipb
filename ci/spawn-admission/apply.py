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

edit(engine / "xrEngine", "PacingDiagnostics.h", [
    ("OtherGameEvent, SpawnPublish, ALifeSwitchOnline",
     "OtherGameEvent, SpawnPublish, ALifeSwitchOnline,\n"
     "        SpawnPrepareSubmit, SpawnPrepareWorker, SpawnPrepareUse, SpawnPrepareMiss"),
])

edit(physics, "SpawnActivationContacts.h", [
    ('#include "ActivationCollisionPlan.h"', '#include "ActivationCollisionPlan.h"\n#include "SpawnActivationWork.h"'),
    ("class Scope\n{", """} // namespace SpawnCollision

namespace SpawnPreparation
{
SpawnCollision::Face* TakeActivationGeometry(ActivationResult* result, const CDB::MODEL* model,
    const float* center, const Fvector& halfSize, const Fvector& queryExtent,
    unsigned fpMode, xr_vector<int>& ids, bool& matched);
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
                p, AABB, aabb, fpMode, data->cashed_tries, detached);
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
    ("\tvoid\t\t\t\t\t\tcl_Process_Spawn", """    bool PrepareALifeSpawn(const CSE_ALifeDynamicObject& object, bool speculative = false);
    void PrepareOfflineALifeSpawns(const CALifeLevelRegistry& registry,
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
edit(game, "alife_switch_manager.cpp", [
    ('#ifdef DEBUG\n#\tinclude "level.h"\n#endif // DEBUG', '#include "Level.h"'),
    ("\tobject->m_bOnline\t\t\t\t= true;", """    if (g_pGameLevel)
        Level().PrepareALifeSpawn(*object);

\tobject->m_bOnline\t\t\t\t= true;"""),
])
edit(game, "alife_online_offline_group.cpp", [
    ('#include "alife_simulator.h"', '#include "alife_simulator.h"\n#include "Level.h"'),
    ("\tMEMBERS::iterator\t\t\tI = m_members.begin();\n\tMEMBERS::iterator\t\t\tE = m_members.end();\n\tfor ( ; I != E; ++I){\n\t\talife().add_online",
     """    if (g_pGameLevel)
        for (const auto& entry : m_members)
            Level().PrepareALifeSpawn(*entry.second);

\tMEMBERS::iterator\t\t\tI = m_members.begin();
\tMEMBERS::iterator\t\t\tE = m_members.end();
\tfor ( ; I != E; ++I){
\t\talife().add_online"""),
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
     "        Level().PrepareOfflineALifeSpawns(graph().level(), graph().actor()->o_Position, online_distance());"),
])
