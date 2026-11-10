#include <algorithm>
#include <cctype>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

using BOOL = bool;
constexpr BOOL TRUE = true, FALSE = false;
using string_path = char[256];
template<class T> using xr_vector = std::vector<T>;
template<class T> using xr_unique_ptr = std::unique_ptr<T>;
enum { MT_NORMAL, MT_SKELETON_ANIM, MT_SKELETON_GEOMDEF_PM, MT_SKELETON_GEOMDEF_ST, MT_PROGRESSIVE, MT_LOD, MT_PARTICLE_EFFECT };
#define VERIFY(value) do { if (!(value)) { std::fprintf(stderr, "%d: %s\n", __LINE__, #value); std::abort(); } } while (false)
struct IReader {};
struct shared_str {
    std::string text;
    shared_str(const char* value) : text(value) {}
    const char* operator*() const { return text.c_str(); }
};
struct dxRender_Visual {
    unsigned Type = MT_NORMAL;
    int origin = 0;
    static inline unsigned loads = 0, spawns = 0, copies = 0, releases = 0;
    virtual ~dxRender_Visual() = default;
    void Copy(dxRender_Visual* reference) { origin = reference->origin; ++copies; }
    void Spawn() { ++spawns; }
    void Release() { ++releases; }
};
struct CKinematicsAnimated : dxRender_Visual {
    dxRender_Visual* m_lod = nullptr;
    xr_vector<dxRender_Visual*> children;
};
static auto xr_strlen(const char* s) { return std::strlen(s); }
static void xr_strcpy(char* dst, const char* src) { std::strcpy(dst, src); }
#ifndef _WIN32
static void _strlwr(char* text) {
    for (; *text; ++text)
        *text = static_cast<char>(std::tolower(static_cast<unsigned char>(*text)));
}
#endif
static char* strext(char* name) { return std::strrchr(name, '.'); }
template<class T> static void xr_delete(T*& p) { delete p; p = nullptr; }

class CModelPool {
public:
    struct PreparedReference {
        dxRender_Visual* reference = nullptr;
        bool registered = false;
        xr_vector<xr_unique_ptr<dxRender_Visual>> clones;
    };
    struct ModelDef { dxRender_Visual* model; unsigned refs; };
    xr_vector<ModelDef> Models;
    dxRender_Visual sharedLeaf;
    dxRender_Visual particleLeaf;
    std::map<std::string, PreparedReference, std::less<>> preparedReferences;
    std::map<std::string, dxRender_Visual*, std::less<>> live;
    std::multimap<std::string, dxRender_Visual*> Pool;
    using POOL_IT = decltype(Pool)::iterator;
    std::map<dxRender_Visual*, std::string> Registry;
    BOOL bAllowChildrenDuplicate = TRUE;
    void Instance_Register(const char* name, dxRender_Visual* visual) {
        live.emplace(name, visual);
        Models.push_back({visual, 0});
    }
    dxRender_Visual* Instance_Find(const char* name) const {
        const auto found = live.find(name);
        return found == live.end() ? nullptr : found->second;
    }
    dxRender_Visual* Instance_Create(unsigned type) {
        dxRender_Visual* visual = type == MT_SKELETON_ANIM ? new CKinematicsAnimated() : new dxRender_Visual();
        visual->Type = type;
        return visual;
    }
    dxRender_Visual* Instance_Load(const char* name, IReader* data, BOOL registerReference) {
        VERIFY(!bAllowChildrenDuplicate);
        if (std::strcmp(name, "absent") == 0) return nullptr;
        ++dxRender_Visual::loads;
        auto* visual = static_cast<CKinematicsAnimated*>(Instance_Create(MT_SKELETON_ANIM));
        visual->origin = data ? 2 : 1;
        if (std::strcmp(name, "particle") == 0) visual->children.push_back(&particleLeaf);
        if (std::strcmp(name, "registered-child") == 0) visual->children.push_back(&sharedLeaf);
        if (registerReference) Instance_Register(name, visual);
        return visual;
    }
    dxRender_Visual* Instance_Load(const char* name, BOOL reg) { return Instance_Load(name, nullptr, reg); }
    dxRender_Visual* Instance_Duplicate(dxRender_Visual* base) {
        auto* visual = Instance_Create(base->Type);
        visual->Copy(base);
        visual->Spawn();
        IncrementReference(base);
        return visual;
    }
    void IncrementReference(dxRender_Visual*);
    dxRender_Visual* LoadReference(const char*, IReader*, BOOL);
    bool PrepareReference(const char*, unsigned);
    void ClearPreparedReferences();
    void DiscardPreparedClones(dxRender_Visual*, const shared_str&);
    dxRender_Visual* Create(const char*, IReader* = nullptr);
};

#include "model-methods.inc"

int main() {
    CModelPool pool;
    pool.particleLeaf.Type = MT_PARTICLE_EFFECT;
    pool.Instance_Register("leaf", &pool.sharedLeaf);
    VERIFY(pool.PrepareReference("npc", 3) && !pool.PrepareReference("npc", 3));
    VERIFY(!pool.Instance_Find("npc") && dxRender_Visual::spawns == 0 && pool.Registry.empty());
    VERIFY(dxRender_Visual::copies == 3 && pool.preparedReferences.at("npc").clones.size() == 3);
    auto* first = pool.Create("NPC.OGF");
    VERIFY(first->origin == 1 && dxRender_Visual::spawns == 1 && dxRender_Visual::loads == 1);
    VERIFY(pool.Models.back().refs == 1 && pool.Registry.count(first) == 1);
    pool.Pool.emplace("npc", first);
    VERIFY(pool.Create("npc") == first && dxRender_Visual::spawns == 2);
    VERIFY(pool.preparedReferences.at("npc").clones.size() == 2);
    auto* second = pool.Create("npc");
    VERIFY(second != first && dxRender_Visual::copies == 3 && dxRender_Visual::spawns == 3);
    pool.DiscardPreparedClones(pool.Instance_Find("npc"), shared_str("npc"));
    VERIFY(!pool.preparedReferences.count("npc"));
    VERIFY(pool.PrepareReference("shared", 2));
    IReader reader;
    auto* streamed = pool.Create("shared", &reader);
    VERIFY(streamed->origin == 2 && pool.preparedReferences.at("shared").clones.size() == 2);
    auto* other = pool.Create("shared");
    VERIFY(other->origin == 2 && pool.preparedReferences.at("shared").clones.size() == 2);
    VERIFY(!pool.PrepareReference("absent", 2) && pool.bAllowChildrenDuplicate);
    VERIFY(pool.PrepareReference("unused", 1));
    VERIFY(pool.PrepareReference("particle", 1) && pool.preparedReferences.at("particle").clones.empty());
    VERIFY(pool.PrepareReference("registered-child", 1) && pool.preparedReferences.at("registered-child").clones.empty());
    VERIFY(pool.PrepareReference("still-live", 2));
    auto* live = pool.Create("still-live");
    pool.ClearPreparedReferences();
    VERIFY(pool.preparedReferences.empty() && dxRender_Visual::releases == 4);
    VERIFY(pool.live.at("shared")->origin == 2 && pool.live.count("still-live") == 1);
    delete first;
    delete second;
    delete streamed;
    delete other;
    delete live;
    for (auto& [key, visual] : pool.live) if (visual != &pool.sharedLeaf) delete visual;
    std::puts("PASS: detached clone construction, ordered admission, pool precedence, explicit input, discard and shutdown");
}
