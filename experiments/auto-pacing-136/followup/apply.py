"""Add only diagnostic scopes and optional nonblocking DX11 pixel observations."""
from pathlib import Path
import shutil
import sys

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("ixray")
SOURCE = Path(__file__).resolve().parent


def edit(path, changes):
    target = ROOT / "src" / path
    text = target.read_text(encoding="utf-8")
    for before, after in changes:
        assert text.count(before) == 1, (path, before, text.count(before))
        text = text.replace(before, after, 1)
    target.write_text(text, encoding="utf-8", newline="\n")


def scope(stage):
    return "PacingDiag::Span pacing" + stage + "(PacingDiag::Kind::" + stage + ");"


def add_before(anchor, stage):
    return anchor, scope(stage) + "\n    " + anchor


edit("xrEngine/PacingDiagnostics.h", [
    ("BeginRender, SyncFailure", """BeginRender, SyncFailure,
        FrameMove, LevelFrame, ClientReceive, GameEvents, SpawnEvent, ObjectsUpdate,
        GameTask, Scheduler, ParallelTasks, FrameMT, ParticleUpdates, TaskEnqueue,
        PixelSample, PixelProbeWork, TimedCallbacks, HudUpdate"""),
    ("ENGINE_API bool Deep();", "ENGINE_API bool Deep();\n    ENGINE_API bool Pixels();"),
])
edit("xrEngine/PacingDiagnostics.cpp", [
    ("    unsigned long long Counter()", """    bool Pixels() { static const bool enabled=Enabled()&&Flag(L"IXRAY_PACING_PIXELS");return enabled; }
    unsigned long long Counter()"""),
    ("        const unsigned i=s.next.fetch_add", """        if(((kind>=Kind::FrameMove&&kind<=Kind::TaskEnqueue)||kind==Kind::TimedCallbacks||kind==Kind::HudUpdate) && (end-begin)<s.frequency/5000)return;
        if(kind==Kind::PixelProbeWork&&payload==0&&(end-begin)<s.frequency/10000)return;
        const unsigned i=s.next.fetch_add"""),
])
edit("xrEngine/device.cpp", [
    ("\t\t{\n\t\t\tPROF_EVENT(\"Update Particles\");", "\t\t{\n            "+scope("ParticleUpdates")+"\n\t\t\tPROF_EVENT(\"Update Particles\");"),
    ("\t\tfor (auto it = m_time_callbacks.begin(); it != m_time_callbacks.end();)", "\t\t{\n            "+scope("TimedCallbacks")+"\n\t\tfor (auto it = m_time_callbacks.begin(); it != m_time_callbacks.end();)"),
    ("\t\t{\n\t\t\tPROF_EVENT(\"seqParallelBeforRender\");", "\t\t}\n\t\t{\n            "+scope("ParallelTasks")+"\n\t\t\tPROF_EVENT(\"seqParallelBeforRender\");"),
    ("\t\t\tg_pIGameActor->UpdatePlayerHud();", "            "+scope("HudUpdate")+"\n\t\t\tg_pIGameActor->UpdatePlayerHud();"),
    add_before("FrameStallDiag::Scope diag(FrameStallDiag::Stage::FrameMove);","FrameMove"),
    ("\tsecondary_tasks.run(&XRay::Engine::GameThread);", "\t{ "+scope("TaskEnqueue")+" secondary_tasks.run(&XRay::Engine::GameThread); }"),
])
edit("xrEngine/EngineThreading.cpp", [
    add_before("FrameStallDiag::DetailScope diagnosticGameThread(FrameStallDiag::Stage::GameThread);", "GameTask"),
    add_before("FrameStallDiag::Scope diagnosticScheduler(FrameStallDiag::Stage::Scheduler);","Scheduler"),
    ("\t\tPROF_EVENT(\"seqParallel\")", "        "+scope("ParallelTasks")+"\n\t\tPROF_EVENT(\"seqParallel\")"),
    add_before("FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::FrameMT);", "FrameMT"),
])
edit("xrGame/Level.cpp", [
    ('#include "../xrEngine/FrameStallDiagnostics.h"', '#include "../xrEngine/FrameStallDiagnostics.h"\n#include "../xrEngine/PacingDiagnostics.h"'),
    add_before("FrameStallDiag::Scope diagnosticEvents(FrameStallDiag::Stage::GameEvents);","GameEvents"),
    add_before("FrameStallDiag::Scope diagnosticSpawn(FrameStallDiag::Stage::SpawnEvent);","SpawnEvent"),
    add_before("FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::LevelFrame);","LevelFrame"),
    ("{ FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::ClientReceive); ClientReceive(); }",
     "{ "+scope("ClientReceive")+" FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::ClientReceive); ClientReceive(); }"),
])
edit("xrEngine/IGame_Level.cpp", [
    ('#include "FrameStallDiagnostics.h"', '#include "FrameStallDiagnostics.h"\n#include "PacingDiagnostics.h"'),
    ("{ FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::ObjectUpdate); Objects.Update(false); }",
     "{ "+scope("ObjectsUpdate")+" FrameStallDiag::DetailScope detail(FrameStallDiag::Stage::ObjectUpdate); Objects.Update(false); }"),
])
edit("Layers/xrRender/dxRenderDeviceRender.cpp", [
    ("#include <d3d11_1.h>", "#include <d3d11_1.h>\n#include \"PacingPixelProbe.h\"\nstatic PacingPixelProbe pacingPixels;"),
    ("\txr_delete(Resources);\n\tCImGuiManager::Instance().Destroy(true);", """#ifdef USE_DX11
    pacingPixels.Reset();
#endif
\txr_delete(Resources);
\tCImGuiManager::Instance().Destroy(true);"""),
    ("    PacingDiag::Span pacingReset(PacingDiag::Kind::Reset);", """    PacingDiag::Span pacingReset(PacingDiag::Kind::Reset);
#ifdef USE_DX11
    pacingPixels.Reset();
#endif"""),
    ("    const bool pacingPresent = PacingDiag::Enabled();", """    if (PacingDiag::Pixels())
    {
        const auto qpc = PacingDiag::Counter();
        const auto frame = PacingDiag::CurrentFrame();
        const auto status = pacingPixels.Observe(RDevice,RContext,RSwapchainTarget,frame,qpc,
            [](unsigned sampledFrame,unsigned long long sampledQpc,unsigned long long levels)
            {
                PacingDiag::Record(PacingDiag::Kind::PixelSample,sampledFrame,sampledQpc,sampledQpc,levels);
            });
        PacingDiag::Record(PacingDiag::Kind::PixelProbeWork,frame,qpc,PacingDiag::Counter(),
            static_cast<unsigned>(status));
    }
    const bool pacingPresent = PacingDiag::Enabled();"""),
])
shutil.copy2(SOURCE / "PacingPixelProbe.h", ROOT / "src/Layers/xrRender/PacingPixelProbe.h")
print("Scope overlays and eight-point DX11 probe applied")
