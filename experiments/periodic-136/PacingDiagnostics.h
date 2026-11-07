#pragma once
#include <cstdint>

// Independent of the expensive PR17 scopes. No fields in gameplay classes.
namespace PacingDiag
{
    enum class Kind : unsigned {
        OnIdle = 1, Render, Present, WaitWorkers, PreRender, Discord,
        SceneRender, Gamma, Occlusion, Pump, Reset, SyncPaint, FrameState,
        BeginRender, SyncFailure
    };
    ENGINE_API bool Enabled();
    ENGINE_API bool Deep();
    ENGINE_API unsigned long long Counter();
    ENGINE_API void SetFrame(unsigned frame, unsigned flags, unsigned gameTime);
    ENGINE_API unsigned CurrentFrame();
    ENGINE_API void Record(Kind kind, unsigned frame, unsigned long long begin,
        unsigned long long end, unsigned long long payload = 0);
    ENGINE_API bool SyncVisible();
    ENGINE_API void Flush();

    class Span
    {
        Kind kind_;
        bool active_;
        unsigned frame_;
        unsigned long long start_, payload_;
    public:
        explicit Span(Kind kind, bool deep = false, unsigned long long payload = 0)
            : kind_(kind), active_(deep ? Deep() : Enabled()),
              frame_(active_ ? CurrentFrame() : 0),
              start_(active_ ? Counter() : 0), payload_(payload) {}
        ~Span() { if (active_) Record(kind_, frame_, start_, Counter(), payload_); }
        Span(const Span&) = delete;
        Span& operator=(const Span&) = delete;
    };
}
