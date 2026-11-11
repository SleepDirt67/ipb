#include "BinderCapture.h"
#include <array>
#include <cstring>
#include <cstddef>

namespace BinderCapture
{
    namespace
    {
        constexpr unsigned binderLimit = 500, dispatchLimit = 1600;
        constexpr unsigned firstSlots = 2, worstSlots = 4, controlSlots = 2, structuralSlots = 1;
        constexpr unsigned retainedSlots = firstSlots + worstSlots + controlSlots + structuralSlots;

        struct Frame
        {
            std::array<IxBinderRecord, binderLimit> binders;
            std::array<IxDispatchRecord, dispatchLimit> dispatches;
            uint64_t begin = 0, end = 0, rank = 0, copyTicks = 0;
            unsigned binderCount = 0, dispatchCount = 0;
            unsigned lostBinders = 0, lostDispatches = 0, invalid = 0;

            void Clear()
            {
                begin = end = rank = copyTicks = 0;
                binderCount = dispatchCount = lostBinders = lostDispatches = invalid = 0;
            }

            void Copy(const Frame& src)
            {
                const auto started = PacingDiag::Counter();
                begin = src.begin;
                end = src.end;
                rank = src.rank;
                binderCount = src.binderCount;
                dispatchCount = src.dispatchCount;
                lostBinders = src.lostBinders;
                lostDispatches = src.lostDispatches;
                invalid = src.invalid;
                std::copy_n(src.binders.begin(), binderCount, binders.begin());
                std::copy_n(src.dispatches.begin(), dispatchCount, dispatches.begin());
                copyTicks = PacingDiag::Counter() - started;
            }
        };
        static_assert(sizeof(Frame) * (retainedSlots + 1) <= 32 * 1024 * 1024,
            "Binder capture buffers exceed their documented budget");

        using Exchange = void* (__cdecl*)(lua_State*, void*);
        using Status = void (__cdecl*)(uint32_t*, int);
        using Methods = const IxMethodInfo* (__cdecl*)(unsigned*);
        struct State
        {
            Frame working;
            std::array<Frame, retainedSlots> retained;
            std::array<unsigned, 65536> generation{};
            IxCaptureHeader header{};
            DWORD tid = GetCurrentThreadId();
            HANDLE stopEvent = nullptr;
            Exchange exchange = nullptr;
            Status status = nullptr;
            Methods methods = nullptr;
            std::wstring path;
            uint64_t next = 0, queue = 0, activeSince = 0, previousPresent = 0, previousState = 0;
            uint64_t nextControl = 0;
            IxBinderRecord* binder = nullptr;
            IxDispatchRecord* dispatch = nullptr;
            unsigned controls = 0, completeStrong = 0;
            bool eightRoot = false, saved = false;

            State()
            {
                // Prefault the records before gameplay. Counts control which bytes are emitted.
                memset(working.binders.data(), 0, sizeof(working.binders));
                memset(working.dispatches.data(), 0, sizeof(working.dispatches));
                for (auto& frame : retained)
                {
                    memset(frame.binders.data(), 0, sizeof(frame.binders));
                    memset(frame.dispatches.data(), 0, sizeof(frame.dispatches));
                }
                memcpy(header.magic, "IXBIND5", 8);
                header.pid = GetCurrentProcessId();
                LARGE_INTEGER f{};
                QueryPerformanceFrequency(&f);
                header.frequency = f.QuadPart;
                header.binder_size = sizeof(IxBinderRecord);
                header.dispatch_size = sizeof(IxDispatchRecord);
                wchar_t output[32768]{}, name[128]{};
                if (GetEnvironmentVariableW(L"IXRAY_PACING_DIR", output, 32768))
                    path = std::wstring(output) + L"\\binder_scopes.bin";
                if (GetEnvironmentVariableW(L"IXRAY_BINDER_STOP_EVENT", name, 128))
                    stopEvent = OpenEventW(EVENT_MODIFY_STATE, FALSE, name);
                const auto lua = GetModuleHandleW(L"lua51.dll");
                exchange = reinterpret_cast<Exchange>(GetProcAddress(lua, "xrBinderCaptureContext"));
                status = reinterpret_cast<Status>(GetProcAddress(lua, "xrBinderCaptureStatus"));
                methods = reinterpret_cast<Methods>(GetProcAddress(lua, "xrBinderCaptureMethods"));
            }

            ~State()
            {
                if (stopEvent)
                    CloseHandle(stopEvent);
            }
        };
        std::unique_ptr<State> state;
        std::atomic<bool> frozen{false};
        std::atomic<bool> observing{false};
        bool Armed()
        {
            static const bool enabled = [] {
                wchar_t value[2]{};
                return GetEnvironmentVariableW(L"IXRAY_BINDER_CAPTURE", value, 2) == 1 && value[0] == L'1';
            }();
            return enabled;
        }

        State* Current()
        {
            // State and its buffers are owned by the engine's main thread.
            return state && state->tid == GetCurrentThreadId() && !frozen.load(std::memory_order_relaxed)
                ? state.get() : nullptr;
        }

