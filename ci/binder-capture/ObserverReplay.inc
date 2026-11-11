#include "src/xrEngine/BinderCaptureFormat.h"
#include <algorithm>
#include <windows.h>

namespace ObserverReplay
{
    using Exchange = void* (__cdecl*)(lua_State*, void*);
    using Setup = int (__cdecl*)(lua_State*);
    using Mark = void (__cdecl*)(lua_State*);
    using Clock = std::chrono::steady_clock;

    enum Mode { Off, Boundaries, Full };
    Mode mode = Off;
    Exchange exchange = nullptr;
    Mark mark = nullptr;
    uint64_t calls = 0, elapsed = 0;
    unsigned completed = 0;

    void Configure(lua_State* vm)
    {
        elapsed = calls = completed = 0;
        if (mode != Full)
            return;
        const auto lua = GetModuleHandleW(L"lua51.dll");
        const auto setup = reinterpret_cast<Setup>(GetProcAddress(lua, "xrBinderCaptureInstall"));
        exchange = reinterpret_cast<Exchange>(GetProcAddress(lua, "xrBinderCaptureContext"));
        mark = reinterpret_cast<Mark>(GetProcAddress(lua, "xrBinderCaptureRegister"));
        Require(setup && exchange && mark && setup(vm), "observer LuaJIT exports");
        mark(vm);
    }

    struct Scope
    {
        Clock::time_point begin;
        IxBinderRecord record;
        void* previous = nullptr;
        lua_State* vm = nullptr;

        void Enter(lua_State* L)
        {
            begin = Clock::now();
            if (mode == Full)
            {
                vm = L;
                record = {};
                previous = exchange(vm, &record);
                const int top = lua_gettop(L);
                lua_getglobal(L, "__ixray_binder_capture_phase");
                lua_pushinteger(L, 8);
                const auto result = lua_pcall(L, 1, 0, 0);
                Require(!result && lua_gettop(L) == top, "observer phase mark");
            }
        }

        void Leave()
        {
            if (vm)
            {
                exchange(vm, previous);
                Require(record.marks == (1u << 8) && !(record.flags & ~IX_NATIVE_OVERFLOW),
                    "observer captured complete Lua interval");
                for (unsigned i = 0; i < record.address_count; ++i)
                    calls += record.native[i].measure.count;
            }
            if (mode != Off)
                ++completed;
            elapsed += std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - begin).count();
        }
    };

    double Milliseconds() { return elapsed / 1000000.0; }

    double P95(std::vector<double> values)
    {
        std::sort(values.begin(), values.end());
        return values[(95 * values.size() + 99) / 100 - 1];
    }
}
