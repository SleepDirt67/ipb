#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

using u8 = std::uint8_t;
using u16 = std::uint16_t;
using u32 = std::uint32_t;
using s64 = std::int64_t;
using BOOL = int;
using LPVOID = void*;
constexpr BOOL FALSE = 0;
constexpr BOOL TRUE = 1;
constexpr u16 BI_NONE = u16(-1);
constexpr u32 MAX_PARTS = 4;
constexpr u32 MAX_CHANNELS = 4;
constexpr u32 MAX_BLENDED = 16;
constexpr u32 MAX_BLENDED_POOL = MAX_PARTS * MAX_CHANNELS * MAX_BLENDED;
constexpr float END_EPS = 0.0001f;
using LPCSTR = const char*;
struct MotionID {
    u16 slot = u16(-1), idx = u16(-1);
    bool valid() const { return slot != u16(-1); }
    void set(u16 s, u16 i) { slot = s; idx = i; }
};
struct anim_notify { unsigned id; };
template<class T> using xr_vector = std::vector<T>;
template<class K, class V> using xr_hash_map = std::unordered_map<K, V>;
#define IC inline
#define VERIFY(value) do { if (!(value)) std::abort(); } while (false)
#define VERIFY2(value, msg) VERIFY(value)
#define NODEFAULT std::abort()
#define CopyMemory(destination, source, size) std::memcpy(destination, source, size)
#include "FixedVector.h"
template<class T> void clamp(T& value, T lower, T upper) { value = std::clamp(value, lower, upper); }

struct MotionNotify {
    std::unordered_map<float, std::vector<anim_notify*>> data;
    std::vector<float> order;
};
struct MotionSlot {
    struct Motions {
        std::map<std::pair<u16, u16>, MotionNotify> data;
        MotionNotify& motion_notify(u16 idx, u16 bone) { return data[{idx, bone}]; }
        const MotionNotify* find_motion_notify(u16 idx, u16 bone) const {
            const auto found = data.find({idx, bone});
            return found == data.end() ? nullptr : &found->second;
        }
    } motions;
};
struct CPartDef { bool Name = true; std::vector<u16> bones; };
struct Partition {
    CPartDef parts[MAX_PARTS];
    CPartDef& part(u16 i) { return parts[i]; }
    CPartDef& operator[](u16 i) { return parts[i]; }
};
struct Bone { u16 id; u16 GetSelfID() const { return id; } };
struct DebugSink { void fatal(int, const char*, LPCSTR) { std::abort(); } } Debug;
constexpr int DEBUG_INFO = 0;
void Msg(const char*) {}
struct Name {
    std::string text;
    LPCSTR c_str() const { return text.c_str(); }
    bool operator<(const Name& other) const { return text < other.text; }
};
using accel_map = std::map<Name, u16>;

#define MODEL_BODY() \
struct CKinematicsAnimated { \
    struct MotionLookup; \
    svector<CBlend, MAX_BLENDED_POOL> blend_pool; \
    svector<CBlend*, MAX_BLENDED * MAX_CHANNELS> blend_cycles[MAX_PARTS]; \
    svector<CBlend*, MAX_BLENDED> blend_fx; \
    std::vector<MotionSlot> m_Motions{1}; \
    Partition partition; \
    Partition* m_Partition = &partition; \
    std::vector<Bone*>* bones = nullptr; \
    std::vector<u16> started; \
    bool hasMotionNotifies = false; \
    void ChannelFactorsStartup() {} \
    void IBlend_Startup(); \
    CBlend* IBlend_Create() { for (auto& b : blend_pool) if (b.blend_state() == CBlend::eFREE_SLOT) return &b; return nullptr; } \
    void IBlendSetup(CBlend& b, u16, u8, MotionID, BOOL, float, float, float speed, BOOL, PlayCallback, LPVOID) \
    { b.set_accrue_state(); b.speed = speed; } \
    void LL_FadeCycle(u16, float, unsigned) {} \
    void LL_CloseCycle(u16, unsigned) {} \
    void Bone_Motion_Start_IM(Bone* bone, CBlend*) { started.push_back(bone->id); } \
    const char** getDebugName() { static const char* name = "fixture"; return &name; } \
    CBlend* LL_PlayCycle(u16, MotionID, BOOL, float, float, float, BOOL, PlayCallback, LPVOID, u8); \
};

namespace Stock {
class CBlend;
using PlayCallback = void (*)(CBlend*);
#include "StockBlend.inc"
MODEL_BODY()
#include "StockEngine.inc"
}
namespace Candidate {
class CBlend;
using PlayCallback = void (*)(CBlend*);
#include "CandidateBlend.inc"
MODEL_BODY()
#include "CandidateEngine.inc"
#include "Lookup.inc"
}

