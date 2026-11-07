#pragma once

#include "../xrEngine/PacingDiagnostics.h"
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>
#include <string>

namespace SpawnLuaProfile
{
    using Callback = void (__cdecl*)(void*, lua_State*, int, int);
    using StartFunction = void (__cdecl*)(lua_State*, const char*, Callback, void*);
    using StopFunction = void (__cdecl*)(lua_State*);
    using DumpFunction = const char* (__cdecl*)(lua_State*, const char*, int, size_t*);

    struct Recorder
    {
        struct Sample
        {
            unsigned long long begin, end;
            unsigned frame, thread, phase;
            int count, vmState;
            bool truncated;
            char stack[384];
        };
        static constexpr unsigned capacity = 32768;
        explicit Recorder(lua_State* state) : state(state), rows(new (std::nothrow) Sample[capacity]{}) {}

        lua_State* state;
        std::unique_ptr<Sample[]> rows;
        std::atomic<unsigned> next{0};
        StopFunction stop = nullptr;
        DumpFunction dump = nullptr;
    };

    inline std::unique_ptr<Recorder> recorder;
    inline unsigned generation = 0;

    inline void __cdecl SampleBinder(void* context, lua_State* state, int count, int vmState)
    {
        const auto phase = PacingDiag::SpawnBinderPhase();
        if (phase == PacingDiag::Kind::None)
            return;
        auto& capture = *static_cast<Recorder*>(context);
        const auto index = capture.next.fetch_add(1, std::memory_order_relaxed);
        if (index >= Recorder::capacity)
            return;
        auto& row = capture.rows[index];
        row.begin = PacingDiag::Counter();
        row.frame = PacingDiag::CurrentFrame();
        row.thread = GetCurrentThreadId();
        row.phase = static_cast<unsigned>(phase);
        row.count = count;
        row.vmState = vmState;
        size_t length = 0;
        const auto* stack = capture.dump(state, "F;lZ|", 10, &length);
        row.truncated = length >= sizeof(row.stack);
        if (length && stack)
            std::memcpy(row.stack, stack, (std::min)(length, sizeof(row.stack) - 1));
        row.end = PacingDiag::Counter();
    }

    inline void Start(lua_State* state)
    {
        if (!PacingDiag::SpawnPathEnabled() || recorder)
            return;
        const auto dll = GetModuleHandleW(L"lua51.dll");
        if (!dll)
            return;
        const auto start = reinterpret_cast<StartFunction>(GetProcAddress(dll, "luaJIT_profile_start"));
        const auto stop = reinterpret_cast<StopFunction>(GetProcAddress(dll, "luaJIT_profile_stop"));
        const auto dump = reinterpret_cast<DumpFunction>(GetProcAddress(dll, "luaJIT_profile_dumpstack"));
        if (!start || !stop || !dump)
            return;
        std::unique_ptr<Recorder> capture(new (std::nothrow) Recorder(state));
        if (!capture || !capture->rows)
            return;
        capture->stop = stop;
        capture->dump = dump;
        recorder = std::move(capture);
        // Line mode gives compiled traces polling points. This is diagnostic-only.
        start(state, "li1", SampleBinder, recorder.get());
    }

    inline void Stop(lua_State* state)
    {
        if (!recorder || recorder->state != state)
            return;
        recorder->stop(state);
        const auto capture = std::move(recorder);
        wchar_t directory[32768] = {};
        const auto length = GetEnvironmentVariableW(L"IXRAY_PACING_DIR", directory, 32768);
        if (!length || length >= 32768)
            return;
        const auto path = std::wstring(directory) + L"\\ixray_spawn_lua_" +
            std::to_wstring(GetCurrentProcessId()) + L"_" + std::to_wstring(++generation) + L".tsv";
        FILE* file = nullptr;
        if (_wfopen_s(&file, path.c_str(), L"wb") || !file)
            return;
        const auto total = capture->next.load(std::memory_order_relaxed);
        const auto stored = (std::min)(total, Recorder::capacity);
        std::fprintf(file, "#version=1,stored=%u,dropped=%u\n", stored, total - stored);
        std::fprintf(file, "qpc_begin\tqpc_end\tframe\ttid\tphase\tsamples\tvm_state\ttruncated\tstack\n");
        for (unsigned i = 0; i < stored; ++i)
        {
            auto& row = capture->rows[i];
            for (char* c = row.stack; *c; ++c)
                if (*c == '\t' || *c == '\r' || *c == '\n')
                    *c = ' ';
            std::fprintf(file, "%llu\t%llu\t%u\t%u\t%u\t%d\t%c\t%u\t%s\n",
                row.begin, row.end, row.frame, row.thread, row.phase, row.count,
                row.vmState, static_cast<unsigned>(row.truncated), row.stack);
        }
        std::fclose(file);
    }
}