        void Freeze(State& s, unsigned reason, uint64_t now)
        {
            s.header.stop_reason = reason;
            s.header.observation_end = now;
            frozen.store(true, std::memory_order_release);
            if (s.stopEvent)
                SetEvent(s.stopEvent);
        }
    }

    bool Enabled() { return Armed(); }

    bool Frozen() { return frozen.load(std::memory_order_relaxed); }
    bool Observing() { return observing.load(std::memory_order_relaxed); }

    void OnFrame(uint64_t qpc, unsigned flags)
    {
        if (!Armed() || Frozen())
            return;
        if (!state)
            state = std::unique_ptr<State>(new State{});
        auto& s = *state;
        const bool active = (flags & 31u) == 17u && s.header.save_loaded;
        observing.store(active, std::memory_order_relaxed);
        if (!active)
        {
            s.activeSince = s.previousPresent = s.previousState = 0;
            s.working.Clear();
            return;
        }
        if (!s.activeSince)
            s.activeSince = qpc;
        if (s.previousState)
            s.header.active_ticks += qpc - s.previousState;
        s.previousState = qpc;
        if (!s.header.observation_begin && qpc - s.activeSince >= 2 * s.header.frequency)
            s.header.observation_begin = qpc;
    }

    void OnPresent(uint64_t begin, uint64_t end)
    {
        auto* s = Current();
        if (!s)
            return;
        auto& f = s->working;
        const uint64_t frequency = s->header.frequency;
        if (!s->activeSince || begin < s->activeSince || begin - s->activeSince < 2 * frequency)
        {
            f.Clear();
            return;
        }
        const auto previous = s->previousPresent;
        s->previousPresent = begin;
        if (!previous)
        {
            f.Clear();
            return;
        }
        f.begin = previous;
        f.end = begin;
        f.rank = begin - previous;

        unsigned roots = 0;
        uint64_t spawn = 0, binder = 0;
        for (unsigned i = 0; i < f.dispatchCount; ++i)
        {
            const auto& row = f.dispatches[i];
            if (!row.parent_scope)
                spawn += row.end - row.begin;
            if (row.stalker && row.parent_object == 0xffff)
                ++roots;
        }
        for (unsigned i = 0; i < f.binderCount; ++i)
        {
            const auto& row = f.binders[i];
            if (row.parent_scope == row.dispatch)
                binder += row.end - row.begin;
        }
        const bool strong = f.rank >= 40 * frequency / 1000 &&
            (spawn >= 20 * frequency / 1000 || binder >= 12 * frequency / 1000);
        const bool large = roots >= 6;

        s->header.binder_dropped += f.lostBinders;
        s->header.dispatch_dropped += f.lostDispatches;
        if (large)
        {
            ++s->header.large;
            auto& slot = s->retained[retainedSlots - 1];
            if (slot.rank < f.rank)
                slot.Copy(f);
        }
        if (strong)
        {
            if (s->header.strong < firstSlots)
                s->retained[s->header.strong].Copy(f);
            ++s->header.strong;
            auto first = s->retained.begin() + firstSlots;
            auto lowest = std::min_element(first, first + worstSlots,
                [](const Frame& a, const Frame& b) { return a.rank < b.rank; });
            if (lowest->rank < f.rank && (s->header.strong > firstSlots))
                lowest->Copy(f);
            if (!(f.lostBinders || f.lostDispatches || f.invalid))
            {
                ++s->completeStrong;
                s->eightRoot |= roots >= 8;
            }
        }
        if (!strong && !large && f.rank < 20 * frequency / 1000 && s->controls < controlSlots &&
            s->header.active_ticks >= s->nextControl)
        {
            s->retained[firstSlots + worstSlots + s->controls++].Copy(f);
            s->nextControl = s->header.active_ticks + 30 * frequency;
        }
        f.Clear();
        if (s->header.active_ticks >= 360 * frequency)
            Freeze(*s, 2, end);
        else if (s->header.active_ticks >= 180 * frequency && s->completeStrong >= 2 && s->eightRoot)
            Freeze(*s, 1, end);
    }

    void SaveLoaded(const char* name)
    {
        if (!Armed())
            return;
        if (!state)
            state = std::unique_ptr<State>(new State{});
        auto* s = Current();
        if (!s)
            return;
        char expected[80]{};
        if (GetEnvironmentVariableA("IXRAY_BINDER_SAVE_ALIAS", expected, 80) && strcmp(name, expected) == 0)
            s->header.save_loaded = PacingDiag::Counter();
    }