template<class Map>
std::vector<unsigned> callbacks(const Map& map) {
    std::vector<unsigned> result;
    for (const auto& [bone, slot] : map)
        for (const auto& frame : slot.keyframes)
            for (const auto* notify : frame.assigned)
                result.push_back(bone * 100 + notify->id);
    return result;
}

template<class Model>
double SpawnCohort() {
    const auto start = std::chrono::steady_clock::now();
    volatile unsigned checksum = 0;
    for (unsigned cohort = 0; cohort != 25; ++cohort) {
        std::vector<std::unique_ptr<Model>> models;
        for (unsigned i = 0; i != 38; ++i) {
            auto model = std::make_unique<Model>();
            model->IBlend_Startup();  // Copy
            model->IBlend_Startup();  // Spawn
            checksum = checksum + model->blend_pool.size();
            models.push_back(std::move(model));
        }
    }
    VERIFY(checksum == 25 * 38 * MAX_BLENDED_POOL);
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
}

int main() {
    std::vector<Bone> definition(74);
    std::vector<Bone*> bones;
    for (u16 i = 0; i < definition.size(); ++i) {
        definition[i].id = i;
        bones.push_back(&definition[i]);
    }
    Stock::CKinematicsAnimated a;
    Candidate::CKinematicsAnimated b;
    a.bones = b.bones = &bones;
    for (u16 i = 0; i < bones.size(); ++i) {
        a.partition.parts[i % MAX_PARTS].bones.push_back(i);
        b.partition.parts[i % MAX_PARTS].bones.push_back(i);
    }
    anim_notify event{7};
    for (bool hasNotifies : {false, true}) {
        b.hasMotionNotifies = hasNotifies;
        if (hasNotifies) {
            for (u16 bone : {1, 5, 17, 20, 39, 42, 53, 70}) {
                MotionNotify note;
                note.order = {0.5f, 1.5f};
                note.data[0.5f] = {&event};
                note.data[1.5f] = {&event, &event};
                a.m_Motions[0].motions.data[{1, bone}] = note;
                b.m_Motions[0].motions.data[{1, bone}] = note;
            }
        }
        for (unsigned reset = 0; reset != 20; ++reset) {
            a.IBlend_Startup();
            b.IBlend_Startup();
            a.started.clear();
            b.started.clear();
            for (u16 i = 0; i != 32; ++i) {
                const u16 part = (i * 3) % MAX_PARTS;
                const float speed = i % 2 ? -1.f : 1.f;
                auto* old = a.LL_PlayCycle(part, {0, 1}, TRUE, 1, 2, speed, FALSE, nullptr, nullptr, 0);
                auto* next = b.LL_PlayCycle(part, {0, 1}, TRUE, 1, 2, speed, FALSE, nullptr, nullptr, 0);
                VERIFY(old && next && a.started == b.started);
                const auto expected = callbacks(old->notifies);
                VERIFY((next->notifies ? callbacks(*next->notifies) : std::vector<unsigned>{}) == expected);
                if (hasNotifies) {
                    for (const auto& [bone, slot] : old->notifies)
                        VERIFY(next->notifies->at(bone).current_notify_index == slot.current_notify_index);
                }
                old->set_free_state();
                next->set_free_state();
            }
        }
    }

    using Lookup = Candidate::CKinematicsAnimated::MotionLookup;
    accel_map first{{Name{"walk"}, 4}, {Name{"Walk"}, 3}, {Name{"run"}, 7}};
    accel_map second{{Name{"walk"}, 11}, {Name{"jump"}, 18}};
    Lookup::Index index;
    Lookup::Insert(index, first, 0);
    Lookup::Insert(index, second, 1);
    VERIFY(Lookup::Find(index, "walk").slot == 1 && Lookup::Find(index, "walk").idx == 11);
    VERIFY(Lookup::Find(index, "Walk").slot == 0 && Lookup::Find(index, "Walk").idx == 3);
    VERIFY(Lookup::Find(index, "run").idx == 7 && Lookup::Find(index, "jump").idx == 18);
    VERIFY(!Lookup::Find(index, "RUN").valid() && !Lookup::Find(index, "").valid());

    std::vector<double> old, next;
    for (unsigned i = 0; i != 8; ++i) {
        if (i % 2) next.push_back(SpawnCohort<Candidate::CKinematicsAnimated>());
        old.push_back(SpawnCohort<Stock::CKinematicsAnimated>());
        if (!(i % 2)) next.push_back(SpawnCohort<Candidate::CKinematicsAnimated>());
    }
    std::sort(old.begin(), old.end());
    std::sort(next.begin(), next.end());
    std::printf("PASS: 1280 cycle comparisons, same bone order and keyframe callback order; slot precedence exact\n");
    std::printf("25 batches of 38 animation instance resets median %.3f -> %.3f ms\n",
        (old[3] + old[4]) / 2, (next[3] + next[4]) / 2);
}
