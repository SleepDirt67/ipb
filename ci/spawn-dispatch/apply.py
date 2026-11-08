"""Install the Lua sweep policy at the actual level dispatch and maintenance boundaries."""
from pathlib import Path
import shutil
import sys

bundle = Path(__file__).resolve().parent
src = Path(sys.argv[1]) / "src"

def edit(name, replacements):
    path = src / name
    original = path.read_bytes()
    crlf = b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b"")
    source = original.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError((name, before, source.count(before)))
        source = source.replace(before, after, 1)
    path.write_bytes(source.replace("\n", "\r\n" if crlf else "\n").encode("latin-1"))

shutil.copyfile(bundle / "DispatchSweep.h", src / "xrGame/DispatchSweep.h")
edit("xrEngine/PacingDiagnostics.h", [
    ("SpawnPublish, ALifeSwitchOnline", "SpawnPublish, ALifeSwitchOnline, SpawnSweepYield, SpawnSweepMaintain, SpawnSweepQuanta"),
])
edit("xrGame/Level.cpp", [
    ('#include "Level.h"', '''#include "Level.h"
#include "DispatchSweep.h"
#include <cstdlib>

namespace
{
bool DispatchSweepEnabled()
{
    static const bool enabled = [] {
        const char* value = std::getenv("IXRAY_SPAWN_DISPATCH_SWEEP");
        return value && xr_strcmp(value, "1") == 0;
    }();
    return enabled;
}
}'''),
    ('u32 svT\t\t\t\t= timeServer()-NET_Latency;', '''u32 svT\t\t\t\t= timeServer()-NET_Latency;
        const bool paceSweep = DispatchSweepEnabled() && IsGameTypeSingle() &&
            bReady && !g_dedicated_server && !IsDemoPlay() && !g_bDebugEvents &&
            g_loading_events.empty() && !Device.dwPrecacheFrame;
        DispatchSweep::Window sweep(lua_gc);
        const auto finishSweep = [&] {
            if (const auto yields = sweep.Exit()) {
                PacingDiag::SpawnSpan yielded(PacingDiag::Kind::SpawnSweepYield, yields);
            }
        };'''),
    ('\t\t\tgame_events->get\t(ID,dest,type,P);', '''        // Peek without consuming any event. Reentrant dispatch keeps the outer budget.
        const auto& queue = game_events->queue;
        if (paceSweep && queue.front().ID == M_SPAWN && queue.size() > 1 &&
            queue[1].ID == M_SPAWN)
            sweep.Enter(ai().script_engine().lua());
        else if (queue.front().ID != M_SPAWN)
            finishSweep();
\t\t\tgame_events->get\t(ID,dest,type,P);'''),
    ('\t}\n\tif (OnServer() && GameID()!= eGameIDSingle)', '''        finishSweep();
\t}
\tif (OnServer() && GameID()!= eGameIDSingle)'''),
    ('\ttry{lua_gc\t(ai().script_engine().lua(), LUA_GCSTEP, psLUA_GCSTEP);}catch (...) {}', '''    try
    {
        auto* state = ai().script_engine().lua();
        if (DispatchSweepEnabled()) {
            PacingDiag::SpawnSpan maintenance(PacingDiag::Kind::SpawnSweepMaintain);
            unsigned quanta = 0;
            if (DispatchSweep::Maintain(lua_gc, state, quanta)) {
                PacingDiag::SpawnSpan serviced(PacingDiag::Kind::SpawnSweepQuanta, quanta);
                return;
            }
        }
        lua_gc(state, LUA_GCSTEP, psLUA_GCSTEP);
    }
    catch (...) {}'''),
])
