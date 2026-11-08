// Included once, by IActivationShape.cpp.
#include "SpawnPreparationQueue.h"
#include "SpawnPreparedGeometry.h"
#include "../xrEngine/PacingDiagnostics.h"

namespace SpawnPreparation
{
namespace
{
using Geometry::Inputs;
using Geometry::maxPoses;
auto Prepare(const Inputs& input)
{
    PacingDiag::SpawnSpan span(PacingDiag::Kind::SpawnPrepareWorker, input.object);
    return Geometry::PrepareGeometry(input);
}
thread_local ActivationScope* currentActivation = nullptr;
}

class ActivationWork
{
public:
    const CDB::MODEL* model;
    const float expansion;
    const std::shared_ptr<const void> binder;
    Queue<Inputs, std::unique_ptr<ActivationResult>, decltype(&Prepare)> queue;

    ActivationWork(const CDB::MODEL* source, float queryExpansion, std::shared_ptr<const void> preparedBinder)
        : model(source), expansion(queryExpansion), binder(std::move(preparedBinder)), queue(&Prepare) {}
};

ActivationWork* StartActivationWork(const CDB::MODEL* model,
    std::shared_ptr<const void> binder)
{
#if defined(_M_X64) && !defined(DEBUG)
    const char* setting = std::getenv("IXRAY_SPAWN_PREPARE");
    if (model && setting && xr_strcmp(setting, "1") == 0)
    {
        try
        {
            return new ActivationWork(model, ph_console::ph_tri_query_ex_aabb_rate, std::move(binder));
        }
        catch (const std::system_error&)
        {
        }
        catch (const std::bad_alloc&)
        {
        }
    }
#endif
    return nullptr;
}

void StopActivationWork(ActivationWork*& work)
{
    if (!work)
        return;
    // A nested game callback may initiate level teardown on this thread.
    for (auto* scope = currentActivation; scope; scope = scope->parent_)
        if (scope->work_ == work)
            scope->work_ = nullptr;
    delete std::exchange(work, nullptr);
}

void SubmitActivation(ActivationWork* work, u16 id, const Fvector* centers, unsigned count,
    const Fvector& halfSize, bool speculative)
{
#if defined(_M_X64) && !defined(DEBUG)
    if (!work || count == 0 || count > maxPoses || !_valid(halfSize) ||
        halfSize.x <= 0.f || halfSize.y <= 0.f || halfSize.z <= 0.f ||
        halfSize.x > 5.f || halfSize.y > 5.f || halfSize.z > 5.f)
        return;
    Inputs input{work->model, {}, halfSize, work->expansion, count, _mm_getcsr(), id};
    for (unsigned i = 0; i < count; ++i)
    {
        if (!_valid(centers[i]))
            return;
        input.centers[i] = centers[i];
    }
    if (work->queue.Submit(id, input, speculative))
    {
        PacingDiag::SpawnSpan accepted(PacingDiag::Kind::SpawnPrepareSubmit, id | (speculative ? 1u << 16 : 0u));
    }
#endif
}

ActivationScope::ActivationScope(ActivationWork* work, u16 id, const IPhysicsShellHolder* owner)
    : parent_(currentActivation), work_(work), owner_(owner), id_(id)
{
    currentActivation = this;
}

ActivationScope::~ActivationScope()
{
    currentActivation = parent_;
    if (work_ && owner_)
        work_->queue.Retire(id_);
    delete prepared_;
}

ActivationResult* ActivationScope::For(const IPhysicsShellHolder* owner)
{
    auto* scope = currentActivation;
    if (!scope || !scope->work_ || !scope->owner_ || scope->owner_ != owner)
        return nullptr;
    if (auto* result = scope->prepared_)
        return result;
    if (auto result = scope->work_->queue.Take(scope->id_))
        scope->prepared_ = result->release();
    else
    {
        PacingDiag::SpawnSpan miss(PacingDiag::Kind::SpawnPrepareMiss, scope->id_);
    }
    return scope->prepared_;
}

std::shared_ptr<const void> ActivationScope::PreparedBinder(const IPhysicsShellHolder* owner)
{
    auto* scope = currentActivation;
    if (!scope || !scope->work_ || !owner || scope->owner_ != owner)
        return {};
    return scope->work_->binder;
}

SpawnCollision::Face* TakeActivationGeometry(ActivationResult* result, const CDB::MODEL* model,
    const float* center, const Fvector& halfSize, const Fvector& queryExtent,
    unsigned fpMode, SpawnCollision::Plan<SpawnCollision::Face>& plan,
    xr_vector<int>& ids, bool& matched)
{
    auto* pose = Geometry::Match(result, model, center, halfSize, queryExtent, fpMode);
    matched = pose != nullptr;
    if (!result)
        return nullptr;
    PacingDiag::SpawnSpan selection(pose ? PacingDiag::Kind::SpawnPrepareUse :
        PacingDiag::Kind::SpawnPrepareMiss, result->object);
    if (!pose)
        return nullptr;
    return Geometry::Admit(*pose, plan, ids);
}
}
