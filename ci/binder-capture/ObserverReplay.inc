#include "src/xrEngine/BinderCaptureFormat.h"
#include <algorithm>
#include <cstddef>
#include <cmath>
#include <iterator>
#include <cstring>
#include <windows.h>

namespace ObserverReplay
{
    using Exchange = void* (__cdecl*)(lua_State*, void*);
    using Setup = int (__cdecl*)(lua_State*);
    using Mark = void (__cdecl*)(lua_State*);

    enum Mode { Off, Boundaries, Full, OffWitness };
    Mode mode = Off;
    Exchange exchange = nullptr;
    Mark mark = nullptr;
    uint64_t calls = 0, timed = 0, elapsed = 0;
    unsigned completed = 0;
    struct Window { uint64_t begin, end; };
    Window windows[10];

    uint64_t Counter()
    {
        LARGE_INTEGER now{};
        QueryPerformanceCounter(&now);
        return now.QuadPart;
    }

    void Configure(lua_State* vm)
    {
        elapsed = calls = timed = completed = 0;
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
        uint64_t begin;
        IxBinderRecord record;
        void* previous = nullptr;
        lua_State* vm = nullptr;

        void Enter(lua_State* L)
        {
            begin = Counter();
            if (mode == Full)
            {
                vm = L;
                memset(&record, 0, offsetof(IxBinderRecord, native));
                memset(record.native_hash, 0, sizeof(record.native_hash));
                memset(record.first_functions, 0, sizeof(record.first_functions));
                record.scope = completed;
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
                calls += record.native_seen;
                timed += record.native_sampled;
            }
            const auto end = Counter();
            if (completed < std::size(windows))
                windows[completed] = {begin, end};
            ++completed;
            elapsed += end - begin;
        }
    };

    double Milliseconds()
    {
        LARGE_INTEGER frequency{};
        QueryPerformanceFrequency(&frequency);
        return 1000.0 * elapsed / frequency.QuadPart;
    }

    double P95(std::vector<double> values)
    {
        std::sort(values.begin(), values.end());
        return values[(95 * values.size() + 99) / 100 - 1];
    }
}
