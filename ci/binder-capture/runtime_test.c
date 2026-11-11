#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
#include <luajit.h>
#include "BinderCaptureFormat.h"

#if defined(_WIN32)
#include <windows.h>
static HMODULE library;
#define lookup(name) GetProcAddress(library, name)
#else
#include <dlfcn.h>
static void *library;
#define lookup(name) dlsym(library, name)
#endif

#define REQUIRE(condition) do { if (!(condition)) { \
  fprintf(stderr, "%s at line %d\n", #condition, __LINE__); return 1; } } while (0)

static void (*tag)(lua_State *, const char *, const char *, unsigned);

static int invoke(lua_State *L)
{
  tag(L, "fixture", "invoke", 2);
  lua_pushvalue(L, 1);
  lua_call(L, 0, 1);
  return 1;
}

static int other_wrapper(lua_State *L, lua_CFunction function)
{
  return function(L);
}

#if defined(_WIN32)
struct Witness {
  HANDLE wake, done;
  unsigned work;
};

static DWORD WINAPI witness_worker(void *parameter)
{
  struct Witness *data = (struct Witness *)parameter;
  unsigned i;
  for (i = 0; i < 12; ++i) {
    if (WaitForSingleObject(data->wake, 3000) != WAIT_OBJECT_0) return 1;
    InterlockedIncrement((volatile LONG *)&data->work);
    SetEvent(data->done);
  }
  return 0;
}

static int etw_witness(void)
{
  struct Witness data = {0};
  HANDLE thread;
  LARGE_INTEGER begin, end, frequency;
  unsigned i;
  data.wake = CreateEventW(NULL, FALSE, FALSE, NULL);
  data.done = CreateEventW(NULL, FALSE, FALSE, NULL);
  REQUIRE(data.wake && data.done);
  thread = CreateThread(NULL, 0, witness_worker, &data, 0, NULL);
  REQUIRE(thread);
  for (i = 0; i < 12; ++i) {
    Sleep(8);
    SetEvent(data.wake);
    REQUIRE(WaitForSingleObject(data.done, 3000) == WAIT_OBJECT_0);
  }
  REQUIRE(WaitForSingleObject(thread, 3000) == WAIT_OBJECT_0 && data.work == 12);
  CloseHandle(thread);
  CloseHandle(data.wake);
  CloseHandle(data.done);
  QueryPerformanceFrequency(&frequency);
  QueryPerformanceCounter(&begin);
  do { QueryPerformanceCounter(&end); } while (end.QuadPart - begin.QuadPart < frequency.QuadPart / 20);
  printf("%lu\n", GetCurrentThreadId());
  return 0;
}

static int calibrate(void)
{
  LARGE_INTEGER start, end, stamp, frequency;
  volatile uint64_t ticks = 0;
  unsigned i, pair;
  QueryPerformanceFrequency(&frequency);
  for (pair = 0; pair != 9; ++pair) {
    QueryPerformanceCounter(&start);
    for (i = 0; i < 100000; ++i) {
      QueryPerformanceCounter(&stamp);
      ticks += (uint64_t)stamp.QuadPart;
    }
    QueryPerformanceCounter(&end);
    printf("qpc_loop_ns=%.3f\n", 1e9 * (end.QuadPart - start.QuadPart) / (100000 * (double)frequency.QuadPart));
  }
  return ticks == 0;
}
#endif

int main(int argc, char **argv)
{
  lua_State *L, *foreign;
  int (*install)(lua_State *);
  void (*register_marker)(lua_State *);
  void (*status)(uint32_t *, int);
  void *(*exchange)(lua_State *, void *);
  const IxMethodInfo *(*methods)(unsigned *);
  IxBinderRecord record, second;
  uint32_t counts[4] = {0};
  uint64_t ticks = 0, gc = 0, gc_by_stage = 0, native = 0;
  unsigned i, j, method_count;
  const IxMethodInfo *method_info;

#if defined(_WIN32)
  if (argc == 2 && strcmp(argv[1], "--etw-witness") == 0) return etw_witness();
  if (argc == 2 && strcmp(argv[1], "--calibrate") == 0) return calibrate();
#endif
  if (argc != 1) return 2;
  (void)argv;
  L = luaL_newstate();
#if defined(_WIN32)
  library = GetModuleHandleW(L"lua51.dll");
#else
  library = dlopen(NULL, RTLD_NOW);
#endif
  REQUIRE(L && library);
  install = (int (*)(lua_State *))lookup("xrBinderCaptureInstall");
  register_marker = (void (*)(lua_State *))lookup("xrBinderCaptureRegister");
  status = (void (*)(uint32_t *, int))lookup("xrBinderCaptureStatus");
  exchange = (void *(*)(lua_State *, void *))lookup("xrBinderCaptureContext");
  tag = (void (*)(lua_State *, const char *, const char *, unsigned))lookup("xrBinderCaptureTagNative");
  methods = (const IxMethodInfo *(*)(unsigned *))lookup("xrBinderCaptureMethods");
  REQUIRE(install && register_marker && status && exchange && tag && methods);

  luaL_openlibs(L);
  REQUIRE(install(L) == 1);
  register_marker(L);
  lua_pushcfunction(L, invoke);
  lua_setglobal(L, "invoke");

  REQUIRE(luaL_loadstring(L, "local a = {}; "
      "__ixray_binder_capture_phase(4); "
      "return invoke(function() "
      " for i=1,30000 do a[i]={i} end; "
      " collectgarbage('collect'); return #a end)") == 0);
  memset(&record, 0, sizeof(record));
  REQUIRE(exchange(L, &record) == NULL);
  record.begin = record.last;
  REQUIRE(lua_pcall(L, 0, 1, 0) == 0);
  REQUIRE(exchange(L, NULL) == &record);
  REQUIRE(lua_tointeger(L, -1) == 30000);
  lua_pop(L, 1);
  REQUIRE(!record.flags && record.vm_generation == 1);
  REQUIRE(record.marks == (1u << 4));
  REQUIRE(record.gc_cycles > 0 && record.allocation_calls >= 30000);
  REQUIRE(record.allocated - record.released == record.heap_after - record.heap_before);
  for (i = 0; i < IX_PHASES; ++i) {
    for (j = 0; j < IX_EXECUTION_COUNT; ++j) ticks += record.ticks[i][j];
    gc += record.ticks[i][IX_GC];
    native += record.ticks[i][IX_EXTERNAL];
  }
  for (i = 0; i < IX_GC_STAGES; ++i) gc_by_stage += record.gc[i].ticks;
  REQUIRE(ticks == record.end - record.begin && gc > 0 && gc == gc_by_stage && native > 0);
  for (i = 0; i < record.address_count && record.native[i].address != (uintptr_t)invoke; ++i) {}
  REQUIRE(i < record.address_count && record.native[i].measure.count == 1);
  REQUIRE(record.ticks[4][IX_VM] > 0);
  REQUIRE(record.native[i].inclusive >= record.native[i].measure.ticks);
  method_info = methods(&method_count);
  REQUIRE(method_count == 1 && strcmp(method_info[0].class_name, "fixture") == 0 &&
          strcmp(method_info[0].method_name, "invoke") == 0 && method_info[0].overload == 2);
  for (i = 0; i < record.address_count && record.native[i].method != 1; ++i) {}
  REQUIRE(i < record.address_count && record.native[i].measure.count == 1);

  REQUIRE(luaL_loadstring(L, "return invoke(function() error('capture test') end)") == 0);
  memset(&record, 0, sizeof(record));
  exchange(L, &record);
  REQUIRE(lua_pcall(L, 0, 1, 0) != 0);
  REQUIRE(exchange(L, NULL) == &record && (record.flags & IX_NONLOCAL_EXIT));
  lua_pop(L, 1);

  REQUIRE(luaL_loadstring(L, "return coroutine.yield(7)") == 0);
  {
    lua_State *co = lua_newthread(L);
    lua_pushvalue(L, -2);
    lua_xmove(L, co, 1);
    memset(&record, 0, sizeof(record));
    exchange(L, &record);
    REQUIRE(lua_resume(co, 0) == LUA_YIELD);
    REQUIRE(exchange(L, NULL) == &record && (record.flags & IX_NONLOCAL_EXIT));
    REQUIRE(lua_tointeger(co, -1) == 7);
    lua_pop(L, 2);
  }

  memset(&record, 0, sizeof(record));
  memset(&second, 0, sizeof(second));
  REQUIRE(exchange(L, &record) == NULL);
  REQUIRE(exchange(L, &second) == &record);
  REQUIRE(exchange(L, &record) == &second);
  REQUIRE(exchange(L, NULL) == &record);
  REQUIRE(!record.flags && !second.flags);
  lua_close(L);

  foreign = luaL_newstate();
  REQUIRE(foreign);
  lua_pushlightuserdata(foreign, (void *)other_wrapper);
  REQUIRE(luaJIT_setmode(foreign, -1, LUAJIT_MODE_WRAPCFUNC | LUAJIT_MODE_ON));
  lua_pop(foreign, 1);
  REQUIRE(install(foreign) == 0);
  lua_close(foreign);

  L = luaL_newstate();
  REQUIRE(L && install(L));
  memset(&record, 0, sizeof(record));
  exchange(L, &record);
  exchange(L, NULL);
  REQUIRE(record.vm_generation == 2 && !record.flags);
  lua_close(L);

  status(counts, 1);
  REQUIRE(counts[0] == 2 && counts[1] == 1 && counts[2] == 1);
  printf("Actual LuaJIT API, reentry, error/yield, VM generations, allocator and exclusive GC passed\n");
  return 0;
}
