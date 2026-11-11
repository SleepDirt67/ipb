#pragma once
#include "BinderCaptureFormat.h"

struct lua_State;

namespace BinderCapture
{
    ENGINE_API bool DispatchActive();
    ENGINE_API void SaveLoaded(const char* name);

    class ENGINE_API Queue
    {
        uint64_t previous_ = 0;
        bool active_ = false;
    public:
        Queue();
        ~Queue();
        Queue(const Queue&) = delete;
        Queue& operator=(const Queue&) = delete;
    };

    class ENGINE_API Dispatch
    {
        IxDispatchRecord* row_ = nullptr;
        IxDispatchRecord* parent_ = nullptr;
    public:
        Dispatch(unsigned id, unsigned parentId, uint64_t classId, const char* section);
        ~Dispatch();
        void Stalker(bool stalker);
        void Result(bool succeeded);
        Dispatch(const Dispatch&) = delete;
        Dispatch& operator=(const Dispatch&) = delete;
    };

    class ENGINE_API Scope
    {
        lua_State* vm_ = nullptr;
        IxBinderRecord* row_ = nullptr;
        void* parent_ = nullptr;
        IxBinderRecord* outer_ = nullptr;
    public:
        Scope(unsigned kind, lua_State* vm);
        ~Scope();
        void Fail();
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;
    };
}
