#include "lj_ixray_capture.h"
#include "lj_bc.h"
#include "luajit.h"

#if LJ_TARGET_WINDOWS
#include <windows.h>
#else
#include <time.h>
#endif

IX_THREAD_LOCAL IxBinderRecord *ix_capture;
static IX_THREAD_LOCAL uintptr_t ix_last_global;
static IX_THREAD_LOCAL uint32_t ix_status[4];

uint64_t ix_capture_clock(void)
{
#if LJ_TARGET_WINDOWS
  LARGE_INTEGER now;
  QueryPerformanceCounter(&now);
  return (uint64_t)now.QuadPart;
#else
  struct timespec now;
  clock_gettime(CLOCK_MONOTONIC, &now);
  return (uint64_t)now.tv_sec * 1000000000 + now.tv_nsec;
#endif
}

void ix_capture_account(IxBinderRecord *record, uint64_t now)
{
  uint64_t elapsed;
  if (now < record->last) {
    record->flags |= IX_BAD_CLOCK;
    return;
  }
  elapsed = now - record->last;
  record->ticks[record->phase][record->execution] += elapsed;
  if (record->execution == IX_GC)
    record->gc[record->gc_stage].ticks += elapsed;
  else if (record->execution == IX_EXTERNAL && record->native_cursor)
    record->native[record->native_cursor - 1].measure.ticks += elapsed;
  record->last = now;
}

static int ix_capture_enter(unsigned execution)
{
  IxBinderRecord *record = ix_capture;
  int previous = record->execution;
  ix_capture_account(record, ix_capture_clock());
  record->execution = execution;
  return previous;
}

static void ix_capture_leave(int previous)
{
  if (previous < 0 || !ix_capture) return;
  ix_capture_account(ix_capture, ix_capture_clock());
  ix_capture->execution = (unsigned)previous;
}

int ix_capture_enter_vm(lua_State *L)
{
  if (!ix_capture || ix_capture->flags & IX_NONLOCAL_EXIT) return -1;
  if (ix_capture->global != (uintptr_t)G(L)) {
    ix_capture->flags |= IX_DIFFERENT_VM;
    return -1;
  }
  return ix_capture_enter(IX_VM);
}

void ix_capture_leave_vm(int previous)
{
  ix_capture_leave(previous);
}

int ix_capture_gc_stage(unsigned stage)
{
  IxBinderRecord *record = ix_capture;
  int previous;
  if (!record || record->flags & IX_NONLOCAL_EXIT) return -1;
  previous = (int)(record->execution * IX_GC_STAGES + record->gc_stage);
  if (record->execution != IX_GC || record->gc_stage != stage) {
    ix_capture_account(record, ix_capture_clock());
    if (record->execution == IX_GC) record->gc[record->gc_stage].interrupted++;
    record->execution = IX_GC;
    record->gc_stage = stage;
    record->gc[stage].count++;
  }
  return previous;
}

void ix_capture_gc_restore(int previous)
{
  IxBinderRecord *record = ix_capture;
  if (previous < 0 || !record ||
      previous == (int)(record->execution * IX_GC_STAGES + record->gc_stage)) return;
  ix_capture_account(record, ix_capture_clock());
  record->execution = (unsigned)previous / IX_GC_STAGES;
  record->gc_stage = (unsigned)previous % IX_GC_STAGES;
}

void ix_capture_gc_cycle(void)
{
  if (ix_capture) ix_capture->gc_cycles++;
}

void ix_capture_bad_exit(lua_State *L)
{
  if (ix_capture && ix_capture->global == (uintptr_t)G(L)) {
    ix_capture_account(ix_capture, ix_capture_clock());
    ix_capture->flags |= IX_NONLOCAL_EXIT;
    ix_capture->execution = IX_HOST;
    ix_capture->native_cursor = 0;
  }
}

void ix_capture_allocation(global_State *g, GCSize before, GCSize after)
{
  IxBinderRecord *record = ix_capture;
  if (!record || record->global != (uintptr_t)g) return;
  record->allocation_calls++;
  if (before < after) record->allocated += after - before;
  else record->released += before - after;
}

