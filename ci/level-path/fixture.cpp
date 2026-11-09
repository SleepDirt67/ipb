#include "LevelSearchWorkspace.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory_resource>
#include <random>
#include <unordered_map>

using u32 = std::uint32_t;
using s32 = std::int32_t;
template<class T> using xr_vector = std::vector<T>;
using std::fabs;

struct ILevelGraph
{
    static constexpr u32 invalid = ~0u;
    struct CVertex {
        std::array<u32, 4> links;
        float x, z;
        u32 link(unsigned edge) const { return links[edge]; }
    };
    struct Header { float cell_size() const { return 0.7f; } };
    std::vector<CVertex> vertices;
    std::vector<unsigned char> passable;
    CVertex* m_nodes;

    ILevelGraph(u32 width, u32 height) : vertices(width * height),
        passable(width * height, 1), m_nodes(vertices.data())
    {
        for (u32 z = 0; z < height; ++z)
            for (u32 x = 0; x < width; ++x)
            {
                const u32 id = z * width + x;
                vertices[id] = {{x ? id - 1 : invalid, x + 1 < width ? id + 1 : invalid,
                    z ? id - width : invalid, z + 1 < height ? id + width : invalid},
                    float(x) * 0.7f, float(z) * 0.7f};
            }
    }

    Header header() const { return {}; }
    CVertex* vertex(u32 id) const { return &m_nodes[id]; }
    bool is_accessible(u32 id) const { return id < vertices.size() && passable[id]; }
    void unpack_xz(CVertex* v, float& x, float& z) const { x = v->x; z = v->z; }
    bool Search(u32, u32, xr_vector<u32>&, float, u32, u32) const;
    bool Stock(u32, u32, xr_vector<u32>&, float, u32, u32) const;
};
#include "Stock.inc"
#include "Candidate.inc"

static void Compare(ILevelGraph& graph, u32 start, u32 dest, float range, u32 steps, u32 visits)
{
    xr_vector<u32> a{4, 8}, b{2, 9};
    const bool before = graph.Stock(start, dest, a, range, steps, visits);
    const bool after = graph.Search(start, dest, b, range, steps, visits);
    if (before != after || a != b)
    {
        std::fprintf(stderr, "Route diverged for %u -> %u, steps %u, visits %u\n", start, dest, steps, visits);
        std::abort();
    }
}

int main()
{
    using namespace std::chrono;
    std::mt19937 random(42);
    ILevelGraph small(64, 61), next(62, 63);
    for (unsigned i = 0; i < 2500; ++i)
    {
        auto& graph = i % 37 == 0 ? next : small;
        const auto size = static_cast<u32>(graph.vertices.size());
        const u32 start = random() % (size + 1), dest = random() % (size + 1);
        graph.passable[random() % size] ^= 1;
        const float range = i % 4 ? 10000.f : float(random() % 90);
        Compare(graph, start, dest, range, i % 5 ? 10000 : random() % 80,
            i % 7 ? 4000 : random() % 55);
    }
    Compare(small, ILevelGraph::invalid, ILevelGraph::invalid, 0, 0, 0);
    ILevelGraph large(900, 650);
    // A blocked wall forces exploration of a substantial connected component.
    for (u32 z = 0; z < 650; ++z)
        large.passable[z * 900 + 610] = 0;
    Compare(large, 0, 584999, 10000.f, ~0u, ~0u);
    ILevelGraph directed(180, 160);
    const u32 gap = 150 * 180 + 114;
    for (u32 z = 0; z < 160; ++z)
        directed.passable[z * 180 + 114] = 0;
    directed.passable[gap] = 1;
    directed.vertices[gap + 1].links[0] = ILevelGraph::invalid;
    Compare(directed, 0, 179, 10000.f, ~0u, ~0u);
    Compare(directed, 179, 0, 10000.f, ~0u, ~0u);
    Compare(directed, 0, 179, 40.f, ~0u, ~0u);
    Compare(directed, 0, 179, 10000.f, 10000u, 20000u);
    std::vector<double> stock, candidate;
    directed.passable[gap] = 0;
    for (unsigned i = 0; i < 9; ++i)
    {
        xr_vector<u32> path;
        const auto begin = steady_clock::now();
        if (directed.Stock(i, 179 + i * 180, path, 10000.f, ~0u, ~0u)) std::abort();
        const auto between = steady_clock::now();
        if (directed.Search(i, 179 + i * 180, path, 10000.f, ~0u, ~0u)) std::abort();
        stock.push_back(duration<double, std::milli>(between - begin).count());
        candidate.push_back(duration<double, std::milli>(steady_clock::now() - between).count());
    }
    std::sort(stock.begin(), stock.end());
    std::sort(candidate.begin(), candidate.end());
    std::printf("28800-vertex blocked graph median %.3f -> %.3f ms\n", stock[4], candidate[4]);
    stock.clear();
    candidate.clear();
    for (unsigned i = 0; i < 13; ++i)
    {
        const u32 from = i * 900 + 34, to = 580480 + i;
        xr_vector<u32> routes[2];
        for (unsigned j = 0; j < 2; ++j)
        {
            const auto variant = (i + j) % 2;
            const auto begin = steady_clock::now();
            const bool result = variant ? large.Search(from, to, routes[1], 10000.f, ~0u, ~0u)
                                        : large.Stock(from, to, routes[0], 10000.f, ~0u, ~0u);
            auto& samples = variant ? candidate : stock;
            samples.push_back(duration<double, std::milli>(steady_clock::now() - begin).count());
            if (result) std::abort();
        }
        if (routes[0] != routes[1]) std::abort();
    }
    std::sort(stock.begin(), stock.end());
    std::sort(candidate.begin(), candidate.end());
    std::printf("2506 exact route comparisons; unreachable routes median %.3f -> %.3f ms, max %.3f -> %.3f ms\n",
        stock[6], candidate[6], stock.back(), candidate.back());
}
