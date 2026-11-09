#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
#include <stdio.h>
#include <stdlib.h>

static unsigned counts[4097], next;
static int finalize(lua_State *L)
{
    unsigned id = *(unsigned *)lua_touserdata(L, 1);
    if (!id || id > 4096 || counts[id]++) abort();
    ++next;
    return 0;
}

int main(void)
{
    for (unsigned steps = 0; steps < 140; ++steps) {
        lua_State *L = luaL_newstate();
        if (!L) abort();
        luaL_openlibs(L);
        lua_gc(L, LUA_GCSTOP, 0);
        lua_newtable(L);
        lua_pushcfunction(L, finalize);
        lua_setfield(L, 1, "__gc");
        lua_createtable(L, 4096, 0);
        for (unsigned id = 1; id <= 4096; ++id) {
            *(unsigned *)lua_newuserdata(L, 32) = id;
            lua_pushvalue(L, 1);
            lua_setmetatable(L, -2);
            if (id % 3) lua_rawseti(L, 2, id);
            else lua_pop(L, 1);
            counts[id] = 0;
        }
        next = 0;
        lua_gc(L, LUA_GCSETSTEPMUL, 100);
        for (unsigned i = 0; i < steps; ++i) lua_gc(L, LUA_GCSTEP, 0);
        lua_close(L);
        if (next != 4096) {
            fprintf(stderr, "steps %u finalizers %u\n", steps, next);
            return 1;
        }
    }
    puts("140 shutdown points preserve exactly one finalization per userdata");
    return 0;
}