static int ix_capture_wrap(lua_State *L, lua_CFunction function)
{
  IxBinderRecord *record = ix_capture;
  IxNativeSite *site = NULL;
  unsigned outer = record ? record->native_cursor : 0;
  uintptr_t address = (uintptr_t)function;
  uint64_t before = 0;
  int result, previous;
  unsigned i;
  if (!record || record->flags & IX_NONLOCAL_EXIT) return function(L);
  if (record->global != (uintptr_t)G(L)) {
    record->flags |= IX_DIFFERENT_VM;
    return function(L);
  }
  previous = ix_capture_enter(IX_EXTERNAL);
  for (i = 0; i < record->address_count; i++) {
    if (record->native[i].address == address && record->native[i].phase == record->phase) {
      site = &record->native[i];
      break;
    }
  }
  if (!site && record->address_count < IX_NATIVE_SITES) {
    site = &record->native[record->address_count++];
    site->address = address;
    site->phase = record->phase;
  }
  if (site) {
    site->measure.count++;
    before = site->measure.ticks;
  } else {
    record->flags |= IX_NATIVE_OVERFLOW;
  }
  if (outer) record->native[outer - 1].measure.interrupted++;
  record->native_cursor = site ? (unsigned)(site - record->native) + 1 : 0;
  result = function(L);
  if (!(record->flags & IX_NONLOCAL_EXIT)) {
    ix_capture_leave(previous);
    record->native_cursor = outer;
    if (site && record->native_cursor != (unsigned)(site - record->native) + 1 && site->measure.ticks - before > site->measure.longest)
      site->measure.longest = site->measure.ticks - before;
  }
  return result;
}

/* This is installed only on diagnostic VMs. An existing wrapper owns its slot. */
LUA_API int xrBinderCaptureInstall(lua_State *L)
{
  global_State *g = G(L);
  if (bc_op(g->bc_cfunc_ext) == BC_FUNCCW) {
    ix_status[1]++;
    return 0;
  }
  lua_pushlightuserdata(L, (void *)ix_capture_wrap);
  {
    int result = luaJIT_setmode(L, -1, LUAJIT_MODE_WRAPCFUNC | LUAJIT_MODE_ON);
    lua_pop(L, 1);
    if (result) {
      ix_last_global = (uintptr_t)g;
      ix_status[0]++;
    } else {
      ix_status[1]++;
    }
    return result;
  }
}

/* Exchange contexts at an engine scope boundary. */
LUA_API void *xrBinderCaptureContext(lua_State *L, void *context)
{
  IxBinderRecord *previous = ix_capture;
  IxBinderRecord *next = (IxBinderRecord *)context;
  uint64_t now = ix_capture_clock();
  if (previous) {
    ix_capture_account(previous, now);
    if (previous->global == (uintptr_t)G(L)) previous->heap_after = G(L)->gc.total;
  }
  ix_capture = next;
  if (next) {
    if (!next->global) {
      next->global = (uintptr_t)G(L);
      next->heap_before = G(L)->gc.total;
      if (next->global == ix_last_global && G(L)->wrapf == (lua_CFunction)ix_capture_wrap)
        next->vm_generation = ix_status[0];
      else
        next->flags |= IX_NO_VM;
    } else if (next->global != (uintptr_t)G(L)) {
      next->flags |= IX_DIFFERENT_VM;
    }
    next->last = now;
  }
  if (previous) previous->end = now;
  return previous;
}

static int ix_capture_mark(lua_State *L)
{
  IxBinderRecord *record = ix_capture;
  int phase;
  if (!record || record->global != (uintptr_t)G(L)) return 0;
  phase = (int)lua_tointeger(L, 1);
  if (phase > 0 && phase < IX_PHASES) {
    ix_capture_account(record, ix_capture_clock());
    record->phase = (unsigned)phase;
    record->marks |= 1u << phase;
  }
  return 0;
}

LUA_API void xrBinderCaptureRegister(lua_State *L)
{
  lua_pushcfunction(L, ix_capture_mark);
  lua_setglobal(L, "__ixray_binder_capture_phase");
}

LUA_API void xrBinderCaptureStatus(uint32_t *out, int script_result)
{
  unsigned i;
  if (script_result == 1) ix_status[2]++;
  if (script_result == -1) ix_status[3]++;
  if (out)
    for (i = 0; i < 4; ++i) out[i] = ix_status[i];
}
