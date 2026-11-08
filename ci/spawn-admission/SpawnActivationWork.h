#pragma once

#include <memory>

namespace CDB { class MODEL; }
class IPhysicsShellHolder;

namespace SpawnPreparation
{
class ActivationWork;
struct ActivationResult;

XRPHYSICS_API ActivationWork* StartActivationWork(const CDB::MODEL* model,
    std::shared_ptr<const void> binder = {});
XRPHYSICS_API void StopActivationWork(ActivationWork*& work);
XRPHYSICS_API void SubmitActivation(ActivationWork* work, u16 object,
    const Fvector* centers, unsigned count, const Fvector& halfSize, bool speculative);

// Binds a detached result to the exact client object. Nested dispatch
// restores the outer owner, including on a miss or unsupported spawn.
class XRPHYSICS_API ActivationScope
{
    friend void StopActivationWork(ActivationWork*& work);
    ActivationScope* parent_;
    ActivationWork* work_;
    const IPhysicsShellHolder* owner_;
    u16 id_;
    ActivationResult* prepared_ = nullptr;

public:
    ActivationScope(ActivationWork* work, u16 id, const IPhysicsShellHolder* owner);
    ~ActivationScope();
    ActivationScope(const ActivationScope&) = delete;
    ActivationScope& operator=(const ActivationScope&) = delete;

    static ActivationResult* For(const IPhysicsShellHolder* owner);
    static std::shared_ptr<const void> PreparedBinder(const IPhysicsShellHolder* owner);
};
}
