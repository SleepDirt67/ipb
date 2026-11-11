#ifndef IXRAY_BINDER_CAPTURE_FORMAT_H
#define IXRAY_BINDER_CAPTURE_FORMAT_H

#include <stdint.h>

enum { IX_PHASES = 12, IX_NATIVE_SITES = 96, IX_GC_STAGES = 16, IX_NATIVE_HASH = 128,
       IX_FIRST_FUNCTIONS = 16, IX_NATIVE_PERIOD = 64 };
enum IxExecution { IX_HOST, IX_VM, IX_EXTERNAL, IX_GC, IX_EXECUTION_COUNT };
enum IxGcStage {
  IX_GC_ROOTS, IX_GC_PROPAGATE, IX_GC_ATOMIC, IX_GC_SWEEP_STRINGS,
  IX_GC_SWEEP, IX_GC_FINALIZE, IX_GC_OVERHEAD, IX_GC_OPEN_UPVALUES,
  IX_GC_REMARK_ROOTS, IX_GC_GRAYAGAIN, IX_GC_SEPARATE_USERDATA,
  IX_GC_CLEAR_WEAK, IX_GC_SHRINK
};
enum IxRecordFlags {
  IX_NONLOCAL_EXIT = 1, IX_NATIVE_OVERFLOW = 2, IX_MARKER_MISSING = 4,
  IX_DIFFERENT_VM = 8, IX_BAD_CLOCK = 16, IX_NO_VM = 32
};

typedef struct IxTally {
  uint64_t ticks, longest;
  uint32_t count, interrupted;
} IxTally;

typedef struct IxNativeSite {
  uint64_t address, inclusive;
  IxTally measure;
  uint32_t phase, method;
} IxNativeSite;

typedef struct IxBinderRecord {
  uint64_t begin, end, scope, parent_scope, dispatch, last, global;
  uint64_t allocated, released, allocation_calls, heap_before, heap_after;
  uint32_t frame, tid, vm_generation, object, generation, kind, flags;
  uint32_t phase, execution, gc_stage, gc_cycles, marks, address_count;
  uint32_t native_cursor, native_seen, native_sampled, qpc_queries;
  uint32_t reserved;
  uint64_t ticks[IX_PHASES][IX_EXECUTION_COUNT];
  IxTally gc[IX_GC_STAGES];
  IxNativeSite native[IX_NATIVE_SITES];
  uint16_t native_hash[IX_NATIVE_HASH];
  uint64_t first_functions[IX_FIRST_FUNCTIONS];
} IxBinderRecord;

typedef struct IxDispatchRecord {
  uint64_t begin, end, scope, parent_scope, queue, class_id;
  uint32_t frame, tid, object, generation, parent_object, parent_generation;
  uint32_t stalker, result;
  char section[96];
} IxDispatchRecord;

typedef struct IxMethodInfo {
  char class_name[48], method_name[64];
  uint32_t overload;
} IxMethodInfo;

typedef struct IxEpisodeRecord {
  uint64_t begin, end, copy_ticks;
  uint32_t binders, dispatches, binder_dropped, dispatch_dropped, invalid, slot;
} IxEpisodeRecord;

typedef struct IxCaptureHeader {
  char magic[8];
  uint64_t frequency, active_ticks, observation_begin, observation_end, save_loaded;
  uint32_t pid, binders, dispatches, binder_dropped, dispatch_dropped;
  uint32_t wrapper_installs, wrapper_refused, script_matches, script_misses;
  uint32_t stop_reason, strong, large, binder_size, dispatch_size, episodes, methods;
} IxCaptureHeader;
#endif
