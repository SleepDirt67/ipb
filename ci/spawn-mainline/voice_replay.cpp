#include "xrCore.h"

extern "C" {
#include <lua/lua.h>
#include <lua/lauxlib.h>
#include <lua/lualib.h>
}
#include <luabind/luabind.hpp>

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <vector>

#include "src/xrGame/SpawnVoiceBindings.h"

enum ESoundTypes { SOUND_TYPE_TALKING = 0x4000 };

namespace
{
unsigned fsCalls;
unsigned registrations;

void Require(bool condition, const char* description)
{
    if (!condition)
    {
        std::fprintf(stderr, "Failed: %s\n", description);
        std::abort();
    }
}
}

class CScriptGameObject
{
    std::string prefix_ = "characters_voice\\model\\";
    unsigned id_ = 1;
public:
    unsigned id() const { return id_; }
    void set_id(unsigned value) { id_ = value; }
    CScriptGameObject& object() { return *this; }
    CScriptGameObject* cast_stalker() { return this; }
    const char* sound_prefix() const { return prefix_.c_str(); }
    void sound_prefix(const char* prefix) { prefix_ = prefix; }

    unsigned add_sound(const char*, unsigned, ESoundTypes, unsigned, unsigned, unsigned)
    {
        ++registrations;
        return 7;
    }

    unsigned add_combat_sound(const char*, unsigned, ESoundTypes, unsigned, unsigned, unsigned, const char*)
    {
        ++registrations;
        return 4;
    }

    unsigned scripted_add_sound(const char*, unsigned, ESoundTypes, unsigned, unsigned, unsigned)
    {
        ++registrations;
        return 2;
    }
};

#include "src/xrGame/SpawnVoiceApply.inc"

static const CLocatorAPI::file* Exist(CLocatorAPI* fs, const char* root, const char* path)
{
    ++fsCalls;
    return fs->exist(root, path);
}

static CLocatorAPI* GetFS() { return &FS; }

static void Load(lua_State* L, const char* script, bool file)
{
    const int result = file ? luaL_loadfile(L, script) : luaL_loadstring(L, script);
    if (result || lua_pcall(L, 0, 0, 0))
    {
        std::fprintf(stderr, "Lua: %s\n", lua_tostring(L, -1));
        std::abort();
    }
}

static void Register(lua_State* L)
{
    using namespace luabind;
    open(L);
    module(L)[
        class_<CLocatorAPI::file>("FS_file"),
        class_<CLocatorAPI>("FS")
            .def("exist", &Exist)
            .def("sound_variant_count", &CLocatorAPI::sound_variant_count),
        def("getFS", &GetFS),
        class_<CScriptGameObject>("game_object")
            .def(constructor<>())
            .def("id", &CScriptGameObject::id)
            .def("set_id", &CScriptGameObject::set_id)
            .def("sound_prefix", static_cast<const char* (CScriptGameObject::*)() const>(&CScriptGameObject::sound_prefix))
            .def("sound_prefix", static_cast<void (CScriptGameObject::*)(const char*)>(&CScriptGameObject::sound_prefix))
            .def("add_sound", &CScriptGameObject::add_sound)
            .def("add_combat_sound", &CScriptGameObject::add_combat_sound)
            .def("other_add_sound", &CScriptGameObject::scripted_add_sound)
    ];
    static constexpr const char* methods[] = {"exist"};
    SpawnVoice::Capture(L, SpawnVoice::fsKey, "FS", methods, std::size(methods));
    SpawnVoice::RegisterNativeApply(L);
}

struct Result
{
    std::string state;
    double ms;
    unsigned fs;
    unsigned added;
    unsigned applied;
};

static Result Replay(const char* voice, const char* input, const char* mode)
{
    auto* L = luaL_newstate();
    Require(L != nullptr, "Lua state");
    luaL_openlibs(L);
    Register(L);
    Load(L, input, true);
    Load(L, voice, true);
    lua_pushstring(L, mode);
    lua_setglobal(L, "replay_mode");
    fsCalls = registrations = 0;
    const auto start = std::chrono::steady_clock::now();
    Load(L, "replay_spawn()", false);
    const double ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - start).count();
    lua_getglobal(L, "replay_result");
    Require(lua_isstring(L, -1), "replay result");
    Result result{lua_tostring(L, -1), ms, fsCalls, registrations, 0};
    lua_getglobal(L, "native_applied");
    result.applied = static_cast<unsigned>(lua_tointeger(L, -1));
    lua_close(L);
    return result;
}

