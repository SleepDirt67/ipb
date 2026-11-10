#define _POSIX_C_SOURCE 200809L
#include "lua.h"
#include "lauxlib.h"
#include "lualib.h"
#include <math.h>
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
    static double ms_per_tick;
    LARGE_INTEGER value;
    if (ms_per_tick == 0) {
        if (!QueryPerformanceFrequency(&value)) abort();
        ms_per_tick = 1000.0 / (double)value.QuadPart;
    }
    if (!QueryPerformanceCounter(&value)) abort();
    return (double)value.QuadPart * ms_per_tick;
#else
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) abort();
    return 1e3 * ts.tv_sec + 1e-6 * ts.tv_nsec;
#endif
}
static int compare(const void *a, const void *b)
{
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static unsigned finalized;
static int on_gc(lua_State *L)
{
    if (!lua_isuserdata(L, 1)) abort();
    ++finalized;
    return 0;
}
static void fill(lua_State *L, unsigned count, unsigned offset, int into)
{
    for (unsigned j = 0; j < count; ++j) {
        unsigned *cell = (unsigned *)lua_newuserdata(L, 32);
        *cell = j + offset;
        lua_pushvalue(L, 1);
        lua_setmetatable(L, -2);
        lua_rawseti(L, into, (int)(j + offset));
    }
}
static void bind_batch(lua_State *L, unsigned frame, unsigned churn)
{
    lua_createtable(L, 569 * 10, 0);
    const int batch = lua_gettop(L);
    for (unsigned npc = 0; npc < 10; ++npc) {
        for (unsigned theme = 0; theme < 569; ++theme) {
            lua_createtable(L, 2, 0);
            lua_pushinteger(L, (lua_Integer)(theme + frame * 569));
            lua_rawseti(L, -2, 1);
            lua_createtable(L, 3, 0);
            lua_pushstring(L, "characters_voice\\cohort\\contact1");
            lua_rawseti(L, -2, 1);
            lua_pushstring(L, "characters_voice\\cohort\\contact2");
            lua_rawseti(L, -2, 2);
            lua_rawseti(L, -2, 2);
            lua_rawseti(L, batch, (int)(1 + npc * 569 + theme));
        }
        fill(L, churn / 10, 1 + npc * (churn / 10) + 569 * 10, batch);
    }
    lua_rawseti(L, 3, 1 + (int)(frame % 5));
}
int main(int argc, char **argv)
{
    enum { Frames = 100, Full = 45 };
    if (argc != 4 && argc != 5) return 1;
    const unsigned live = (unsigned)atoi(argv[1]);
    const unsigned churn = (unsigned)atoi(argv[2]);
    const int pause = atoi(argv[3]);
    const unsigned tables = argc == 5 ? (unsigned)atoi(argv[4]) : 0;
    double frame_ms[Frames], full_ms[Full];
    lua_State *L = luaL_newstate();
    if (!L) abort();
    luaL_openlibs(L);
    lua_gc(L, LUA_GCSTOP, 0);
    lua_createtable(L, 0, 1);
    lua_pushcfunction(L, on_gc);
    lua_setfield(L, 1, "__gc");
    lua_createtable(L, (int)live, 0);
    lua_createtable(L, 5, 0);
    fill(L, live, 1, 2);
    lua_createtable(L, (int)tables, 0);
    for (unsigned i = 1; i <= tables; ++i) {
        lua_createtable(L, 2, 1);
        lua_pushinteger(L, (lua_Integer)i);
        lua_rawseti(L, -2, 1);
        lua_createtable(L, 2, 0);
        lua_pushinteger(L, (lua_Integer)i + 1);
        lua_rawseti(L, -2, 1);
        lua_rawseti(L, -2, 2);
        lua_rawseti(L, 4, (int)i);
    }
    for (unsigned i = 1; i <= tables; i += 3) {
        lua_pushnil(L);
        lua_rawseti(L, 4, (int)i);
    }
    lua_gc(L, LUA_GCCOLLECT, 0);
    lua_gc(L, LUA_GCSETPAUSE, pause);
    lua_gc(L, LUA_GCRESTART, 0);
    for (unsigned i = 0; i < Frames; ++i) {
        const double start = now();
        bind_batch(L, i, churn);
        frame_ms[i] = now() - start;
    }
    lua_gc(L, LUA_GCSTOP, 0);
    for (unsigned i = 0; i < Full; ++i) {
        lua_createtable(L, (int)churn, 0);
        fill(L, churn, 1, 5);
        lua_pop(L, 1);
        const double start = now();
        lua_gc(L, LUA_GCCOLLECT, 0);
        full_ms[i] = now() - start;
    }
    if (tables >= 2) {
        lua_rawgeti(L, 4, 2);
        lua_rawgeti(L, -1, 2);
        lua_rawgeti(L, -1, 1);
        if (lua_tointeger(L, -1) != 3) abort();
        lua_pop(L, 3);
    }
    const int kib = lua_gc(L, LUA_GCCOUNT, 0);
    lua_close(L);
    const unsigned expected = live + (churn / 10 * 10) * Frames + churn * Full;
    if (finalized != expected) {
        fprintf(stderr, "Finalized %u, expected %u\n", finalized, expected);
        return 1;
    }
    qsort(frame_ms, Frames, sizeof(double), compare);
    qsort(full_ms, Full, sizeof(double), compare);
    printf("live=%u tables=%u churn=%u pause=%d, binder %.3f median / %.3f p95 / %.3f max, full %.3f median / %.3f p95 / %.3f max, %.1f MiB\n",
           live, tables, churn, pause, (frame_ms[49] + frame_ms[50]) / 2, frame_ms[94], frame_ms[99],
           full_ms[22], full_ms[42], full_ms[Full-1], kib / 1024.);
    return 0;
}
