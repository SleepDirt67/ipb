"""Install opt-in QPC attribution at IX-Ray's existing spawn and Lua boundaries."""
from pathlib import Path
import shutil
import sys

source = Path(__file__).resolve().parent
engine = Path(sys.argv[1]) / "src"


def edit(name, replacements):
    target = engine / name
    data = target.read_bytes()
    crlf = b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")
    text = data.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError(f"{name}: expected one anchor {before!r}, found {text.count(before)}")
        text = text.replace(before, after, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    target.write_bytes(text.encode("latin-1"))


def mark(kind, argument=""):
    return f"PacingDiag::SpawnSpan spawnPath(PacingDiag::Kind::{kind}{argument});"


def enter(anchor, kind, argument=""):
    return anchor, anchor + "\n    " + mark(kind, argument)


def include(anchor):
    return anchor, anchor + '\n#include "../xrEngine/PacingDiagnostics.h"'


edit("xrEngine/PacingDiagnostics.h", [
    ("OnIdle = 1", "None = 0, OnIdle = 1"),
    ("TimedCallbacks, HudUpdate", """TimedCallbacks, HudUpdate,
        SpawnDispatch, StalkerSpawn, BinderReload, BinderReinit, BinderNetSpawn,
        BinderSoundCollection, BinderPosition, OtherGameEvent, SpawnPublish, ALifeSwitchOnline"""),
    ("    class Span", """    ENGINE_API bool SpawnPathEnabled();
    ENGINE_API Kind SpawnBinderPhase();
    ENGINE_API Kind ExchangeSpawnBinderPhase(Kind phase);

    class SpawnSpan
    {
        Kind kind_;
        bool active_;
        bool binder_;
        Kind previous_;
        unsigned frame_;
        unsigned long long start_, payload_;
    public:
        explicit SpawnSpan(Kind kind, unsigned long long payload = 0, bool binder = false, bool enabled = true)
            : kind_(kind), active_(enabled && SpawnPathEnabled()), binder_(active_ && binder),
              previous_(binder_ ? ExchangeSpawnBinderPhase(kind) : Kind::None),
              frame_(active_ ? CurrentFrame() : 0),
              start_(active_ ? Counter() : 0), payload_(payload) {}
        ~SpawnSpan()
        {
            if (!active_)
                return;
            const auto end = Counter();
            if (binder_)
                ExchangeSpawnBinderPhase(previous_);
            Record(kind_, frame_, start_, end, payload_);
        }
        SpawnSpan(const SpawnSpan&) = delete;
        SpawnSpan& operator=(const SpawnSpan&) = delete;
    };

    class Span"""),
])
edit("xrEngine/PacingDiagnostics.cpp", [
    ("    bool Pixels()", """    namespace { thread_local Kind spawnBinderPhase = Kind::None; }
    bool SpawnPathEnabled() {
        static const bool enabled = Enabled() && Flag(L"IXRAY_SPAWN_PATH");
        return enabled;
    }
    Kind SpawnBinderPhase() { return spawnBinderPhase; }
    Kind ExchangeSpawnBinderPhase(Kind phase) {
        const auto previous = spawnBinderPhase;
        spawnBinderPhase = phase;
        return previous;
    }
    bool Pixels()"""),
])
edit("xrGame/script_binder.cpp", [
    include('#include "../xrEngine/FrameStallDiagnostics.h"'),
    enter("void CScriptBinder::reinit\t\t\t()\n{", "BinderReinit", ", 0, true"),
    enter("void CScriptBinder::reload\t\t\t(LPCSTR section)\n{", "BinderReload", ", 0, true"),
    enter("BOOL CScriptBinder::net_Spawn\t\t(CSE_Abstract* DC)\n{", "BinderNetSpawn", ", DC ? DC->ID : 0xffff, true"),
])
edit("xrGame/Level_network_spawn.cpp", [
    include('#include "StdAfx.h"'),
    enter("void CLevel::g_sv_Spawn\t\t(CSE_Abstract* E)\n{", "SpawnDispatch",
          ", E->ID | (static_cast<unsigned long long>(E->ID_Parent) << 16)"),
    ('} else {\n\t\tif(!g_dedicated_server)\n\t\t\tclient_spawn_manager().callback(O);',
     '} else {\n        ' + mark("SpawnPublish", ", E->ID") +
     '\n\t\tif(!g_dedicated_server)\n\t\t\tclient_spawn_manager().callback(O);'),
])
edit("xrGame/ai/stalker/ai_stalker.cpp", [
    ('#include "stdafx.h"', '#include "stdafx.h"\n#include "../../../xrEngine/PacingDiagnostics.h"'),
    enter("BOOL CAI_Stalker::net_Spawn\t\t\t(CSE_Abstract* DC)\n{", "StalkerSpawn"),
])
edit("xrGame/sound_player.cpp", [
    include('#include "StdAfx.h"'),
    enter("CSoundPlayer::CSoundCollection::CSoundCollection\t(const CSoundCollectionParams &params)\n{",
          "BinderSoundCollection"),
])
edit("xrGame/script_game_object2.cpp", [
    include('#include "StdAfx.h"'),
    enter("void CScriptGameObject::SetNpcPosition(Fvector pos)\n{", "BinderPosition"),
])
edit("xrGame/Level.cpp", [
    ("\t\t\tswitch (ID)\n\t\t\t{\n\t\t\tcase M_SPAWN:",
     "\t\t\tPacingDiag::SpawnSpan otherEvent(PacingDiag::Kind::OtherGameEvent,\n"
     "\t\t\t    ID == M_EVENT ? ID | (static_cast<unsigned long long>(type) << 16) |\n"
     "\t\t\t        (static_cast<unsigned long long>(dest) << 32) : ID, false, ID != M_SPAWN);\n"
     "\t\t\tswitch (ID)\n\t\t\t{\n\t\t\tcase M_SPAWN:"),
])
edit("xrGame/alife_switch_manager.cpp", [
    include('#include "StdAfx.h"'),
    enter("void CALifeSwitchManager::add_online(CSE_ALifeDynamicObject *object, bool update_registries)\n{",
          "ALifeSwitchOnline", ", object->ID"),
])
edit("xrScripts/script_storage.cpp", [
    ('#include "script_process.h"', '#include "script_process.h"\n#include "SpawnLuaProfile.h"'),
    ("\tif (m_virtual_machine)\n\t\tlua_close(m_virtual_machine);",
     "\tif (m_virtual_machine) {\n        SpawnLuaProfile::Stop(m_virtual_machine);\n\t\tlua_close(m_virtual_machine);\n    }"),
    ("\tif (m_virtual_machine)\n\t{\n\t\tlua_close(m_virtual_machine);",
     "\tif (m_virtual_machine)\n\t{\n        SpawnLuaProfile::Stop(m_virtual_machine);\n\t\tlua_close(m_virtual_machine);"),
    ("\tlua_init_ext(lua());\n#endif\n}", "\tlua_init_ext(lua());\n#endif\n    SpawnLuaProfile::Start(lua());\n}"),
])
shutil.copyfile(source / "SpawnLuaProfile.h", engine / "xrScripts/SpawnLuaProfile.h")
print("Installed QPC spawn path and opt-in Lua stack sampling")
