#include <algorithm>
#include <array>
#include <cctype>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <map>
#include <memory>
#include <memory_resource>
#include <queue>
#include <random>
#include <string>
#include <unordered_map>
#include <vector>

using u32 = unsigned;
using s32 = int;
using LPCSTR = const char*;
using string256 = char[256];
template <class T> using xr_vector = std::vector<T>;

struct ILevelGraph {
    struct CVertex {
        std::array<u32, 4> links;
        float x, z;
        bool accessible = true;
        u32 link(s32 direction) const { return links[direction]; }
    };
    struct Header {
        float cell_size() const { return 0.7f; }
    };
    mutable std::vector<CVertex> grid;
    Header header() const { return {}; }
    CVertex* vertex(u32 id) const { return &grid.at(id); }
    bool is_accessible(u32 id) const { return id < grid.size() && grid[id].accessible; }
    static void unpack_xz(const CVertex* node, float& x, float& z) { x = node->x; z = node->z; }
    bool Search(u32, u32, xr_vector<u32>&, float, u32, u32) const;
    bool SearchOld(u32, u32, xr_vector<u32>&, float, u32, u32) const;
};

static void xr_strcpy(string256& out, LPCSTR in) {
    std::memcpy(out, in, std::strlen(in) + 1);
}
#ifndef _MSC_VER
static void _strlwr(char* value) {
    for (; *value; ++value)
        *value = static_cast<char>(std::tolower(static_cast<unsigned char>(*value)));
}
#endif
static char* strext(char* name) { return std::strrchr(name, '.'); }
static int xr_strcmp(LPCSTR a, LPCSTR b) { return std::strcmp(a, b); }

struct SoundName : std::string {
    const char* operator*() const { return c_str(); }
};
struct CSoundRender_Source {
    SoundName fname;
    void unload() {}
    void load(LPCSTR id) {
        string256 normalized;
        xr_strcpy(normalized, id);
        _strlwr(normalized);
        if (auto ext = strext(normalized))
            *ext = 0;
        fname.assign(normalized);
    }
};
struct CSoundRender_Core {
    struct Emitter { void stop(bool) {} };
    std::vector<Emitter*> s_emitters;
    std::vector<CSoundRender_Source*> s_sources;
    std::map<std::string, CSoundRender_Source*, std::less<>> s_sources_by_name;
    CSoundRender_Source* i_create_source(LPCSTR);
    CSoundRender_Source* i_create_sourceOld(LPCSTR);
    void refresh_sources();
    void refresh_sourcesOld();
    void clear() {
        s_sources_by_name.clear();
        for (auto* source : s_sources)
            delete source;
        s_sources.clear();
    }
    ~CSoundRender_Core() { clear(); }
};

constexpr auto FALSE = false;
#include "functions.inc"

ILevelGraph make_grid(u32 width, u32 height) {
    ILevelGraph graph;
    const u32 invalid = width * height;
    for (u32 z = 0; z < height; ++z) {
        for (u32 x = 0; x < width; ++x) {
            const u32 v = z * width + x;
            graph.grid.push_back({{x ? v - 1 : invalid, x + 1 < width ? v + 1 : invalid,
                z ? v - width : invalid, z + 1 < height ? v + width : invalid}, float(x), float(z)});
        }
    }
    return graph;
}

int main() {
    constexpr u32 unlimited = 0xffffffff;
    std::mt19937 random(3846317);
    std::vector<u32> old_path, new_path;
    constexpr unsigned graph_cases = 32000;
    for (unsigned n = 0; n < graph_cases; ++n) {
        auto graph = make_grid(6 + random() % 21, 6 + random() % 21);
        for (auto& node : graph.grid) {
            node.accessible = random() % 7 != 0;
            std::shuffle(node.links.begin(), node.links.end(), random);
        }
        const u32 start = random() % graph.grid.size();
        const u32 finish = n % 19 == 0 ? start : random() % graph.grid.size();
        const float range = n % 4 ? 1e8f : float(random() % 30);
        const u32 iterations = n % 3 ? unlimited : random() % 60;
        const u32 visited = n % 3 == 1 ? unlimited : random() % 64;
        const bool original = graph.SearchOld(start, finish, old_path, range, iterations, visited);
        const bool candidate = graph.Search(start, finish, new_path, range, iterations, visited);
        if (original != candidate || old_path != new_path)
            return 1;
    }

    CSoundRender_Core original, candidate;
    constexpr unsigned sound_cases = 12000;
    for (unsigned n = 0; n < sound_cases; ++n) {
        if (n % 3000 == 0) {
            original.clear();
            candidate.clear();
        }
        if (n % 1200 == 601) {
            original.refresh_sourcesOld();
            candidate.refresh_sources();
        }
        std::string name = (n % 2 == 0 ? "AI\\Voice" : "ai\\voice") + std::to_string(random() % 970);
        name += std::array{"", ".OGG", ".tail.ogg", ".tail", ".wav", ".left.tail.ogg", ".left.tail"}[n % 7];
        const auto* first = original.i_create_sourceOld(name.c_str());
        const auto* second = candidate.i_create_source(name.c_str());
        if (first->fname != second->fname || original.s_sources.size() != candidate.s_sources.size())
            return 2;
        if (std::find(original.s_sources.begin(), original.s_sources.end(), first) - original.s_sources.begin() !=
            std::find(candidate.s_sources.begin(), candidate.s_sources.end(), second) - candidate.s_sources.begin())
            return 3;
    }

    using Clock = std::chrono::steady_clock;
    auto graph = make_grid(190, 190);
    // A disconnected target forces a large search without relying on a changed iteration budget.
    graph.grid[graph.grid.size() - 2].accessible = false;
    graph.grid[graph.grid.size() - 191].accessible = false;
    const auto bench_graph = [&](auto search) {
        const auto begin = Clock::now();
        for (unsigned i = 0; i < 8; ++i)
            if ((graph.*search)(i, static_cast<u32>(graph.grid.size() - 1), new_path, 1e8f, unlimited, unlimited))
                std::terminate();
        return std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
    };
    const auto bench_sound = [](auto lookup) {
        CSoundRender_Core manager;
        std::vector<std::string> names;
        for (unsigned i = 0; i < 5000; ++i) {
            names.push_back("characters\\audio_" + std::to_string(i) + ".ogg");
            (manager.*lookup)(names.back().c_str());
        }
        const auto begin = Clock::now();
        for (unsigned repetition = 0; repetition < 8; ++repetition)
            for (const auto& name : names)
                (manager.*lookup)(name.c_str());
        return std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
    };

    const auto graph_old = bench_graph(&ILevelGraph::SearchOld);
    const auto graph_new = bench_graph(&ILevelGraph::Search);
    const auto sound_old = bench_sound(&CSoundRender_Core::i_create_sourceOld);
    const auto sound_new = bench_sound(&CSoundRender_Core::i_create_source);
    std::cout << "Graph exact path and result: " << graph_cases << " cases\n"
              << "Sound source identity and order: " << sound_cases << " requests\n"
              << "Graph old/new milliseconds: " << graph_old << " / " << graph_new << '\n'
              << "Sound old/new milliseconds: " << sound_old << " / " << sound_new << '\n';
}
