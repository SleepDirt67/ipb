"""Add diagnostics to the sealed Windows engine source after production overlays."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
SCRIPT_SHA256 = "3f401082c3fe918aa48d521a1a18cdfcf2ae6009b7d56620451e42a399d029e9"
PHASES = [
    "host or unmarked VM", "reinit base and storage", "state manager", "movement manager",
    "visual and base spawn", "database and callbacks", "info and death", "relations and enemy registration",
    "sound and anomaly evaluator", "reach task and position", "smart terrain and schemes", "finalize",
]


def one(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError(f"Expected one engine anchor: {anchor!r}")
    return source.replace(anchor, replacement, 1)


def change(file, transform):
    raw = file.read_bytes()
    source = raw.decode("utf-8").replace("\r\n", "\n")
    updated = transform(source)
    if raw.count(b"\r\n") == raw.count(b"\n"):
        updated = updated.replace("\n", "\r\n")
    file.write_bytes(updated.encode("utf-8"))


def script_source(script):
    raw = script.read_bytes()
    if hashlib.sha256(raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")).hexdigest() != SCRIPT_SHA256:
        raise ValueError("Stock xr_motivator.script source SHA256 mismatch")
    normalized = raw.replace(b"\r\n", b"\n")
    patched = normalized.decode("latin1")
    cuts = (
        ("\t\tobject_binder.reinit(self)", 1),
        ("\tself.st.state_mgr = state_mgr.bind_manager(self.object)", 2),
        ("\tself.st.move_mgr = move_mgr.move_mgr(self.object)", 3),
        ("\tprintf(\"motivator_binder:net_spawn()", 4),
        ("\n\tdb.add_obj(self.object)", 5),
        ("\tif self.loaded == false then", 6),
        ("\tlocal relation = db.goodwill.relations", 7),
        ("\tsound_theme.init_npc_sound(self.object)", 8),
        ("\txr_reach_task.add_reach_task_action(self.object)", 9),
        ("\tsmart_terrain.setup_gulag_and_logic_on_spawn(self.object", 10),
        ("\tif character_community(self.object) ~= \"zombied\" then", 11),
    )
    start = patched.index("function motivator_binder:reinit()")
    end = patched.index("function motivator_binder:net_destroy()")
    scope = patched[start:end]
    for anchor, number in cuts:
        anchor = anchor.lstrip("\n")
        scope = one(scope, anchor, f"\t__ixray_probe({number}); {anchor.lstrip()}")
    patched = "local __ixray_probe = _G.__ixray_binder_capture_phase; " + patched[:start] + scope + patched[end:]
    return normalized, patched.encode("latin1")


def cpp_array(name, source):
    lines = [", ".join(map(str, source[i:i+32])) for i in range(0, len(source), 32)]
    return f"static constexpr unsigned char {name}[] = {{\n" + ",\n".join(lines) + "\n};\n"


def binders(source):
    for name, kind in (("reinit", 1), ("reload", 2), ("net_Spawn", 3), ("load", 4)):
        pattern = re.compile(rf"(CScriptBinder::{name}\s*\([^\n]*\)\n\{{)(.*?)(\n\}})", re.S)
        match = pattern.search(source)
        if not match:
            raise ValueError(name)
        body = match.group(2)
        body, errors = re.subn(r"(catch\(\.\.\.\)\s*\{)", r"\1\n            binderCapture.Fail();", body)
        if not errors:
            raise ValueError(f"No protected binder boundary in {name}")
        body = (f"\n    BinderCapture::Scope binderCapture({kind}, BinderCapture::DispatchActive()\n"
                "        ? ai().script_engine().lua() : nullptr);" + body)
        source = source[:match.start(2)] + body + source[match.end(2):]
    return source


def apply(root, checks):
    src = root / "src"
    for name in ("BinderCapture.h", "BinderCaptureFormat.h", "BinderCaptureEngine.inc"):
        shutil.copyfile(HERE / name, src / "xrEngine" / name)
    shutil.copyfile(HERE / "BinderScript.inc", src / "xrScripts/BinderScript.inc")
    stock, marked = script_source(root / "gamedata/scripts/xr_motivator.script")
    (src / "xrScripts/BinderScript.generated.inc").write_text(
        cpp_array("originalMotivator", stock) + cpp_array("markedMotivator", marked), encoding="ascii", newline="\n"
    )
    checks.mkdir(parents=True, exist_ok=True)
    (checks / "instrumentation_map.json").write_text(json.dumps({
        "base": "886337084c8fd851a4fff186b453ae7cc6450821",
        "stock_motivator_sha256": SCRIPT_SHA256, "normalized_sha256": hashlib.sha256(stock).hexdigest(),
        "instrumented_sha256": hashlib.sha256(marked).hexdigest(), "phases": PHASES,
        "native": "First occupied slot and one call per 64 in selected phases. Voice/anomaly and idle VM bypass the C wrapper. Untimed C, JIT fast functions, FFI and VM internals remain in the residual.",
    }, indent=2) + "\n", encoding="utf-8")
    (checks / "motivator_probe.lua").write_bytes(marked)

    def pacing(source):
        source = one(source, "namespace PacingDiag\n", '#include "BinderCaptureEngine.inc"\n\nnamespace PacingDiag\n')
        source = one(source, "        const auto q=Counter();", """        const auto q=Counter();
        const bool wasObserving = BinderCapture::Observing();
        BinderCapture::OnFrame(q, flags);
        static unsigned previousFlags = ~0u;
        const bool stateChanged = previousFlags != flags;
        previousFlags = flags;""")
        source = one(source, "        Record(Kind::FrameState,frame,q,q,",
                     """        if (!BinderCapture::Enabled() || BinderCapture::Observing() || wasObserving || stateChanged)
            Record(Kind::FrameState,frame,q,q,""")
        source = one(source, "        // Deep-only", """        if (BinderCapture::Frozen()) return;
        if (BinderCapture::Enabled())
        {
            if (kind != Kind::FrameState && !BinderCapture::Observing()) return;
            if ((kind == Kind::OtherGameEvent || kind == Kind::BeginRender ||
                kind == Kind::Discord || kind == Kind::Gamma || kind == Kind::SceneRender) &&
                end - begin < s.frequency / 2000) return;
        }
        // Deep-only""")
        source = one(source, "if(i>=State::capacity){s.dropped.fetch_add(1,std::memory_order_relaxed);return;}",
                     """if(i>=State::capacity){
            s.dropped.fetch_add(1,std::memory_order_relaxed);
            if (kind == Kind::Present) BinderCapture::OnPresent(begin, end);
            return;
        }""")
        source = one(source, "if(((kind>=Kind::FrameMove",
                     "if((!BinderCapture::Enabled() || (kind != Kind::TaskEnqueue && kind != Kind::GameTask)) && ((kind>=Kind::FrameMove")
        return one(source, '    }\n    void Flush() { if(Enabled())Data().Write(); }',
                   '''        if (kind == Kind::Present) BinderCapture::OnPresent(begin, end);
    }
    void Flush() { BinderCapture::Flush(); if(Enabled())Data().Write(); }''')
    change(src / "xrEngine/PacingDiagnostics.cpp", pacing)

    def device(source):
        source = one(source, "\t\tsecondary_tasks.run(&XRay::Engine::PreRenderThread);",
                     """        {
            PacingDiag::Span enqueue(PacingDiag::Kind::TaskEnqueue, false, 1);
            secondary_tasks.run(&XRay::Engine::PreRenderThread);
        }""")
        source = one(source, "PacingDiag::Span pacingTaskEnqueue(PacingDiag::Kind::TaskEnqueue);",
                     "PacingDiag::Span pacingTaskEnqueue(PacingDiag::Kind::TaskEnqueue, false, 2);")
        return one(source, "PacingDiag::Span pacingWait(PacingDiag::Kind::WaitWorkers);",
                   "PacingDiag::Span pacingWait(PacingDiag::Kind::WaitWorkers, false, 3);")
    change(src / "xrEngine/device.cpp", device)

    def workers(source):
        source = one(source, "PacingDiag::Span pacingPre(PacingDiag::Kind::PreRender);",
                     "PacingDiag::Span pacingPre(PacingDiag::Kind::PreRender, false, 1);")
        return one(source, "PacingDiag::Span pacingGameTask(PacingDiag::Kind::GameTask);",
                   "PacingDiag::Span pacingGameTask(PacingDiag::Kind::GameTask, false, 2);")
    change(src / "xrEngine/EngineThreading.cpp", workers)

    def luabind(source):
        declaration = """#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace {
using IxTag = void (__cdecl*)(lua_State*, const char*, const char*, unsigned);
using IxGate = const volatile uint32_t* (__cdecl*)();
struct IxTagHook { IxTag tag; const volatile uint32_t* gate; };
IxTagHook BinderMethodTag()
{
    wchar_t flag[2]{};
    if (GetEnvironmentVariableW(L"IXRAY_BINDER_CAPTURE", flag, 2) != 1 || flag[0] != L'1')
        return {};
    const auto lua = GetModuleHandleW(L"lua51.dll");
    const auto tag = reinterpret_cast<IxTag>(GetProcAddress(lua, "xrBinderCaptureTagNative"));
    const auto gate = reinterpret_cast<IxGate>(GetProcAddress(lua, "xrBinderCaptureTagGate"));
    return {tag, gate ? gate() : nullptr};
}
}
#endif

"""
        anchor = "int luabind::detail::class_rep::function_dispatcher(lua_State* L)"
        source = one(source, anchor, declaration + anchor)
        return one(source, "return o.call(L, force_static_call != 0);",
                   """#ifdef _WIN32
            static const auto binderMethodTag = BinderMethodTag();
            if (binderMethodTag.gate && *binderMethodTag.gate && binderMethodTag.tag)
                binderMethodTag.tag(L, rep->crep->name(), rep->name, static_cast<unsigned>(match_index));
#endif
            return o.call(L, force_static_call != 0);""")
    change(root / "build/x64/Engine-Windows/_deps/luabind-src/luabind/src/class_rep.cpp", luabind)


    def insert_header(source):
        return one(source, '#include "StdAfx.h"\n', '#include "StdAfx.h"\n#include "../xrEngine/BinderCapture.h"\n')

    change(src / "xrGame/script_binder.cpp", lambda source: binders(insert_header(source)))
    change(src / "xrGame/Level.cpp", lambda source: one(
        insert_header(source), "\t\t\tgame_events->get\t(ID,dest,type,P);",
        "\t\t\tgame_events->get\t(ID,dest,type,P);\n            BinderCapture::Queue binderQueue;"))
    def dispatch(source):
        source = insert_header(source)
        source = one(source, "    PacingDiag::SpawnSpan spawnPath(PacingDiag::Kind::SpawnDispatch,",
                     "    BinderCapture::Dispatch binderDispatch(E->ID, E->ID_Parent, E->m_tClassID, *E->s_name);\n"
                     "    PacingDiag::SpawnSpan spawnPath(PacingDiag::Kind::SpawnDispatch,")
        source = one(source, "        const bool prepareVoice = owner && owner->cast_stalker() && IsGameTypeSingle() &&",
                     "        const bool stalker = owner && owner->cast_stalker();\n"
                     "        binderDispatch.Stalker(stalker);\n"
                     "        const bool prepareVoice = stalker && IsGameTypeSingle() &&")
        return one(source, "    if (0==O || !spawnSucceeded)",
                   "    binderDispatch.Result(spawnSucceeded);\n    if (0==O || !spawnSucceeded)")
    change(src / "xrGame/Level_network_spawn.cpp", dispatch)

    def save(source):
        source = insert_header(source)
        anchor = '\tMsg("* Game %s is successfully loaded from file'
        return one(source, anchor, "    BinderCapture::SaveLoaded(save_name);\n" + anchor)
    change(src / "xrGame/alife_storage_manager.cpp", save)

    def storage(source):
        source = one(source, '#include "SpawnLuaProfile.h"\n', '#include "SpawnLuaProfile.h"\n#include "BinderScript.inc"\n')
        source = one(source, "    SpawnLuaProfile::Start(lua());", "    BinderScript::Install(lua());\n    SpawnLuaProfile::Start(lua());")
        source = one(source, "        const auto source = !prepared.empty()",
                     "        auto source = !prepared.empty()")
        return one(source, "        loaded = load_buffer(lua(), source.data()",
                   '''        if (BinderScript::Enabled() && caNameSpaceName && xr_strcmp(caNameSpaceName, "xr_motivator") == 0)
            source = BinderScript::Source(lua(), source);
        loaded = load_buffer(lua(), source.data()''')
    change(src / "xrScripts/script_storage.cpp", storage)


if __name__ == "__main__":
    apply(Path(sys.argv[1]), Path(sys.argv[2]))
