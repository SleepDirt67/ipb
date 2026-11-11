"""Instrument the exact pinned LuaJIT runtime after its production patches."""
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Unexpected LuaJIT source at {old!r}")
    return text.replace(old, new, 1)


def apply(root):
    src = root / "src"
    for name in ("BinderCaptureFormat.h", "lj_ixray_capture.h", "lj_ixray_capture.inc"):
        shutil.copyfile(HERE / name, src / name)

    dispatch = src / "lj_dispatch.c"
    dispatch.write_text(dispatch.read_text() + '\n#include "lj_ixray_capture.inc"\n')

    gc = src / "lj_gc.c"
    data = gc.read_text()
    data = replace(data, "  size_t udsize;\n", "  size_t udsize;\n  int ix_previous;\n")
    cuts = (
        ("  gc_mark_uv(g);", "IX_GC_OPEN_UPVALUES"),
        ("  setgcrefr(g->gc.gray, g->gc.weak);", "IX_GC_REMARK_ROOTS"),
        ("  setgcrefr(g->gc.gray, g->gc.grayagain);", "IX_GC_GRAYAGAIN"),
        ("  udsize = lj_gc_separateudata(g, 0);", "IX_GC_SEPARATE_USERDATA"),
        ("  gc_clearweak(g, gcref(g->gc.weak));", "IX_GC_CLEAR_WEAK"),
        ("  lj_buf_shrink(L, &g->tmpbuf);", "IX_GC_SHRINK"),
    )
    for index, (anchor, stage) in enumerate(cuts):
        assignment = "ix_previous = " if index == 0 else ""
        data = replace(data, anchor, f"  {assignment}ix_capture_gc_stage({stage});\n{anchor}")
    data = replace(data, "  /* Prepare for sweep phase. */",
                   "  ix_capture_gc_restore(ix_previous);\n\n  /* Prepare for sweep phase. */")
    data = replace(data, "  switch (g->gc.state) {",
                   """  if (ix_capture && ix_capture->gc_stage != g->gc.state)
    ix_capture_gc_stage(g->gc.state);
  switch (g->gc.state) {""")
    data = replace(data, "    gc_mark_start(g);", "    ix_capture_gc_cycle();\n    gc_mark_start(g);")
    for fn, end in (("int LJ_FASTCALL lj_gc_step(lua_State *L)", "/* Ditto,"),
                    ("void lj_gc_fullgc(lua_State *L)", "/* -- Write barriers")):
        start = data.index(fn)
        stop = data.index(end, start)
        body = data[start:stop]
        body = replace(body, "  setvmstate(g, GC);",
                       "  int ix_previous = ix_capture_gc_stage(IX_GC_OVERHEAD);\n  setvmstate(g, GC);")
        body = body.replace("g->vmstate = ostate;", "ix_capture_gc_restore(ix_previous);\n    g->vmstate = ostate;")
        data = data[:start] + body + data[stop:]
    data = replace(data, "  g->gc.total = (g->gc.total - osz) + nsz;",
                   "  if (ix_capture) ix_capture_allocation(g, osz, nsz);\n"
                   "  g->gc.total = (g->gc.total - osz) + nsz;")
    data = replace(data, "  g->gc.total += size;",
                   "  if (ix_capture) ix_capture_allocation(g, 0, size);\n  g->gc.total += size;")
    gc.write_text(data)

    header = src / "lj_gc.h"
    data = replace(header.read_text(), "/* Allocator. */",
                   '#include "lj_ixray_capture.h"\n\n/* Allocator. */')
    data = replace(data, "  g->allocf(g->allocd, p, osize, 0);",
                   "  if (ix_capture) ix_capture_allocation(g, (GCSize)osize, 0);\n"
                   "  g->allocf(g->allocd, p, osize, 0);")
    header.write_text(data)

    api = src / "lj_api.c"
    data = api.read_text()
    for call in (
        "lj_vm_call(L, api_call_base(L, nargs), nresults+1);",
        "status = lj_vm_pcall(L, api_call_base(L, nargs), nresults+1, ef);",
        "status = lj_vm_cpcall(L, func, ud, cpcall);",
    ):
        data = replace(data, "  " + call,
                       "  {\n    int ix_previous = ix_capture_enter_vm(L);\n"
                       f"    {call}\n    ix_capture_leave_vm(ix_previous);\n  }}")
    data = replace(data, "LUA_API int lua_yield(lua_State *L, int nresults)\n{",
                   "LUA_API int lua_yield(lua_State *L, int nresults)\n{\n  ix_capture_bad_exit(L);")
    data = replace(data, """  if (L->cframe == NULL && L->status <= LUA_YIELD)
    return lj_vm_resume(L,
      L->status == LUA_OK ? api_call_base(L, nargs) : L->top - nargs,
      0, 0);""", """  if (L->cframe == NULL && L->status <= LUA_YIELD) {
    int ix_previous = ix_capture_enter_vm(L);
    int result = lj_vm_resume(L,
      L->status == LUA_OK ? api_call_base(L, nargs) : L->top - nargs,
      0, 0);
    if (result == LUA_YIELD) ix_capture_bad_exit(L);
    ix_capture_leave_vm(ix_previous);
    return result;
  }""")
    api.write_text(data)

    err = src / "lj_err.c"
    data = replace(err.read_text(), '#include "lj_obj.h"', '#include "lj_obj.h"\n#include "lj_ixray_capture.h"')
    data = replace(data, "LJ_NOINLINE void LJ_FASTCALL lj_err_throw(lua_State *L, int errcode)\n{",
                   "LJ_NOINLINE void LJ_FASTCALL lj_err_throw(lua_State *L, int errcode)\n{\n"
                   "  ix_capture_bad_exit(L);")
    err.write_text(data)


if __name__ == "__main__":
    apply(Path(sys.argv[1]))
