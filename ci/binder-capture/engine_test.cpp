#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <memory>
#include <string>

#define ENGINE_API
static uint64_t qpc = 100000000;
namespace PacingDiag
{
    uint64_t Counter() { return ++qpc; }
    unsigned CurrentFrame() { return static_cast<unsigned>(qpc / 1000); }
}

#include "BinderCaptureEngine.inc"

#define REQUIRE(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s at line %d\n", #condition, __LINE__); return 1; } } while (0)

int main()
{
    BinderCapture::OnFrame(qpc, 17);
    BinderCapture::SaveLoaded("fixture");
    auto& s = *BinderCapture::state;
    const auto frequency = s.header.frequency;
    BinderCapture::OnFrame(qpc, 17);
    qpc += 3 * frequency;
    BinderCapture::OnFrame(qpc, 17);
    BinderCapture::OnPresent(qpc, qpc + 1);

    for (unsigned frame = 0; frame != 8; ++frame)
    {
        for (unsigned id = 1; id <= 9; ++id)
        {
            BinderCapture::Queue queue;
            BinderCapture::Dispatch dispatch(id, 0xffff, 0x53, "fixture_stalker");
            dispatch.Stalker(true);
            {
                BinderCapture::Scope binder(3, nullptr);
                qpc += frequency / 100;
            }
            dispatch.Result(true);
        }
        qpc += frame * frequency / 1000;
        BinderCapture::OnPresent(qpc, qpc + 1);
    }
    REQUIRE(s.header.strong == 8 && s.header.large == 8);
    REQUIRE(s.retained[0].binderCount == 9 && s.retained[1].binderCount == 9);
    REQUIRE(s.retained[0].dispatches[0].generation == 1 && s.retained[1].dispatches[0].generation == 2);
    REQUIRE(s.retained.back().dispatches[0].generation == 8);
    for (unsigned id = 1; id <= BinderCapture::dispatchLimit + 1; ++id)
    {
        BinderCapture::Dispatch dispatch(id, 0xffff, 0x44, "overflow");
        dispatch.Result(true);
    }
    qpc += frequency / 1000;
    BinderCapture::OnPresent(qpc, qpc + 1);
    REQUIRE(s.header.dispatch_dropped == 1);
    BinderCapture::Flush();
    REQUIRE(s.header.binders >= 18 && s.header.episodes >= 6);
    std::puts("Engine retention, structural episodes, recycled object ID and overflow passed");
}
