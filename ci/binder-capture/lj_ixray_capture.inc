#include "lj_ixray_capture.h"
#include "lj_bc.h"
#include "luajit.h"
#include <string.h>

#if LJ_TARGET_WINDOWS
#include <windows.h>
#else
#include <time.h>
#endif

IX_THREAD_LOCAL IxBinderRecord *ix_capture;
static IX_THREAD_LOCAL uintptr_t ix_last_global;
static IX_THREAD_LOCAL uint32_t ix_status[4];

enum { IX_METHODS = 512, IX_METHOD_HASH = 1024 };
typedef struct IxMethodKey {
  const char *class_name, *method_name;
  unsigned overload, generation;
} IxMethodKey;
static IX_THREAD_LOCAL IxMethodKey ix_method_keys[IX_METHODS];
static IX_THREAD_LOCAL IxMethodInfo ix_method_info[IX_METHODS];
static IX_THREAD_LOCAL uint16_t ix_method_hash[IX_METHOD_HASH];
static IX_THREAD_LOCAL unsigned ix_method_count;
static volatile uint32_t ix_tag_gate;

LUA_API const volatile uint32_t *xrBinderCaptureTagGate(void)
{
  return &ix_tag_gate;
}


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
  record->qpc_queries++;
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
  return ix_capture->execution == IX_VM ? -1 : ix_capture_enter(IX_VM);
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
    ix_tag_gate = 0;
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

static IxNativeSite *ix_capture_site(IxBinderRecord *record, uintptr_t address, unsigned method)
{
  unsigned cell = (unsigned)((address >> 3) ^ (address >> 12) ^
                             (record->phase * 37u) ^ (method * 61u)) & (IX_NATIVE_HASH - 1);
  IxNativeSite *site;
  while (record->native_hash[cell]) {
    site = &record->native[record->native_hash[cell] - 1];
    if (site->address == address && site->phase == record->phase && site->method == method)
      return site;
    cell = (cell + 1) & (IX_NATIVE_HASH - 1);
  }
  if (record->address_count == IX_NATIVE_SITES) {
    record->flags |= IX_NATIVE_OVERFLOW;
    return NULL;
  }
  site = &record->native[record->address_count++];
  memset(site, 0, sizeof(*site));
  record->native_hash[cell] = (uint16_t)record->address_count;
  site->address = address;
  site->phase = record->phase;
  site->method = method;
  return site;
}

static void ix_copy_label(char *to, size_t size, const char *from)
{
  size_t length = strlen(from);
  if (length >= size) length = size - 1;
  memcpy(to, from, length);
  to[length] = 0;
}

static unsigned ix_capture_method(const char *class_name, const char *method_name, unsigned overload)
{
  unsigned cell = (unsigned)(((uintptr_t)class_name >> 3) ^ ((uintptr_t)method_name >> 4) ^
                              (overload * 23u)) & (IX_METHOD_HASH - 1);
  while (ix_method_hash[cell]) {
    unsigned id = ix_method_hash[cell];
    const IxMethodKey *key = &ix_method_keys[id - 1];
    if (key->class_name == class_name && key->method_name == method_name &&
        key->overload == overload && key->generation == ix_capture->vm_generation)
      return id;
    cell = (cell + 1) & (IX_METHOD_HASH - 1);
  }
  if (ix_method_count == IX_METHODS) {
    ix_capture->flags |= IX_NATIVE_OVERFLOW;
    return 0;
  }
  ix_method_keys[ix_method_count].class_name = class_name;
  ix_method_keys[ix_method_count].method_name = method_name;
  ix_method_keys[ix_method_count].overload = overload;
  ix_method_keys[ix_method_count].generation = ix_capture->vm_generation;
  ix_copy_label(ix_method_info[ix_method_count].class_name,
                sizeof(ix_method_info[ix_method_count].class_name), class_name);
  ix_copy_label(ix_method_info[ix_method_count].method_name,
                sizeof(ix_method_info[ix_method_count].method_name), method_name);
  ix_method_info[ix_method_count].overload = overload;
  ix_method_hash[cell] = (uint16_t)++ix_method_count;
  return ix_method_count;
}

