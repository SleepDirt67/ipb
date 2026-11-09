/* Model a long-lived Lua heap and time each normal incremental API step. */
#include "lua.h"
#include "lauxlib.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif

static double now(void)
{
#ifdef _WIN32
    LARGE_INTEGER counter;
    static double scale;
    if (scale == 0) {
        if (!QueryPerformanceFrequency(&counter)) abort();
        scale = 1000.0 / (double)counter.QuadPart;
    }
    if (!QueryPerformanceCounter(&counter)) abort();
    return (double)counter.QuadPart * scale;
#else
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) abort();
    return 1e3 * ts.tv_sec + 1e-6 * ts.tv_nsec;
#endif
}

static uint32_t random_size(uint32_t *state)
{
    *state = *state * UINT32_C(1664525) + UINT32_C(1013904223);
    return 8u + ((*state >> 18) & 31u) * 16u;
}

static int finalize(lua_State *L)
{
    if (!lua_touserdata(L, 1)) abort();
    return 0;
}

static void fill(lua_State *L, int total)
{
    enum { PerGroup = 96 };
    uint32_t random = 1;
    const int groups = (total + PerGroup - 1) / PerGroup;
    lua_createtable(L, groups, 0);
    for (int group = 0; group < groups; ++group) {
        const int size = total < PerGroup ? total : PerGroup;
        lua_createtable(L, size, 0);
        for (int slot = 1; slot <= size; ++slot) {
            unsigned *live = lua_newuserdata(L, random_size(&random));
            *live = (unsigned)(group * PerGroup + slot);
            lua_pushvalue(L, 1);
            lua_setmetatable(L, -2);
            lua_rawseti(L, 3, slot);
            if (slot % 5 == 0) {
                lua_newuserdata(L, random_size(&random));
                lua_pop(L, 1);
            }
        }
        lua_rawseti(L, 2, group + 1);
        total -= size;
    }
}

int main(int argc, char **argv)
{
    if (argc != 2) return 1;
    const int count = atoi(argv[1]);
    if (count < 1 || count > 1000000) return 1;
    lua_State *L = luaL_newstate();
    if (!L) abort();
    lua_gc(L, LUA_GCSTOP, 0);
    lua_newtable(L);
    lua_pushcfunction(L, finalize);
    lua_setfield(L, 1, "__gc");
    fill(L, count);
    lua_gc(L, LUA_GCCOLLECT, 0);
    lua_gc(L, LUA_GCSETSTEPMUL, 1);
    for (unsigned cycle = 0; cycle < 7; ++cycle) {
        double longest = 0;
        unsigned steps = 0;
        const double start = now();
        for (;;) {
            const double step_start = now();
            const int done = lua_gc(L, LUA_GCSTEP, 0);
            const double elapsed = now() - step_start;
            if (elapsed > longest) longest = elapsed;
            ++steps;
            if (done) break;
            if (steps >= 3000000) abort();
        }
        printf("cycle %u live=%d longest-step %.3f ms, cycle %.3f ms, %u steps\n",
               cycle, count, longest, now() - start, steps);
    }
    lua_close(L);
    return 0;
}
