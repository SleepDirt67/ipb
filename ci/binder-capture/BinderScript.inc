// Included by script_storage.cpp. Only the diagnostic VM sees the marker.
#include <windows.h>
#include "BinderScript.generated.inc"

namespace BinderScript
{
    bool Enabled()
    {
        static const bool result = [] {
            wchar_t value[2]{};
            return GetEnvironmentVariableW(L"IXRAY_BINDER_CAPTURE", value, 2) == 1 && value[0] == L'1';
        }();
        return result;
    }

    template<class Function>
    Function Resolve(const char* name)
    {
        const HMODULE library = GetModuleHandleW(L"lua51.dll");
        return reinterpret_cast<Function>(GetProcAddress(library, name));
    }

    void Install(lua_State* vm)
    {
        if (!Enabled())
            return;
        const auto install = Resolve<int (__cdecl*)(lua_State*)>("xrBinderCaptureInstall");
        const auto marker = Resolve<void (__cdecl*)(lua_State*)>("xrBinderCaptureRegister");
        if (install && marker && install(vm))
            marker(vm);
    }

    std::string_view Source(lua_State* vm, std::string_view input)
    {
        const auto status = Resolve<void (__cdecl*)(uint32_t*, int)>("xrBinderCaptureStatus");
        // If an existing wrapper owns the slot, load the original Lua source.
        lua_getglobal(vm, "__ixray_binder_capture_phase");
        const bool installed = lua_iscfunction(vm, -1);
        lua_pop(vm, 1);
        if (!installed || !status)
            return input;
        size_t index = 0;
        for (size_t i = 0; i < input.size(); ++i)
        {
            if (input[i] == '\r' && i + 1 < input.size() && input[i + 1] == '\n')
                continue;
            if (index == sizeof(originalMotivator) ||
                static_cast<unsigned char>(input[i]) != originalMotivator[index++])
            {
                status(nullptr, -1);
                return input;
            }
        }
        if (index != sizeof(originalMotivator))
        {
            status(nullptr, -1);
            return input;
        }
        status(nullptr, 1);
        return {reinterpret_cast<const char*>(markedMotivator), sizeof(markedMotivator)};
    }
}
