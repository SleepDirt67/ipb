#ifndef LJ_IXRAY_CAPTURE_H
#define LJ_IXRAY_CAPTURE_H

#include "BinderCaptureFormat.h"
#include "lj_obj.h"

#if defined(_MSC_VER)
#define IX_THREAD_LOCAL __declspec(thread)
#else
#define IX_THREAD_LOCAL __thread
#endif

LJ_DATA IX_THREAD_LOCAL IxBinderRecord *ix_capture;
LJ_FUNC uint64_t ix_capture_clock(void);
LJ_FUNC void ix_capture_account(IxBinderRecord *record, uint64_t now);
LJ_FUNC void ix_capture_allocation(global_State *g, GCSize before, GCSize after);
LJ_FUNC int ix_capture_enter_vm(lua_State *L);
LJ_FUNC void ix_capture_leave_vm(int previous);
LJ_FUNC int ix_capture_gc_stage(unsigned stage);
LJ_FUNC void ix_capture_gc_restore(int previous);
LJ_FUNC void ix_capture_gc_cycle(void);
LJ_FUNC void ix_capture_bad_exit(lua_State *L);

#endif