int main(int argc, char** argv)
{
    Require(argc == 5, "stock, previous, candidate and replay input");
    const auto root = std::filesystem::absolute("spawn-voice-replay");
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root / "characters_voice/model");
    for (auto directory : {"characters_voice", "characters_voice/model"})
    {
        for (auto name : {"line0.ogg", "line1.ogg", "line2.ogg", "line4.ogg", "line03.ogg", "single.ogg",
            "single1.ogg", "line21.ogg", "line22.ogg", "line25.ogg"})
        {
            std::ofstream wave(root / directory / name);
            wave << name;
        }
    }

    Core._initialize("spawn-voice-replay", nullptr, FALSE, nullptr);
    const auto absolute = root.string();
    FS._initialize(CLocatorAPI::flTargetFolderOnly, absolute.c_str(), nullptr);
    FS.append_path("$game_sounds$", absolute.c_str(), nullptr, TRUE);
    FS.prepare_spawn_voice_catalogue();
    Require(FS.prepared_spawn_voice_count("CHARACTERS_VOICE\\MODEL\\LINE") == 2, "Lua first hole");
    Require(FS.prepared_spawn_voice_count("characters_voice\\model\\line2") == -1, "Lua exact file wins");
    xr_vector<u32> numbers;
    Require(FS.find_numbered_sounds("characters_voice\\model\\line", 64, numbers), "native numbered query");
    Require((numbers == xr_vector<u32>{0, 1, 2, 4, 21, 22, 25}), "native gaps and zero preserved");

    for (const auto* mode : {"normal", "npc_override", "fs_override", "getfs_override", "debug_hook"})
    {
        const auto base = Replay(argv[1], argv[4], mode);
        const auto work = Replay(argv[3], argv[4], mode);
        const auto previous = Replay(argv[2], argv[4], mode);
        Require(work.state == base.state && work.added == base.added, mode);
        Require(work.state == previous.state && work.added == previous.added, "PR24 result");
        if (std::string_view(mode) == "normal")
            Require(work.applied == work.added && work.fs == 0 && base.fs > 0, "native path activation");
        else
            Require(work.applied == 0, "script replacements use original binder");
        std::printf("PASS %s: %u registrations, Lua VFS calls %u -> %u, native %u\n",
            mode, work.added, base.fs, work.fs, work.applied);
    }
    std::vector<double> stock, previous, candidate;
    for (int trial = 0; trial < 9; ++trial)
    {
        if (trial % 2)
        {
            candidate.push_back(Replay(argv[3], argv[4], "normal").ms);
            previous.push_back(Replay(argv[2], argv[4], "normal").ms);
            stock.push_back(Replay(argv[1], argv[4], "normal").ms);
        }
        else
        {
            stock.push_back(Replay(argv[1], argv[4], "normal").ms);
            previous.push_back(Replay(argv[2], argv[4], "normal").ms);
            candidate.push_back(Replay(argv[3], argv[4], "normal").ms);
        }
    }
    std::sort(stock.begin(), stock.end());
    std::sort(previous.begin(), previous.end());
    std::sort(candidate.begin(), candidate.end());
    std::printf("Fixture median stock / PR24 Lua with shared catalogue / candidate: %.3f / %.3f / %.3f ms\n",
        stock[4], previous[4], candidate[4]);

    string_path name;
    FS.update_path(name, "$game_sounds$", "characters_voice\\model\\line1.ogg");
    FS.file_delete(name);
    Require(FS.prepared_spawn_voice_count("characters_voice\\model\\line") == -2, "delete invalidation");
    const auto stale = Replay(argv[3], argv[4], "normal");
    Require(stale.applied == 0, "invalid index uses original binder");
    FS.prepare_spawn_voice_catalogue();
    Require(FS.prepared_spawn_voice_count("characters_voice\\model\\line") == 0, "index rebuilt without file");

    Core._destroy();
    std::filesystem::remove_all(root);
}
