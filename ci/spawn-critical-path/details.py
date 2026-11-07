"""Parallelize the complete first detail-grid expansion, preserving slot and RNG order."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1]) / "src/Layers/xrRender"
bundle = Path(__file__).resolve().parent

def update(name, changes):
    file = root / name
    original = file.read_bytes()
    normalized = original.replace(b"\r\n", b"\n")
    text = normalized.decode("utf-8")
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError((name, before[:80], text.count(before)))
        text = text.replace(before, after, 1)
    result = text.encode("utf-8")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        result = result.replace(b"\n", b"\r\n")
    file.write_bytes(result)

update("DetailManager.h", [
    ("\tint\t\t\t\t\t\t\t\tcache_cz;", "\tint\t\t\t\t\t\t\t\tcache_cz;\n\tbool cache_first_update = true;"),
    ("void\t\t\t\t\t\t\tcache_Decompress(Slot* D);",
     "void\t\t\t\t\t\t\tcache_Decompress(Slot* D, xr_vector<CDetail::SlotItem*>* windOrder = nullptr);"),
])

update("DetailManager_CACHE.cpp", [
    ('#include "DetailManager.h"', '''#include "DetailManager.h"

#if defined(IXR_WINDOWS) && !defined(_EDITOR) && !defined(DEBUG)
#include "DetailGridShift.h"
#include <ppl.h>
#include <xmmintrin.h>
#include <cstdlib>

namespace
{
bool DetailBatchEnabled()
{
    static const bool enabled = [] {
        const char* setting = std::getenv("IXRAY_DETAIL_BATCH");
        return !setting || xr_strcmp(setting, "0") != 0;
    }();
    return enabled;
}

struct DetailFloatMode
{
    explicit DetailFloatMode(unsigned mode) { _mm_setcsr(mode); }
    ~DetailFloatMode() { _mm_setcsr(previous); }
    const unsigned previous = _mm_getcsr();
};
}
#endif'''),
    ("\t// Centroid\n\tcache_cx", "\tcache_first_update = true;\n\t// Centroid\n\tcache_cx"),
    ("\t// *****\tCache shift\n\t{", '''#if defined(IXR_WINDOWS) && !defined(_EDITOR) && !defined(DEBUG)
    const bool initialBatch = cache_first_update && DetailBatchEnabled() &&
        !ps_r2_ls_flags.test(R2FLAG_FAST_DETAILS_UPDATE) && cache_task.size() == dm_cache_size;
    if (initialBatch && DetailGridShift::CoversGrid(cache_cx, cache_cz, v_x, v_z, dm_cache_line))
    {
        // Every slot is pending and the old shift visits every slot at least once.
        // Keep the exact final slot permutation and the untouched pending order.
        DetailGridShift::Rotate(cache, std::int64_t(v_x) - cache_cx, std::int64_t(v_z) - cache_cz);
        cache_cx = v_x;
        cache_cz = v_z;
        for (u32 z = 0; z < dm_cache_line; ++z)
            for (u32 x = 0; x < dm_cache_line; ++x)
                cache_Task(x, z, cache[z][x]);
    }
    else
#endif
\t// *****\tCache shift
\t{'''),
    ("\t// Task performer\n\t{", '''#if defined(IXR_WINDOWS) && !defined(_EDITOR) && !defined(DEBUG)
    if (initialBatch)
    {
        PROF_EVENT("Initial detail batch");
        const auto ownerFloatMode = _mm_getcsr();
        constexpr size_t slotsPerBlock = 16;
        const size_t count = cache_task.size();
        xr_vector<xr_vector<CDetail::SlotItem*>> windOrders(count);
        concurrency::parallel_for(size_t{0}, (count + slotsPerBlock - 1) / slotsPerBlock, [&](size_t block) {
            const DetailFloatMode floatMode(ownerFloatMode);
            const size_t end = std::min(count, (block + 1) * slotsPerBlock);
            for (size_t i = block * slotsPerBlock; i < end; ++i)
                cache_Decompress(cache_task[count - 1 - i], &windOrders[i]);
        });
        // Replay the old reverse-slot order and each slot's original z/x traversal.
        // Workers only draw from per-slot generators. The global generator stays here.
        for (const auto& order : windOrders)
            for (auto* item : order)
                item->vis_ID = Random.randI(1, 3);
        cache_task.clear();
    }
    else
#endif
\t// Task performer
\t{'''),
    ("    if (bNeedMegaUpdate)", "    cache_first_update = false;\n\n    if (bNeedMegaUpdate)"),
])

update("DetailManager_Decompress.cpp", [
    ("void\t\tCDetailManager::cache_Decompress(Slot* S)",
     "void\t\tCDetailManager::cache_Decompress(Slot* S, xr_vector<CDetail::SlotItem*>* windOrder)"),
    ("\txrc.box_options\t\t(CDB::OPT_FULL_TEST); ",
     "\tstatic thread_local xrXRC workerCollider;\n\tauto& collider = windOrder ? workerCollider : xrc;\n"
     "\tcollider.box_options\t\t(CDB::OPT_FULL_TEST); "),
    ("\txrc.box_query", "\tcollider.box_query"),
    ("xrc.r_count\t()", "collider.r_count\t()"),
    ("xrc.r_begin()", "collider.r_begin()"),
    ("\t\t\tif (Dobj.m_Flags.is(DO_NO_WAVING))\n\t\t\t\tItem.vis_ID = 0;",
     "\t\t\tconst bool animated = !Dobj.m_Flags.is(DO_NO_WAVING);\n"
     "\t\t\tif (!animated || windOrder)\n\t\t\t\tItem.vis_ID = 0;"),
    ("\t\t\tD.G[index].items.emplace_back(xr_make_shared<CDetail::SlotItem>(Item));",
     '''\t\t\tconst auto& stored = D.G[index].items.emplace_back(xr_make_shared<CDetail::SlotItem>(Item));
#ifndef DBG_SWITCHOFF_RANDOMIZE
\t\t\tif (windOrder && animated)
\t\t\t\twindOrder->push_back(stored.get());
#endif'''),
])
shutil.copyfile(bundle / "DetailGridShift.h", root / "DetailGridShift.h")
