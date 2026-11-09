#include "rows.h"
#include <algorithm>
#include <array>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <random>
#include <vector>
#ifdef _MSC_VER
#include <malloc.h>
#define alloca _alloca
#else
#include <alloca.h>
#endif
using dReal = float;
using dRealPtr = const dReal*;
using dRealMutablePtr = dReal*;
struct dxBody { float invMass; };
struct dxQuickStepParameters { int num_iterations; float w; };
static std::mt19937 rng(1);
using std::isnan;
#define WARM_STARTING 0
#define RANDOMLY_REORDER_CONSTRAINTS 1
#define REAL(x) float(x)
#define dIASSERT(x) assert(x)
#define dFabs std::fabs
#define dInfinity (std::numeric_limits<float>::infinity())
#define dRealAllocaArray(name,n) auto* name = static_cast<dReal*>(alloca((n)*sizeof(dReal)))
static void dSetZero(float* ptr,int count) { std::fill_n(ptr,count,0.f); }
static void dMULTIPLY0_331(float* out,const float* matrix,const float* v)
{
    for (int i = 0; i < 3; ++i)
        out[i] = matrix[4*i]*v[0] + matrix[4*i+1]*v[1] + matrix[4*i+2]*v[2];
}
#include "solvers.inc"

struct Fixture
{
    int m, nb;
    std::vector<float> j, inverse, lambda, force, rhs, lo, hi, cfm;
    std::vector<int> jb, findex;

    Fixture(int count,int bodies) : m(count), nb(bodies), j(m*12), inverse(nb*12),
        lambda(m), force(nb*6), rhs(m), lo(m), hi(m), cfm(m), jb(m*2), findex(m)
    {
        auto random = std::mt19937(m + nb);
        auto sample = [&] { return (static_cast<int>(random() % 2001)-1000) / 1000.f; };
        for (auto& value:j) value = sample();
        for (int i=0;i<nb;++i) inverse[12*i]=inverse[12*i+5]=inverse[12*i+10]=1.f;
        for(int i=0;i<m;++i)
        {
            lambda[i]=sample()*.02f;
            rhs[i]=sample()*.5f;
            lo[i]=-3.f;
            hi[i]=3.f;
            cfm[i]=.001f;
            jb[i*2]=static_cast<int>(random()%nb);
            jb[i*2+1]=i%3 ? -1 : (jb[i*2]+1)%nb;
            findex[i]=i%3==0 ? -1 : i/3*3;
        }
    }

    void solve(unsigned variant, unsigned seed)
    {
        dxBody body{1};
        std::vector<dxBody*> ptr(nb, &body);
        dxQuickStepParameters cfg{20,1.3f};
        rng.seed(seed);
        auto solver=std::array{SOR_LCP, SOR_Vector, SOR_Dot}[variant];
        solver(m,nb,j.data(),jb.data(),ptr.data(),inverse.data(),lambda.data(),force.data(),
            rhs.data(),lo.data(),hi.data(),cfm.data(),findex.data(),&cfg);
    }

    bool matches(const Fixture& other) const
    {
        auto bits = [](const auto& a, const auto& b) {
            return std::memcmp(a.data(),b.data(),a.size()*sizeof(float))==0;
        };
        return bits(lambda,other.lambda)&&bits(force,other.force)&&bits(lo,other.lo)&&bits(hi,other.hi);
    }
};

int main()
{
    int compared = 0;
    unsigned different[3]{};
    double totals[3]{};
    for (int m : {6,12,24,72,240})
        for (int i = 0; i < 2000; ++i)
        {
            const Fixture sample(m, 2 + i%11);
            Fixture fixtures[3]{sample,sample,sample};
            for (unsigned v = 0; v < 3; ++v)
            {
                const unsigned variant = (i + v)%3;
                auto start = std::chrono::steady_clock::now();
                fixtures[variant].solve(variant, i);
                totals[variant] += std::chrono::duration<double,std::milli>(
                    std::chrono::steady_clock::now() - start).count();
            }
            ++compared;
            for (unsigned v = 1; v < 3; ++v)
                different[v] += !fixtures[0].matches(fixtures[v]);
        }
    std::printf("SOR cases %d; force-only differences %u, force-and-dot differences %u; total %.3f / %.3f / %.3f ms\n",
        compared,different[1],different[2],totals[0],totals[1],totals[2]);
    return different[1] != 0;
}