    void Flush()
    {
        auto* s = state.get();
        if (!s || s->saved || s->path.empty())
            return;
        s->saved = true;
        if (!Frozen())
            Freeze(*s, 3, PacingDiag::Counter());
        if (s->status)
        {
            uint32_t stats[4]{};
            s->status(stats, 0);
            s->header.wrapper_installs = stats[0];
            s->header.wrapper_refused = stats[1];
            s->header.script_matches = stats[2];
            s->header.script_misses = stats[3];
        }
        for (const auto& frame : s->retained)
        {
            s->header.binders += frame.binderCount;
            s->header.dispatches += frame.dispatchCount;
            if (frame.rank) ++s->header.episodes;
        }
        const auto* methods = s->methods ? s->methods(&s->header.methods) : nullptr;
        FILE* output = nullptr;
        if (_wfopen_s(&output, s->path.c_str(), L"wb") || !output)
            return;
        fwrite(&s->header, sizeof(s->header), 1, output);
        for (unsigned i = 0; i < retainedSlots; ++i)
        {
            const auto& frame = s->retained[i];
            if (frame.rank)
            {
                const IxEpisodeRecord episode{frame.begin, frame.end, frame.copyTicks, frame.binderCount,
                    frame.dispatchCount, frame.lostBinders, frame.lostDispatches, frame.invalid, i};
                fwrite(&episode, sizeof(episode), 1, output);
            }
        }
        for (const auto& frame : s->retained)
            fwrite(frame.binders.data(), sizeof(IxBinderRecord), frame.binderCount, output);
        for (const auto& frame : s->retained)
            fwrite(frame.dispatches.data(), sizeof(IxDispatchRecord), frame.dispatchCount, output);
        if (methods) fwrite(methods, sizeof(IxMethodInfo), s->header.methods, output);
        fclose(output);
    }

    bool DispatchActive()
    {
        if (!Armed())
            return false;
        const auto* s = Current();
        return s && s->dispatch;
    }

    Queue::Queue()
    {
        auto* s = Current();
        if (!s)
            return;
        active_ = true;
        previous_ = s->queue;
        s->queue = ++s->next;
    }

    Queue::~Queue()
    {
        auto* s = Current();
        if (s && active_)
            s->queue = previous_;
    }

    Dispatch::Dispatch(unsigned id, unsigned parentId, uint64_t classId, const char* section)
    {
        auto* s = Current();
        if (!s)
            return;
        parent_ = s->dispatch;
        const auto generation = ++s->generation[id];
        auto& f = s->working;
        if (f.dispatchCount == dispatchLimit)
        {
            ++f.lostDispatches;
            s->dispatch = nullptr;
            return;
        }
        row_ = &f.dispatches[f.dispatchCount++];
        *row_ = {};
        row_->frame = PacingDiag::CurrentFrame();
        row_->tid = s->tid;
        row_->scope = ++s->next;
        row_->parent_scope = parent_ ? parent_->scope : 0;
        row_->queue = s->queue;
        row_->class_id = classId;
        row_->object = id;
        row_->generation = generation;
        row_->parent_object = parentId;
        row_->parent_generation = parentId == 0xffff ? 0 : s->generation[parentId];
        strncpy_s(row_->section, section ? section : "", _TRUNCATE);
        s->dispatch = row_;
        row_->begin = PacingDiag::Counter();
    }

    Dispatch::~Dispatch()
    {
        auto* s = Current();
        if (!s)
            return;
        if (row_)
            row_->end = PacingDiag::Counter();
        s->dispatch = parent_;
    }

    void Dispatch::Stalker(bool stalker)
    {
        if (row_)
            row_->stalker = stalker;
    }

    void Dispatch::Result(bool succeeded)
    {
        if (row_)
            row_->result = succeeded ? 1 : 2;
    }

    Scope::Scope(unsigned kind, lua_State* vm)
    {
        auto* s = Current();
        if (!s || !s->dispatch)
            return;
        auto& f = s->working;
        if (f.binderCount == binderLimit)
        {
            ++f.lostBinders;
            return;
        }
        row_ = &f.binders[f.binderCount++];
        // The site table is sparse. Its used slots are reset on insertion.
        memset(row_, 0, offsetof(IxBinderRecord, native));
        memset(row_->native_hash, 0, sizeof(row_->native_hash));
        memset(row_->first_functions, 0, sizeof(row_->first_functions));
        row_->scope = ++s->next;
        outer_ = s->binder;
        row_->parent_scope = outer_ ? outer_->scope : s->dispatch->scope;
        row_->dispatch = s->dispatch->scope;
        row_->object = s->dispatch->object;
        row_->generation = s->dispatch->generation;
        row_->frame = s->dispatch->frame;
        row_->tid = s->tid;
        row_->kind = kind;
        row_->begin = PacingDiag::Counter();
        if (vm && s->exchange)
        {
            vm_ = vm;
            parent_ = s->exchange(vm_, row_);
        }
        else
            row_->flags |= IX_NO_VM;
        s->binder = row_;
    }

    Scope::~Scope()
    {
        if (!row_)
            return;
        auto* s = Current();
        if (vm_ && s->exchange)
            s->exchange(vm_, parent_);
        else
            row_->end = PacingDiag::Counter();
        if (s->dispatch->stalker && row_->kind == 3 && !row_->marks)
            row_->flags |= IX_MARKER_MISSING;
        if (row_->flags)
            ++s->working.invalid;
        s->binder = outer_;
    }

    void Scope::Fail()
    {
        if (row_)
            row_->flags |= IX_NONLOCAL_EXIT;
    }
}
