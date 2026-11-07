#!/usr/bin/env python3
"""Refine proven IX-Ray 1.3.6 stalls without altering simulation.
Applied AFTER tools/apply_ixray_frame_diagnostics.py and after prior CPU patch.
"""
from pathlib import Path
import re
ROOT = Path("ixray/src")
def modify(path, changes):
    p = ROOT / path
    data = p.read_bytes()
    # IX-Ray sources are mixed Windows-1251 / ASCII, preserve all high bytes.
    s = data.replace(b"\r\n", b"\n").decode("latin-1")
    for name, before, after in changes:
        count = s.count(before)
        if count != 1:
            raise RuntimeError(f"{path}: anchor {name}: expected 1, got {count}")
        s = s.replace(before, after, 1)
    p.write_bytes(s.encode("latin-1"))
    print(path, "OK", len(changes))

modify("xrEngine/FrameStallDiagnostics.h", [
    ("stages", "SpawnEvent, ObjectCreate, ObjectNetSpawn, ModelLoad, ModelDefer,\n        Count",
     "SpawnEvent, ObjectCreate, ObjectNetSpawn, ModelLoad, ModelDefer,\n"
     "        SchedulerRT, SchedulerNormal, GameObjectBase, ObjectBase,\n"
     "        BinderReload, BinderSpawn, SpawnSupplies, ObjectPoolCreate,\n        Count"),
    ("method", "    ENGINE_API void FinishFrame(unsigned frame, double totalMs);",
     "    ENGINE_API void FinishFrame(unsigned frame, double totalMs);\n"
     "    ENGINE_API void RecordScheduled(bool rt, unsigned frame, unsigned long long us, const char* name);"),
])
modify("xrEngine/device.cpp", [
    ("worst struct", '''        struct Sample
        {
            std::atomic<unsigned> frame{0};''', '''        struct WorstSchedule
        {
            unsigned long long us = 0;
            char name[96] = {};
        };
        struct Sample
        {
            WorstSchedule worst[2];
            std::atomic<unsigned> frame{0};'''),
    ("worst reset", '''        s.frame.store(frame, std::memory_order_release);
        activeFrame.store(frame, std::memory_order_release);''', '''        s.worst[0].us = 0;
        s.worst[0].name[0] = 0;
        s.worst[1].us = 0;
        s.worst[1].name[0] = 0;
        s.frame.store(frame, std::memory_order_release);
        activeFrame.store(frame, std::memory_order_release);'''),
    ("schedule capture", '''    void FinishFrame(unsigned frame, double totalMs)
    {''', '''    void RecordScheduled(bool rt, unsigned frame, unsigned long long us, const char* name)
    {
        if (!Enabled() || frame == 0) return;
        Sample& s = samples[frame % kHistory];
        if (s.frame.load(std::memory_order_acquire) != frame) return;
        const unsigned slot = static_cast<unsigned>(rt ? Stage::SchedulerRT : Stage::SchedulerNormal);
        s.us[slot].fetch_add(us, std::memory_order_relaxed);
        s.count[slot].fetch_add(1, std::memory_order_relaxed);
        // Only GameThread writes this pair; main thread reads after secondary_tasks.wait().
        WorstSchedule& worst = s.worst[rt ? 0 : 1];
        if (us > worst.us)
        {
            worst.us = us;
            strncpy_s(worst.name, sizeof(worst.name), name ? name : "?", _TRUNCATE);
        }
    }

    void FinishFrame(unsigned frame, double totalMs)
    {'''),
    ("log format", "model_defer=%.2f\",",
     "model_defer=%.2f rt=%.2f(n=%u) nonrt=%.2f(n=%u) worst_rt=%s/%.2f worst_nonrt=%s/%.2f game_base=%.2f obj_base=%.2f binder_reload=%.2f binder_spawn=%.2f supplies=%.2f pool_create=%.2f\","),
    ("log args", '''ms(s, Stage::ModelLoad), calls(s, Stage::ModelLoad), ms(s, Stage::ModelDefer));''', '''ms(s, Stage::ModelLoad), calls(s, Stage::ModelLoad), ms(s, Stage::ModelDefer),
            ms(s, Stage::SchedulerRT), calls(s, Stage::SchedulerRT),
            ms(s, Stage::SchedulerNormal), calls(s, Stage::SchedulerNormal),
            s.worst[0].name, static_cast<double>(s.worst[0].us) / 1000.0,
            s.worst[1].name, static_cast<double>(s.worst[1].us) / 1000.0,
            ms(s, Stage::GameObjectBase), ms(s, Stage::ObjectBase),
            ms(s, Stage::BinderReload), ms(s, Stage::BinderSpawn),
            ms(s, Stage::SpawnSupplies), ms(s, Stage::ObjectPoolCreate));''')
])
modify("xrEngine/xrSheduler.cpp", [
    ("include", '#include "xrSheduler.h"', '#include "xrSheduler.h"\n#include "FrameStallDiagnostics.h"'),
    ("normal timed update", '''\t\t\tT.Object->shedule_Update\t(clampr(Elapsed,u32(1),u32(_max(u32(T.Object->shedule.t_max),u32(1000)))) );
\t\t\tif (!m_current_step_obj)''', '''            const bool traceNormal = FrameStallDiag::Enabled();
            const auto normalStart = traceNormal ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
            T.Object->shedule_Update(clampr(Elapsed,u32(1),u32(_max(u32(T.Object->shedule.t_max),u32(1000)))));
            if (traceNormal)
            {
                const auto elapsedUs = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - normalStart).count();
                FrameStallDiag::RecordScheduled(false, Device.dwFrame, elapsedUs > 0 ? static_cast<unsigned long long>(elapsedUs) : 0ULL, *T.scheduled_name);
            }
\t\t\tif (!m_current_step_obj)'''),
    ("rt timed update", '''\t\tT.Object->shedule_Update\t(Elapsed);
\t\tT.dwTimeOfLastExecute''', '''        const bool traceRT = FrameStallDiag::Enabled();
        const auto rtStart = traceRT ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
        T.Object->shedule_Update(Elapsed);
        if (traceRT)
        {
            const auto elapsedUs = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now() - rtStart).count();
            FrameStallDiag::RecordScheduled(true, Device.dwFrame, elapsedUs > 0 ? static_cast<unsigned long long>(elapsedUs) : 0ULL, *T.scheduled_name);
        }
\t\tT.dwTimeOfLastExecute''')
])
modify("xrEngine/IGame_ObjectPool.cpp", [
    ("include", '#include "IGame_ObjectPool.h"', '#include "IGame_ObjectPool.h"\n#include "FrameStallDiagnostics.h"'),
    ("pool_create", '''CObject* IGame_ObjectPool::create(LPCSTR name)
{''', '''CObject* IGame_ObjectPool::create(LPCSTR name)
{
    FrameStallDiag::Scope diagnosticPoolCreate(FrameStallDiag::Stage::ObjectPoolCreate);''')
])
modify("xrEngine/xr_object.cpp", [
    ("include", '#include "stdafx.h"', '#include "stdafx.h"\n#include "FrameStallDiagnostics.h"'),
    ("base net spawn", '''BOOL CObject::net_Spawn\t\t\t(CSE_Abstract* data)
{''', '''BOOL CObject::net_Spawn\t\t\t(CSE_Abstract* data)
{
    FrameStallDiag::Scope diagnosticBaseObject(FrameStallDiag::Stage::ObjectBase);''')
])
modify("xrGame/GameObject.cpp", [
    ("include", '#include "StdAfx.h"', '#include "StdAfx.h"\n#include "../xrEngine/FrameStallDiagnostics.h"'),
    ("game net spawn", '''BOOL CGameObject::net_Spawn\t\t(CSE_Abstract*\tDC)
{''', '''BOOL CGameObject::net_Spawn\t\t(CSE_Abstract*\tDC)
{
    FrameStallDiag::Scope diagnosticBaseGameObject(FrameStallDiag::Stage::GameObjectBase);'''),
    ("spawn supplies", '''\tspawn_supplies\t\t\t\t();''', '''    {
        FrameStallDiag::Scope diagnosticSupplies(FrameStallDiag::Stage::SpawnSupplies);
        spawn_supplies();
    }''')
])
modify("xrGame/script_binder.cpp", [
    ("include", '#include "StdAfx.h"', '#include "StdAfx.h"\n#include "../xrEngine/FrameStallDiagnostics.h"'),
    ("binder reload", '''void CScriptBinder::reload\t\t\t(LPCSTR section)
{''', '''void CScriptBinder::reload\t\t\t(LPCSTR section)
{
    FrameStallDiag::Scope diagnosticBinderReload(FrameStallDiag::Stage::BinderReload);'''),
    ("binder net spawn", '''BOOL CScriptBinder::net_Spawn\t\t(CSE_Abstract* DC)
{''', '''BOOL CScriptBinder::net_Spawn\t\t(CSE_Abstract* DC)
{
    FrameStallDiag::Scope diagnosticBinderSpawn(FrameStallDiag::Stage::BinderSpawn);''')
])
print("Detailed GameObject and Scheduler attribution enabled, original call order unchanged.")
