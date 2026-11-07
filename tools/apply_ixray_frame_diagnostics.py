#!/usr/bin/env python3
"""IX-Ray r1.3.6, always-on diagnostic overlays. Never alters game logic.
Run AFTER the canonical HOLD, crouch, CPU, DX11 patches, and INSTEAD OF
IXRay_136_OptIn_FrameStall_Trace.patch. The existing trace is superseded.
"""
from pathlib import Path
import re

ROOT = Path("ixray/src")

def modify(path, changes):
    p = ROOT / path
    old = p.read_bytes().replace(b"\r\n", b"\n").decode("latin-1")
    value = old
    for label, before, after in changes:
        n = value.count(before)
        if n != 1:
            raise RuntimeError(f"{path} [{label}]: expected one anchor, found {n}")
        value = value.replace(before, after, 1)
    p.write_bytes(value.encode("latin-1"))
    print(f"Updated {path}: {len(changes)} verified anchors")

header = r'''#pragma once
// Diagnostic-only per-frame CPU stall attribution, enabled by default; no gameplay changes.
// API lives in xrAbstractions / xrEngine, shared by xrGame and DX11 renderer.
#include <chrono>

namespace FrameStallDiag
{
    enum class Stage : unsigned {
        FrameMove, RenderMain, EndRender, WaitGameThread, GameThread,
        Scheduler, ScriptVM, PhysicsCommands, LuaGC, GameEvents,
        SpawnEvent, ObjectCreate, ObjectNetSpawn, ModelLoad, ModelDefer,
        Count
    };

    ENGINE_API bool Enabled();
    ENGINE_API unsigned CurrentFrame();
    ENGINE_API void BeginFrame(unsigned frame);
    ENGINE_API void Record(Stage stage, unsigned frame, unsigned long long us);
    ENGINE_API void FinishFrame(unsigned frame, double totalMs);

    // Scopes can be disabled explicitly with IXRAY_TRACE_FRAME_STALLS=0.
    class Scope
    {
        using Clock = std::chrono::steady_clock;
        Stage stage_;
        bool active_;
        unsigned frame_;
        Clock::time_point start_;
    public:
        explicit Scope(Stage stage)
            : stage_(stage),
              active_(Enabled()),
              frame_(active_ ? CurrentFrame() : 0),
              start_(active_ ? Clock::now() : Clock::time_point{}) {}
        ~Scope()
        {
            if (!active_ || frame_ == 0)
                return;
            const auto us = std::chrono::duration_cast<std::chrono::microseconds>(Clock::now() - start_).count();
            Record(stage_, frame_, us > 0 ? static_cast<unsigned long long>(us) : 0ULL);
        }
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;
    };
}
'''
header_path = ROOT / "xrEngine/FrameStallDiagnostics.h"
if header_path.exists():
    raise RuntimeError("Diagnostics header already exists")
header_path.write_text(header, encoding="utf-8")

