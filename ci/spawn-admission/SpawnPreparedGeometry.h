#pragma once

#include "SpawnActivationContacts.h"
#include <memory>
#include <optional>

namespace SpawnPreparation
{
namespace Geometry
{
constexpr unsigned maxPoses = 3;
constexpr unsigned maxFaces = 512;

struct Inputs
{
    const CDB::MODEL* model;
    std::array<Fvector, maxPoses> centers;
    Fvector halfSize;
    float expansion;
    unsigned count;
    unsigned fpMode;
    u16 object = 0;

    bool operator==(const Inputs& other) const
    {
        if (model != other.model || count != other.count ||
            (fpMode & 0xffc0u) != (other.fpMode & 0xffc0u) ||
            std::bit_cast<unsigned>(expansion) != std::bit_cast<unsigned>(other.expansion) ||
            std::memcmp(&halfSize.x, &other.halfSize.x, 3 * sizeof(float)))
            return false;
        for (unsigned i = 0; i < count; ++i)
            if (std::memcmp(&centers[i].x, &other.centers[i].x, 3 * sizeof(float)))
                return false;
        return true;
    }
};

struct Pose
{
    Fvector center;
    Fvector halfSize;
    Fvector queryExtent;
    std::vector<int> ids;
    std::vector<SpawnCollision::Face> faces;
};

}

struct ActivationResult
{
    const CDB::MODEL* model;
    unsigned fpMode;
    std::array<Geometry::Pose, Geometry::maxPoses> poses;
    unsigned count = 0;
    u16 object = 0;
};

namespace Geometry
{
inline std::optional<std::unique_ptr<ActivationResult>> PrepareGeometry(const Inputs& input)
{
#if defined(_M_X64) && !defined(DEBUG)
    const unsigned oldMode = _mm_getcsr();
    _mm_setcsr(input.fpMode);
    struct RestoreFloatingPoint
    {
        unsigned mode;
        ~RestoreFloatingPoint() { _mm_setcsr(mode); }
    } restore{oldMode};

    try
    {
        auto result = std::make_unique<ActivationResult>();
        result->model = input.model;
        result->object = input.object;
        result->fpMode = SpawnCollision::Scope::FloatingPointMode();
        CDB::COLLIDER collider;
        collider.box_options(0);
        // InitTriangle stores the address for the existing live collision code.
        // The detached calculations only read the level mesh.
        auto* triangles = const_cast<CDB::TRI*>(input.model->get_tris());
        const auto* vertices = input.model->get_verts();
        for (unsigned i = 0; i < input.count; ++i)
        {
            const auto& center = input.centers[i];
            auto& pose = result->poses[result->count];
            pose.center = center;
            // This is the stationary identity-box case of CollideBox.
            // The consumer checks all six float components against live ODE.
            pose.halfSize = input.halfSize;
            pose.halfSize.add(10.f * EPS_L);
            pose.queryExtent.mul(pose.halfSize, input.expansion);
            collider.box_query(input.model, center, pose.queryExtent);
            const auto count = collider.r_count();
            if (count < 0 || static_cast<unsigned>(count) > maxFaces)
                continue;
            pose.ids.resize(count);
            pose.faces.resize(count);
            const auto* query = count ? collider.r_begin() : nullptr;
            for (int j = 0; j < count; ++j)
            {
                const auto id = query[j].id;
                pose.ids[j] = id;
                auto& face = pose.faces[j];
                face.Vertices(triangles[id], vertices);
                if (!face.Broad(&center.x, pose.halfSize))
                    continue;
                Triangle triangle;
                face.TriangleAt(triangles + id, &center.x, triangle);
                if (triangle.dist < 0.f)
                    face.Exact(&center.x, pose.halfSize);
            }
            ++result->count;
        }
        if (result->count)
            return result;
    }
    catch (const std::bad_alloc&)
    {
    }
#endif
    return {};
}
}

namespace Geometry
{
inline Pose* Match(ActivationResult* result, const CDB::MODEL* model,
    const float* center, const Fvector& halfSize, const Fvector& queryExtent,
    unsigned fpMode)
{
    if (!result || result->model != model || result->fpMode != fpMode)
        return nullptr;
    for (unsigned i = 0; i < result->count; ++i)
    {
        auto& pose = result->poses[i];
        if (std::memcmp(&pose.center.x, center, 3 * sizeof(float)) ||
            std::memcmp(&pose.halfSize.x, &halfSize.x, 3 * sizeof(float)) ||
            std::memcmp(&pose.queryExtent.x, &queryExtent.x, 3 * sizeof(float)))
            continue;
        return &pose;
    }
    return nullptr;
}
}
}
