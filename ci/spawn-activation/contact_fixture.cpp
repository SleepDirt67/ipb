#include "src/xrPhysics/stdafx.h"
#include "src/xrPhysics/ode_include.h"
#include "src/xrPhysics/SpawnActivationContacts.h"

#include <array>
#include <cstdio>
#include <random>

namespace
{
void Require(bool condition, const char* label)
{
    if (!condition)
    {
        std::fprintf(stderr, "Failed: %s\n", label);
        std::abort();
    }
}

bool SameFloat(float a, float b)
{
    return std::bit_cast<std::uint32_t>(a) == std::bit_cast<std::uint32_t>(b);
}

void CheckTriangle(const Triangle& a, const Triangle& b)
{
    Require(a.T == b.T && SameFloat(a.dist, b.dist) && SameFloat(a.pos, b.pos), "plane and distance");
    for (int axis = 0; axis < 3; ++axis)
    {
        Require(SameFloat(a.norm[axis], b.norm[axis]), "normal");
        Require(SameFloat(a.side0[axis], b.side0[axis]), "first edge");
        Require(SameFloat(a.side1[axis], b.side1[axis]), "second edge");
    }
}

struct Work
{
    static constexpr unsigned size = 144;
    std::array<CDB::TRI, size> faces{};
    std::array<Fvector, size * 3> vertices{};

    Work()
    {
        std::mt19937 rng(20371001);
        std::uniform_real_distribution<float> value(-1.6f, 1.6f);
        for (unsigned i = 0; i < size; ++i)
            for (unsigned j = 0; j < 3; ++j)
            {
                const auto index = i * 3 + j;
                faces[i].verts[j] = index;
                vertices[index].set(value(rng), value(rng), value(rng));
            }
    }
};
}

int main()
{
    Work mesh;
    SpawnCollision::Plan<SpawnCollision::Face> plan;
    unsigned checks = 0;
    unsigned exactTests = 0;
    const auto mode = SpawnCollision::Scope::FloatingPointMode();
    for (int repeat = 0; repeat < 250; ++repeat)
    {
        const bool newQuery = repeat % 37 == 0;
        const float movement = static_cast<float>(repeat / 3) * .013f;
        const Fvector center{movement, -.07f, .02f};
        const Fvector extent{.42f, .61f, .47f};
        const float* p = reinterpret_cast<const float*>(&center);
        const float* e = reinterpret_cast<const float*>(&extent);
        Require(plan.Select(mesh.faces.data(), mesh.vertices.data(), Work::size, newQuery, p, e, mode),
            "usable CDB result");
        for (unsigned index = 0; index < Work::size; ++index)
        {
            auto* triangle = &mesh.faces[index];
            Point vertices[3];
            for (int i = 0; i < 3; ++i)
                vertices[i] = Point(reinterpret_cast<const float*>(&mesh.vertices[triangle->verts[i]]));
            auto& face = plan.At(index);
            face.Vertices(*triangle, mesh.vertices.data());
            const bool broad = aabb_tri_aabb(Point(p), Point(e), vertices);
            Require(face.Broad(p, extent) == broad, "coarse intersection");
            ++checks;
            if (!broad)
                continue;
            Triangle a, b;
            CalculateTri(triangle, p, a, vertices);
            face.TriangleAt(triangle, p, b);
            CheckTriangle(a, b);
            Require(face.Exact(p, extent) == __aabb_tri(Point(p), Point(e), vertices), "exact intersection");
            ++exactTests;
        }
    }

    const float zero[3]{};
    const float moved[3]{.01f, 0, 0};
    Require(!plan.ReuseStaticQuery(mesh.faces.data(), zero, zero, mode, 0), "initial BVH query");
    plan.SetStaticQueryCount(15);
    Require(plan.ReuseStaticQuery(mesh.faces.data(), zero, zero, mode, 15), "repeat identical BVH query");
    Require(!plan.ReuseStaticQuery(mesh.faces.data(), zero, zero, mode, 0), "cleared triangles invalidate BVH query");
    Require(!plan.ReuseStaticQuery(mesh.faces.data(), moved, zero, mode, 0), "pose invalidates BVH query");
    Require(!plan.ReuseStaticQuery(mesh.faces.data(), moved, zero, mode ^ 0x8000, 0), "FP mode invalidates BVH query");
    Require(!plan.ReuseStaticQuery(mesh.vertices.data(), moved, zero, mode ^ 0x8000, 0), "mesh invalidates BVH query");
    plan.Clear();
    Require(!plan.ReuseStaticQuery(mesh.vertices.data(), moved, zero, mode ^ 0x8000, 0), "new activation has no BVH query");
    Require(!plan.Select(mesh.faces.data(), mesh.vertices.data(), 4097, false, zero, zero, mode),
        "large static query fallback");
    std::printf("PASS: %u coarse and %u exact native collision checks; moving and stationary poses\n", checks, exactTests);
}