implementation = r'''
// Shared per-frame counters. The GameThread is joined before FinishFrame.
// No worker-thread logging, allocations or mutexes on the instrumented path.
namespace FrameStallDiag
{
    namespace
    {
        constexpr unsigned kHistory = 256;
        constexpr unsigned kStages = static_cast<unsigned>(Stage::Count);
        struct Sample
        {
            std::atomic<unsigned> frame{0};
            std::atomic<unsigned long long> us[kStages]{};
            std::atomic<unsigned> count[kStages]{};
        };
        Sample samples[kHistory];
        std::atomic<unsigned> activeFrame{0};

        double ms(const Sample& s, Stage stage)
        {
            return static_cast<double>(s.us[static_cast<unsigned>(stage)].load(std::memory_order_relaxed)) / 1000.0;
        }
        unsigned calls(const Sample& s, Stage stage)
        {
            return s.count[static_cast<unsigned>(stage)].load(std::memory_order_relaxed);
        }
    }

    bool Enabled()
    {
        static const bool enabled = []() {
            char flag[2] = {};
            // Diagnostic builds trace by default. Set IXRAY_TRACE_FRAME_STALLS=0 to disable.
            return !(GetEnvironmentVariableA("IXRAY_TRACE_FRAME_STALLS", flag, sizeof(flag)) == 1 && flag[0] == '0');
        }();
        return enabled;
    }

    unsigned CurrentFrame()
    {
        return activeFrame.load(std::memory_order_acquire);
    }

    void BeginFrame(unsigned frame)
    {
        if (!Enabled()) return;
        Sample& s = samples[frame % kHistory];
        s.frame.store(0, std::memory_order_release);
        for (unsigned i = 0; i != kStages; ++i)
        {
            s.us[i].store(0, std::memory_order_relaxed);
            s.count[i].store(0, std::memory_order_relaxed);
        }
        s.frame.store(frame, std::memory_order_release);
        activeFrame.store(frame, std::memory_order_release);
    }

    void Record(Stage stage, unsigned frame, unsigned long long us)
    {
        if (!Enabled() || frame == 0) return;
        Sample& s = samples[frame % kHistory];
        if (s.frame.load(std::memory_order_acquire) != frame) return;
        const unsigned slot = static_cast<unsigned>(stage);
        s.us[slot].fetch_add(us, std::memory_order_relaxed);
        s.count[slot].fetch_add(1, std::memory_order_relaxed);
    }

    void FinishFrame(unsigned frame, double totalMs)
    {
        if (!Enabled() || totalMs < 16.0) return;
        const auto now = std::chrono::steady_clock::now();
        static auto lastReport = now - std::chrono::seconds(1);
        if (now - lastReport < std::chrono::milliseconds(250)) return;
        Sample& s = samples[frame % kHistory];
        if (s.frame.load(std::memory_order_acquire) != frame) return;
        lastReport = now;
        Msg("! FRAMESTALL2 frame=%u total=%.2fms move=%.2f render=%.2f end_render=%.2f wait=%.2f game=%.2f scheduler=%.2f script=%.2f physics_cmd=%.2f lua_gc=%.2f events=%.2f spawn=%.2f(n=%u) object_ctor=%.2f net_spawn=%.2f model_load=%.2f(n=%u) model_defer=%.2f",
            frame, totalMs,
            ms(s, Stage::FrameMove), ms(s, Stage::RenderMain), ms(s, Stage::EndRender),
            ms(s, Stage::WaitGameThread), ms(s, Stage::GameThread),
            ms(s, Stage::Scheduler), ms(s, Stage::ScriptVM),
            ms(s, Stage::PhysicsCommands), ms(s, Stage::LuaGC),
            ms(s, Stage::GameEvents), ms(s, Stage::SpawnEvent), calls(s, Stage::SpawnEvent),
            ms(s, Stage::ObjectCreate), ms(s, Stage::ObjectNetSpawn),
            ms(s, Stage::ModelLoad), calls(s, Stage::ModelLoad), ms(s, Stage::ModelDefer));
    }
}

'''
modify("xrEngine/device.cpp", [
 ("include", '#include "stdafx.h"', '#include "stdafx.h"\n#include "FrameStallDiagnostics.h"\n#include <atomic>'),
 ("implementation", 'int g_svDedicateServerUpdateReate = 100;', implementation + 'int g_svDedicateServerUpdateReate = 100;'),
 ("start frame", '\tPROF_FRAME("Main Thread");', '''\tPROF_FRAME("Main Thread");
    FrameStallDiag::BeginFrame(dwFrame + 1);
    const auto frameStallStart = FrameStallDiag::Enabled()
        ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};'''),
 ("frame move", '\t\tFrameMove();', '''        {
            FrameStallDiag::Scope diag(FrameStallDiag::Stage::FrameMove);
            FrameMove();
        }'''),
 ("main render", '''\tif (!g_dedicated_server)
\t{
\t\tStatistic->RenderTOTAL_Real.FrameStart();''',
  '''\tif (!g_dedicated_server)
\t{
        FrameStallDiag::Scope diag(FrameStallDiag::Stage::RenderMain);
\t\tStatistic->RenderTOTAL_Real.FrameStart();'''),
 ("join and end", '''\tsecondary_tasks.wait();

\tDevice.EndRender();''', '''    {
        FrameStallDiag::Scope diag(FrameStallDiag::Stage::WaitGameThread);
        secondary_tasks.wait();
    }
    {
        FrameStallDiag::Scope diag(FrameStallDiag::Stage::EndRender);
        Device.EndRender();
    }
    if (FrameStallDiag::Enabled())
    {
        const auto frameStallEnd = std::chrono::steady_clock::now();
        const double totalMs = std::chrono::duration<double, std::milli>(frameStallEnd - frameStallStart).count();
        FrameStallDiag::FinishFrame(dwFrame, totalMs);
    }''')
])
modify("xrEngine/EngineThreading.cpp", [
 ("include", '#include "EngineThreading.h"', '#include "EngineThreading.h"\n#include "FrameStallDiagnostics.h"'),
 ("game thread", '''void XRay::Engine::GameThread()
{''', '''void XRay::Engine::GameThread()
{
    FrameStallDiag::Scope diagnosticGameThread(FrameStallDiag::Stage::GameThread);'''),
 ("scheduler", '''\t{
\t\tPROF_EVENT("Sheduler")''', '''\t{
        FrameStallDiag::Scope diagnosticScheduler(FrameStallDiag::Stage::Scheduler);
\t\tPROF_EVENT("Sheduler")''')
])
modify("xrGame/Level.cpp", [
 ("include", '#include "StdAfx.h"', '#include "StdAfx.h"\n#include "../xrEngine/FrameStallDiagnostics.h"'),
 ("event span", '''\tPROF_EVENT("CLevel::ProcessGameEvents");''', '''\tPROF_EVENT("CLevel::ProcessGameEvents");
    FrameStallDiag::Scope diagnosticEvents(FrameStallDiag::Stage::GameEvents);'''),
 ("spawn span", '''\t\t\tcase M_SPAWN:
\t\t\t\t{
\t\t\t\t\tPROF_EVENT("M_SPAWN");''', '''\t\t\tcase M_SPAWN:
\t\t\t\t{
                    FrameStallDiag::Scope diagnosticSpawn(FrameStallDiag::Stage::SpawnEvent);
\t\t\t\t\tPROF_EVENT("M_SPAWN");'''),
 ("script and physics", '''\t\t\tai().script_engine().script_process(ScriptEngine::eScriptProcessorLevel)->update();

\t\t\tm_ph_commander->update();
\t\t\tm_ph_commander_scripts->update();''', '''            {
                FrameStallDiag::Scope diagnosticScript(FrameStallDiag::Stage::ScriptVM);
                ai().script_engine().script_process(ScriptEngine::eScriptProcessorLevel)->update();
            }
            {
                FrameStallDiag::Scope diagnosticPhysics(FrameStallDiag::Stage::PhysicsCommands);
                m_ph_commander->update();
                m_ph_commander_scripts->update();
            }'''),
 ("lua GC", '''\tPROF_EVENT("CLevel::script_gc");
\ttry{lua_gc''', '''\tPROF_EVENT("CLevel::script_gc");
    FrameStallDiag::Scope diagnosticGC(FrameStallDiag::Stage::LuaGC);
\ttry{lua_gc''')
])
modify("xrGame/Level_network_spawn.cpp", [
 ("include", '#include "Level.h"', '#include "Level.h"\n#include "../xrEngine/FrameStallDiagnostics.h"'),
 ("object ctor", '''\tCObject*\tO\t\t= Objects.Create\t(*E->s_name);''', '''    CObject* O = nullptr;
    {
        FrameStallDiag::Scope diagnosticCreate(FrameStallDiag::Stage::ObjectCreate);
        O = Objects.Create(*E->s_name);
    }'''),
 ("net spawn", '''\tif (0==O || (!O->net_Spawn\t(E))) ''', '''    bool spawnSucceeded = false;
    if (O)
    {
        FrameStallDiag::Scope diagnosticNetSpawn(FrameStallDiag::Stage::ObjectNetSpawn);
        spawnSucceeded = O->net_Spawn(E);
    }
    if (0==O || !spawnSucceeded) ''')
])
modify("Layers/xrRender/ModelPool.cpp", [
 ("include", '#include "ModelPool.h"', '#include "ModelPool.h"\n#include "../../xrEngine/FrameStallDiagnostics.h"'),
 ("instance load", '''dxRender_Visual*\tCModelPool::Instance_Load\t\t(const char* N, BOOL allow_register)
{''', '''dxRender_Visual*\tCModelPool::Instance_Load\t\t(const char* N, BOOL allow_register)
{
    FrameStallDiag::Scope diagnosticLoad(FrameStallDiag::Stage::ModelLoad);'''),
 ("reader load", '''dxRender_Visual* CModelPool::Instance_Load(const char* name, IReader* data, BOOL allow_register)
{''', '''dxRender_Visual* CModelPool::Instance_Load(const char* name, IReader* data, BOOL allow_register)
{
    FrameStallDiag::Scope diagnosticLoad(FrameStallDiag::Stage::ModelLoad);'''),
 ("deferred deletion", '''void CModelPool::DeleteQueuedDeffer()
{''', '''void CModelPool::DeleteQueuedDeffer()
{
    FrameStallDiag::Scope diagnosticDeferred(FrameStallDiag::Stage::ModelDefer);''')
])
print("Attribution-only overlay applied. Gameplay event order, AI and timing unchanged.")