LUA_API void xrBinderCaptureTagNative(lua_State *L, const char *class_name,
                                     const char *method_name, unsigned overload)
{
  IxBinderRecord *record = ix_capture;
  IxNativeSite *site;
  unsigned method;
  if (!record || record->execution != IX_EXTERNAL || !record->native_cursor ||
      record->global != (uintptr_t)G(L) || record->flags & IX_NONLOCAL_EXIT)
    return;
  method = ix_capture_method(class_name, method_name, overload);
  if (!method) return;
  ix_capture_account(record, ix_capture_clock());
  site = ix_capture_site(record, record->native[record->native_cursor - 1].address, method);
  record->native_cursor = site ? (unsigned)(site - record->native) + 1 : 0;
  if (site) site->measure.count++;
}

LUA_API const IxMethodInfo *xrBinderCaptureMethods(unsigned *count)
{
  *count = ix_method_count;
  return ix_method_info;
}

static int ix_capture_wrap(lua_State *L, lua_CFunction function)
{
  IxBinderRecord *record = ix_capture;
  IxNativeSite *site;
  unsigned outer;
  uint64_t before = 0, started;
  int result, previous;
  if (!record || record->flags & IX_NONLOCAL_EXIT) return function(L);
  if (record->global != (uintptr_t)G(L)) {
    record->flags |= IX_DIFFERENT_VM;
    return function(L);
  }
  outer = record->native_cursor;
  {
    unsigned slot = ((uintptr_t)function >> 4) & (IX_FIRST_FUNCTIONS - 1);
    unsigned call = ++record->native_seen;
    if (record->first_functions[slot] &&
        ((call + (unsigned)record->scope) & (IX_NATIVE_PERIOD - 1)) != 0) {
      /* Keep the unmeasured C body in the explicit VM/other residual. A skipped
         method must not replace its sampled caller's Luabind identity. */
      if (!outer) return function(L);
      record->native_cursor = 0;
      ix_tag_gate = 0;
      result = function(L);
      if (!(record->flags & IX_NONLOCAL_EXIT)) {
        record->native_cursor = outer;
        ix_tag_gate = 1;
      }
      return result;
    }
    record->first_functions[slot] = (uintptr_t)function;
    record->native_sampled++;
  }
  previous = ix_capture_enter(IX_EXTERNAL);
  started = record->last;
  site = ix_capture_site(record, (uintptr_t)function, 0);
  if (site) {
    site->measure.count++;
    before = site->measure.ticks;
  }
  if (outer) record->native[outer - 1].measure.interrupted++;
  record->native_cursor = site ? (unsigned)(site - record->native) + 1 : 0;
  ix_tag_gate = record->native_cursor != 0;
  result = function(L);
  if (!(record->flags & IX_NONLOCAL_EXIT)) {
    ix_capture_leave(previous);
    record->native_cursor = outer;
    ix_tag_gate = outer != 0;
    if (site) {
      site->inclusive += record->last - started;
      if (outer != (unsigned)(site - record->native) + 1 && site->measure.ticks - before > site->measure.longest)
        site->measure.longest = site->measure.ticks - before;
    }
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
      g->bc_cfunc_ext = BCINS_AD(BC_FUNCC, 0, 0);
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
  ix_tag_gate = next && next->native_cursor;
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
    if (!previous) next->qpc_queries++;
  }
  if (previous) previous->end = now;
  if (G(L)->wrapf == (lua_CFunction)ix_capture_wrap)
    G(L)->bc_cfunc_ext = BCINS_AD(next && next->phase != 8 ? BC_FUNCCW : BC_FUNCC, 0, 0);
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
    if (record->phase != (unsigned)phase)
      memset(record->first_functions, 0, sizeof(record->first_functions));
    record->phase = (unsigned)phase;
    if (phase == 8) record->native_untimed_phases |= 1u << phase;
    if (G(L)->wrapf == (lua_CFunction)ix_capture_wrap)
      G(L)->bc_cfunc_ext = BCINS_AD(phase == 8 ? BC_FUNCC : BC_FUNCCW, 0, 0);
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
