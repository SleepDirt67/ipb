#include "src/xrPhysics/stdafx.h"
#include "src/xrPhysics/ode_include.h"
#include "src/xrPhysics/SpawnPreparationQueue.h"
#include "src/xrPhysics/SpawnPreparedGeometry.h"

#include <bit>
#include <chrono>
#include <cstdio>
#include <future>

namespace
{
using namespace SpawnPreparation;
using namespace Geometry;
using namespace std::chrono_literals;

void Require(bool condition, const char* label)
{
    if (!condition)
    {
        std::fprintf(stderr, "FAIL: %s\n", label);
        std::abort();
    }
}

template<class Try>
auto WaitFor(Try attempt, const char* label)
{
    const auto end = std::chrono::steady_clock::now() + 3s;
    do
    {
        if (auto result = attempt())
            return result;
        std::this_thread::yield();
    } while (std::chrono::steady_clock::now() < end);
    Require(false, label);
    std::abort();
}

void CheckQueue()
{
    std::promise<void> entered;
    std::promise<void> released;
    auto release = released.get_future().share();
    const auto prepare = [&](const unsigned& value) -> std::optional<unsigned> {
        if (value == 11)
        {
            entered.set_value();
            release.wait();
        }
        return value;
    };
    Queue<unsigned, unsigned, decltype(prepare), 2> queue(prepare);
    WaitFor([&] { return queue.Submit(1, 11); }, "submit blocked worker");
    Require(entered.get_future().wait_for(3s) == std::future_status::ready, "worker entered");
    WaitFor([&] { return queue.Submit(2, 22); }, "queue behind running job");
    Require(!queue.Submit(3, 33), "overflow leaves fallback available");
    Require(!queue.Take(1) && !queue.Take(2), "both running and pending miss without waiting");
    queue.Retire(1);
    queue.Retire(2);
    WaitFor([&] { return queue.Submit(2, 222); }, "reuse ID after pending cancellation");
    released.set_value();
    Require(*WaitFor([&] { return queue.Take(2); }, "receive new ID result") == 222,
        "retired input cannot publish for reused ID");
    Require(!queue.Take(1) && !queue.Take(2), "at most one take and no retired result");
}

void CheckLookahead()
{
    std::promise<void> entered;
    std::promise<void> released;
    auto release = released.get_future().share();
    std::array<unsigned, 3> execution{};
    unsigned executed = 0;
    const auto prepare = [&](const unsigned& value) -> std::optional<unsigned> {
        if (value == 11)
        {
            entered.set_value();
            release.wait();
        }
        execution[executed++] = value;
        return value;
    };
    Queue<unsigned, unsigned, decltype(prepare), 3> queue(prepare);
    WaitFor([&] { return queue.Submit(1, 11, true); }, "lookahead starts");
    Require(entered.get_future().wait_for(3s) == std::future_status::ready, "lookahead worker entered");
    WaitFor([&] { return queue.Submit(2, 22, true); }, "pending lookahead");
    WaitFor([&] { return queue.Submit(3, 33, true); }, "second pending lookahead");
    WaitFor([&] { return queue.Submit(1, 111); }, "new announced pose retires running lookahead");
    released.set_value();
    Require(*WaitFor([&] { return queue.Take(1); }, "announced pose available") == 111,
        "superseded running pose never publishes");
    Require(*WaitFor([&] { return queue.Take(3); }, "unrelated lookahead still available") == 33,
        "newest unrelated lookahead survived capacity limit");
    Require(!queue.Take(2) && execution == std::array<unsigned, 3>{11, 111, 33},
        "announced work precedes and displaces lookahead");
}

bool Same(float a, float b)
{
    return std::bit_cast<unsigned>(a) == std::bit_cast<unsigned>(b);
}

void CheckGeometry()
{
    Fvector vertices[]{{-2, 0, -2}, {2, 0, -2}, {-2, 0, 2}, {2, 0, 2}};
    CDB::TRI triangles[2]{};
    triangles[0].verts[0] = 0;
    triangles[0].verts[1] = 2;
    triangles[0].verts[2] = 1;
    triangles[1].verts[0] = 2;
    triangles[1].verts[1] = 3;
    triangles[1].verts[2] = 1;
    CDB::MODEL model;
    model.build(vertices, 4, triangles, 2);

    Inputs input{&model, {Fvector{0, -.1f, 0}, Fvector{7, 1, 7}}, {.4f, .6f, .4f}, 1.3f, 2, _mm_getcsr()};
    input.binder = std::make_shared<const int>(42);
    using Result = std::unique_ptr<ActivationResult>;
    Queue<Inputs, Result, decltype(&PrepareGeometry)> queue(&PrepareGeometry);
    WaitFor([&] { return queue.Submit(42, input); }, "submit real CDB work");
    auto prepared = WaitFor([&] { return queue.Take(42); }, "take real CDB work");
    Require((*prepared)->binder == input.binder, "physics and binder share the admitted generation");
    auto extent = input.halfSize;
    extent.add(10.f * EPS_L);
    auto queryExtent = extent;
    queryExtent.mul(input.expansion);
    unsigned comparisons = 0;
    CDB::COLLIDER collider;
    collider.box_options(0);
    for (const auto& center : {input.centers[0], input.centers[1]})
    {
        const auto mode = SpawnCollision::Scope::FloatingPointMode();
        auto* pose = Match(prepared->get(), &model, &center.x, extent, queryExtent, mode);
        Require(pose, "exact prepared geometry matches");
        Require(!Match(prepared->get(), &model, &center.x, extent, queryExtent, mode ^ 0x8000),
            "FP mode change forces the original query");
        Require(!Match(prepared->get(), nullptr, &center.x, extent, queryExtent, mode),
            "changed world forces the original query");
        Fvector moved = center;
        moved.x += .03f;
        Require(!Match(prepared->get(), &model, &moved.x, extent, queryExtent, mode),
            "changed pose forces the original query");

        collider.box_query(&model, center, queryExtent);
        const int count = collider.r_count();
        Require(pose->ids.size() == static_cast<std::size_t>(count), "CDB result length");
        for (int i = 0; i < count; ++i)
        {
            const int id = collider.r_begin()[i].id;
            Require(pose->ids[i] == id, "CDB order");
            auto* tri = model.get_tris() + id;
            Point points[3];
            for (int v = 0; v < 3; ++v)
                points[v] = Point(&model.get_verts()[tri->verts[v]].x);
            auto& face = pose->faces[i];
            const bool broad = aabb_tri_aabb(Point(&center.x), Point(&extent.x), points);
            Require(face.Broad(&center.x, extent) == broad, "detached broad phase");
            if (!broad)
                continue;
            Triangle baseline, detached;
            CalculateTri(tri, &center.x, baseline, points);
            face.TriangleAt(tri, &center.x, detached);
            Require(Same(detached.pos, baseline.pos) && Same(detached.dist, baseline.dist),
                "detached plane and signed distance");
            for (int j = 0; j < 3; ++j)
                Require(Same(detached.norm[j], baseline.norm[j]), "detached normal");
            Require(face.Exact(&center.x, extent) == __aabb_tri(Point(&center.x), Point(&extent.x), points),
                "detached exact intersection");
            ++comparisons;
        }
    }
    Require(comparisons > 0, "CDB fixture exercised real overlapping triangles");
}
}

int main()
{
    Core._initialize("spawn-admission-fixture", nullptr, FALSE, nullptr);
    CheckQueue();
    CheckLookahead();
    CheckGeometry();
    Core._destroy();
    std::puts("PASS: detached CDB differential, deadline miss, cancellation, ID reuse and queue ownership");
}
