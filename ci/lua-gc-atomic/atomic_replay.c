#include <stdio.h>
#include <stdlib.h>
#include <windows.h>

#include "lua.h"
#include "lauxlib.h"
#include "lj_obj.h"
#include "lj_gc.h"

static unsigned finalized, last_finalized;
static int closing;

static int finalize_tag(lua_State *L)
{
    unsigned tag = *(unsigned *)lua_touserdata(L, 1);
    if (tag >= last_finalized || (closing ? tag % 4 != 0 : tag % 4 == 0))
        abort();
    last_finalized = tag;
    ++finalized;
    return 0;
}

int main(int argc, char **argv)
{
    const unsigned count = argc == 2 ? strtoul(argv[1], NULL, 10) : 60000u;
    lua_State *L = luaL_newstate();
    if (!L)
        return 1;
    global_State *g = G(L);
    if (g->gc.state != GCSpause)
        abort();
    lua_gc(L, LUA_GCSTOP, 0);
    lua_createtable(L, 0, 1);
    lua_pushcfunction(L, finalize_tag);
    lua_setfield(L, 1, "__gc");
    lua_createtable(L, count / 4, 0);
    for (unsigned i = 1; i <= count; ++i)
    {
        unsigned *tag = lua_newuserdata(L, sizeof(*tag) + ((i >> 4) % 7) * 16);
        *tag = i;
        lua_pushvalue(L, 1);
        lua_setmetatable(L, -2);
        if (i % 4 == 0)
            lua_rawseti(L, 2, i / 4);
        else
            lua_pop(L, 1);
    }
    lua_gc(L, LUA_GCSETSTEPMUL, 1);
    last_finalized = count + 1;
    LARGE_INTEGER frequency;
    QueryPerformanceFrequency(&frequency);
    double atomic_step = 0.0;
    do
    {
        const int state = g->gc.state;
        LARGE_INTEGER before, after;
        QueryPerformanceCounter(&before);
        lua_gc(L, LUA_GCSTEP, 0);
        QueryPerformanceCounter(&after);
        if (state < GCSsweepstring && g->gc.state >= GCSsweepstring)
            atomic_step = (double)(after.QuadPart - before.QuadPart) * 1000.0 / frequency.QuadPart;
    } while (g->gc.state != GCSpause);
    if (atomic_step <= 0 || finalized != count - count / 4)
        abort();
    printf("%u %.6f %u\n", count, atomic_step, finalized);
    closing = 1;
    last_finalized = count + 1;
    lua_pop(L, 2);
    lua_close(L);
    if (finalized != count)
        abort();
    return 0;
}
