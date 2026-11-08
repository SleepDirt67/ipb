#pragma once

#include "ActivationCollisionPlan.h"
#include "tri-colliderknoopc/dTriColliderMath.h"
#include <cstdlib>
#ifdef _M_X64
#include <xmmintrin.h>
#endif

namespace SpawnCollision
{
struct Face
{
    Point vertices[3];
    Triangle triangle;
    bool loaded = false;
    signed char broad = -1;
    signed char exact = -1;
    bool derived = false;

    void ResetPose()
    {
        broad = exact = -1;
        derived = false;
    }

    const Point* Vertices(const CDB::TRI& source, const Fvector* meshVertices)
    {
        if (!loaded)
        {
            for (int i = 0; i < 3; ++i)
                vertices[i] = Point(reinterpret_cast<const float*>(&meshVertices[source.verts[i]]));
            loaded = true;
        }
        return vertices;
    }

    bool Broad(const dReal* center, const Fvector& extent)
    {
        if (broad < 0)
            broad = aabb_tri_aabb(Point(center), Point(reinterpret_cast<const float*>(&extent)), vertices);
        return broad != 0;
    }

    bool Exact(const dReal* center, const Fvector& extent)
    {
        if (exact < 0)
            exact = __aabb_tri(Point(center), Point(reinterpret_cast<const float*>(&extent)), vertices);
        return exact != 0;
    }

    void TriangleAt(CDB::TRI* source, const dReal* center, Triangle& out)
    {
        if (!derived)
        {
            CalculateTri(source, center, triangle, vertices);
            derived = true;
        }

        // Only the fields populated by CalculateTri. The caller still owns
        // depth and the live contact decisions made after this point.
        dVectorSet(out.side0, triangle.side0);
        dVectorSet(out.side1, triangle.side1);
        dVectorSet(out.norm, triangle.norm);
        out.dist = triangle.dist;
        out.pos = triangle.pos;
        out.T = triangle.T;
    }
};

class Scope
{
    static inline thread_local Scope* current_ = nullptr;
    static inline thread_local Plan<Face> scratch_;

    Scope* parent_;
    dBodyID body_;
    Plan<Face> plan_;

public:
    explicit Scope(dBodyID body) : parent_(current_), body_(body)
    {
        current_ = this;
    }
    ~Scope()
    {
        if (!parent_)
            scratch_.Clear();
        current_ = parent_;
    }
    Scope(const Scope&) = delete;
    Scope& operator=(const Scope&) = delete;

    static Plan<Face>* For(dBodyID body)
    {
#if defined(_M_X64) && !defined(DEBUG)
        static const bool enabled = [] {
            const char* setting = std::getenv("IXRAY_SPAWN_CONTACT_PLAN");
            return !setting || xr_strcmp(setting, "0") != 0;
        }();
        if (enabled && current_ && body && current_->body_ == body)
            return current_->parent_ ? &current_->plan_ : &scratch_;
#endif
        return nullptr;
    }

    static unsigned FloatingPointMode()
    {
#ifdef _M_X64
        return _mm_getcsr() & 0xffc0u;
#else
        return 0;
#endif
    }
};
}
