#pragma once

#include <array>
#include <bit>
#include <cstdint>
#include <new>
#include <vector>

namespace SpawnCollision
{
// An activation owns one plan. A new CDB result replaces all rows. A changed
// box pose retains the mesh inputs and discards only the geometric results.
template<class Face>
class Plan
{
    struct Row
    {
        Face face;
        std::uint32_t poseRevision = 0;
    };
    std::vector<Row> rows_;
    std::uint32_t poseRevision_ = 1;
    using Pose = std::array<std::uint32_t, 6>;
    Pose pose_{};
    Pose staticQuery_{};
    const void* staticModel_ = nullptr;
    unsigned staticMode_ = 0;
    std::size_t staticCount_ = 0;
    unsigned mode_ = 0;
    bool ready_ = false;
    const void* triangles_ = nullptr;
    const void* vertices_ = nullptr;

    static Pose Encode(const float* center, const float* extent)
    {
        Pose pose;
        for (std::size_t i = 0; i < pose.size(); ++i)
            pose[i] = std::bit_cast<std::uint32_t>(i < 3 ? center[i] : extent[i - 3]);
        return pose;
    }

    void ClearRows()
    {
        ready_ = false;
        rows_.clear();
        poseRevision_ = 1;
    }

public:
    void Clear()
    {
        ClearRows();
        staticModel_ = nullptr;
    }

    bool ReuseStaticQuery(const void* model, const float* center, const float* extent,
        unsigned mode, std::size_t currentCount)
    {
        const auto pose = Encode(center, extent);
        if (model && model == staticModel_ && pose == staticQuery_ && mode == staticMode_ && currentCount == staticCount_)
            return true;
        staticModel_ = model;
        staticQuery_ = pose;
        staticMode_ = mode;
        return false;
    }

    void SetStaticQueryCount(std::size_t count) { staticCount_ = count; }

    bool Select(const void* triangles, const void* vertices, std::size_t count,
        bool newQuery, const float* center, const float* extent, unsigned floatingPointMode)
    {
        constexpr std::size_t maxFaces = 4096;
        if (count > maxFaces)
        {
            ClearRows();
            return false;
        }

        if (!ready_ || newQuery || triangles != triangles_ || vertices != vertices_ || count != rows_.size())
        {
            ClearRows();
            try
            {
                rows_.resize(count);
            }
            catch (const std::bad_alloc&)
            {
                return false;
            }
            triangles_ = triangles;
            vertices_ = vertices;
            ready_ = true;
            pose_ = Encode(center, extent);
            mode_ = floatingPointMode;
            return true;
        }

        const auto pose = Encode(center, extent);
        if (pose != pose_ || mode_ != floatingPointMode)
        {
            ++poseRevision_;
            pose_ = pose;
            mode_ = floatingPointMode;
        }
        return true;
    }

    Face& At(std::size_t index)
    {
        auto& row = rows_[index];
        if (row.poseRevision != poseRevision_)
        {
            row.face.ResetPose();
            row.poseRevision = poseRevision_;
        }
        return row.face;
    }
};
}
