#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

using u16 = std::uint16_t;
#include "PHItemList.h"
#define R_ASSERT2(condition, description) do { if (!(condition)) std::abort(); } while (false)

namespace PacingDiag {
enum class Kind { SpawnActivationIsolate, SpawnActivationMaterialize };
struct SpawnSpan { SpawnSpan(Kind, unsigned) {} };
}
static int xr_strcmp(const char* left, const char* right)
{
    return std::char_traits<char>::compare(left, right, 2);
}

struct CPHObject
{
    DECLARE_PHLIST_ITEM(CPHObject)
public:
    bool active = true;
    bool body = true;
    int id = 0;
    unsigned changes = 0;
    virtual ~CPHObject() = default;
    virtual void FreezeContent() { R_ASSERT2(active, "active"); active = false; ++changes; }
    virtual void UnFreezeContent() { R_ASSERT2(!active, "frozen"); active = true; ++changes; }
};
struct CPHCharacter : CPHObject
{
    bool ActivationFreezeIsReversible() const { return body; }
    void FreezeContent() override { CPHObject::FreezeContent(); body = false; }
    void UnFreezeContent() override { CPHObject::UnFreezeContent(); body = true; }
};
struct CPHShell : CPHObject
{
    int count = 0;
    unsigned notifications = 0;
    bool ActivationFreezeIsReversible() const { return count <= 0; }
    void FreezeContent() override { CPHObject::FreezeContent(); --count; }
    void UnFreezeContent() override { CPHObject::UnFreezeContent(); if (++count > 0) ++notifications; }
};
struct UpdateStep { virtual ~UpdateStep() = default; };
struct IActivationWorldStep : UpdateStep {};
struct CPHWorld
{
    CPHItemList<CPHObject> m_objects, m_freezed_objects;
    CPHItemList<CPHObject> m_update_objects, m_freezed_update_objects;
    IActivationWorldStep* m_deferred_activation_step = nullptr;
    UpdateStep* m_update_callback = nullptr;
    bool b_world_freezed = false;
    bool Processing() const { return false; }
    bool IsFreezed() const { return b_world_freezed; }
    bool DeferFreezeForActivation();
    void MaterializeActivationFreeze();
    void Freeze();
    void UnFreeze();
};
#include "freeze_functions.inc"

struct Result
{
    std::vector<int> list;
    unsigned changes, notifications;
    bool enabled, materialized;
};
static Result run(bool candidate, bool has_contact, bool has_callback, bool unsafe_body,
                  bool unsafe_shell, bool unknown_callback)
{
    CPHWorld world;
    IActivationWorldStep guarded;
    UpdateStep original;
    world.m_update_callback = unknown_callback ? &original : &guarded;
    CPHCharacter first, second;
    CPHShell shell;
    CPHObject shape;
    first.id = 1;
    second.id = 2;
    shell.id = 3;
    shape.id = 4;
    first.body = !unsafe_body;
    shell.count = unsafe_shell ? 1 : 0;
    world.m_objects.push_back(&first);
    world.m_objects.push_back(&shell);
    world.m_objects.push_back(&second);
    bool deferred = candidate && world.DeferFreezeForActivation();
    if (!deferred) {
        world.m_objects.push_back(&shape);
        world.Freeze();
        world.m_freezed_objects.erase(&shape);
        shape.UnFreezeContent();
    }
    world.m_objects.push_back(&shape);
    if (has_contact || has_callback) {
        world.MaterializeActivationFreeze();
        R_ASSERT2(!first.active && !shell.active && !first.body, "observer sees the original frozen state");
    }
    const bool materialized = !world.m_deferred_activation_step;
    world.UnFreeze();
    std::vector<int> list;
    for (auto* object : world.m_objects) {
        R_ASSERT2(object->active, "all objects restored");
        list.push_back(object->id);
    }
    return {list, first.changes + shell.changes + second.changes,
            shell.notifications, first.body, materialized};
}

int main()
{
#ifdef _WIN32
    _putenv_s("IXRAY_SPAWN_ACTIVATION_FREEZE", "1");
#else
    setenv("IXRAY_SPAWN_ACTIVATION_FREEZE", "1", 1);
#endif
    for (unsigned bits = 0; bits != 32; ++bits) {
        const auto baseline = run(false, bits&1, bits&2, bits&4, bits&8, bits&16);
        const auto deferred = run(true, bits&1, bits&2, bits&4, bits&8, bits&16);
        R_ASSERT2(baseline.list == deferred.list && baseline.notifications == deferred.notifications &&
                  baseline.enabled == deferred.enabled, "phase transition is equivalent");
        R_ASSERT2(deferred.materialized == (bits != 0), "materialize before an observer or on fallback");
        R_ASSERT2(deferred.changes == (bits ? baseline.changes : 0), "skip only the reversible round trip");
    }
    std::cout << "32 freeze list, contact and callback ordering cases passed\n";
}
