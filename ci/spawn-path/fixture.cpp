#include <windows.h>
extern "C" {
#include <lua/lua.h>
#include <lua/lauxlib.h>
#include <lua/lualib.h>
}
#define ENGINE_API
#include "SpawnLuaProfile.h"

namespace PacingDiag
{
    thread_local Kind phase = Kind::None;
    bool SpawnPathEnabled() { return true; }
    Kind SpawnBinderPhase() { return phase; }
    Kind ExchangeSpawnBinderPhase(Kind value) { const auto old = phase; phase = value; return old; }
    unsigned CurrentFrame() { return 1; }
    unsigned long long Counter() { LARGE_INTEGER q; QueryPerformanceCounter(&q); return q.QuadPart; }
    void Record(Kind, unsigned, unsigned long long, unsigned long long, unsigned long long) {}
}

int main()
{
    auto* state = luaL_newstate();
    if (!state)
        return 1;
    luaL_openlibs(state);
    SpawnLuaProfile::Start(state);
    if (!SpawnLuaProfile::recorder)
        return 2;
    {
        using PacingDiag::Kind;
        PacingDiag::SpawnSpan outer(Kind::BinderNetSpawn, 0, true);
        {
            PacingDiag::SpawnSpan nested(Kind::BinderReinit, 0, true);
            if (PacingDiag::SpawnBinderPhase() != Kind::BinderReinit)
                return 3;
        }
        if (PacingDiag::SpawnBinderPhase() != Kind::BinderNetSpawn)
            return 4;
        const char* script =
            "local function work()\n"
            "  local start, now = os.clock(), os.clock()\n"
            "  while now - start < 0.3 do\n"
            "    now = os.clock()\n"
            "  end\n"
            "end\n"
            "work()\nreturn 42";
        if (luaL_loadbuffer(state, script, strlen(script), "@spawn_path_fixture.script")
            || lua_pcall(state, 0, 1, 0) || lua_tointeger(state, -1) != 42)
            return 5;
    }
    if (PacingDiag::SpawnBinderPhase() != PacingDiag::Kind::None)
        return 6;
    const auto count = SpawnLuaProfile::recorder->next.load();
    if (!count || count >= SpawnLuaProfile::Recorder::capacity)
        return 7;
    SpawnLuaProfile::Stop(state);
    lua_close(state);
    std::printf("PASS: LuaJIT returned 42, nested binder scopes restored, %u stack rows\n", count);
    return 0;
}
