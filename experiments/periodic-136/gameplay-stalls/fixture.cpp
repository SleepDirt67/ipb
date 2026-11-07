#include <algorithm>
#include <charconv>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <set>
#include <string>
#include <string_view>
#include <vector>
extern "C" {
#include <lua.h>
#include <lauxlib.h>
#include <lualib.h>
}

void require(bool value)
{
    if (!value)
        std::abort();
}

namespace detail {
struct object_rep {};
}
using detail::object_rep;
struct class_registry {
    static class_registry* before_registry(lua_State*);
    static class_registry* after_registry(lua_State*);
};

using u32 = std::uint32_t;
using LPCSTR = const char*;
using string_path = char[520];
using string256 = char[256];
template<class T> using xr_vector = std::vector<T>;
auto xr_strlen = std::strlen;

template <size_t Size, class... Args>
void xr_sprintf(char (&buffer)[Size], const char* format, Args... args)
{
    const int size = std::snprintf(buffer, Size, format, args...);
    require(size >= 0 && static_cast<size_t>(size) < Size);
}

struct CLocatorAPI {
    enum { flNeedRescan=1, flBuildCopy=8, flEBuildCopy=16, flCacheFiles=64 };
    struct Flags {
        unsigned bits = 0;
        bool is_any(unsigned mask) const { return (bits & mask) != 0; }
        bool is(unsigned mask) const { return is_any(mask); }
    } m_Flags;

    struct file {
        const char* name;
        bool operator<(const file& other) const
        {
            return std::strcmp(name, other.name) < 0;
        }
    };
    struct Path {
        std::string directory = "game\\sounds\\";
        const char* m_Path = directory.c_str();
        void _update(string_path& dest, const char* source) const
        {
            xr_sprintf(dest, "%s%s", m_Path, source);
            for (char* p = dest; *p; ++p)
                *p = static_cast<char>(std::tolower(static_cast<unsigned char>(*p)));
        }
    } sound_path;

    std::set<std::string> paths;
    std::set<file> m_files;
    unsigned probes = 0;
    void check_pathes() { m_Flags.bits &= ~flNeedRescan; }
    const Path* get_path(const char*) const { return &sound_path; }
    void insert(std::string path)
    {
        const auto it = paths.insert(sound_path.directory + std::move(path)).first;
        m_files.insert(file{it->c_str()});
    }
    bool exist(string_path& dest, const char*, const char* name, const char* ext)
    {
        ++probes;
        check_pathes();
        const auto relative = std::string(name) + ext;
        sound_path._update(dest, relative.c_str());
        return m_files.contains(file{dest});
    }
    bool find_numbered_sounds(LPCSTR, u32, xr_vector<u32>&);
} FS;

void xr_strconcat(string_path& dest, const char* left, const char* right)
{
    xr_sprintf(dest, "%s%s", left, right);
}

int _GetItemCount(const char* names)
{
    return 1 + std::count(names, names + std::strlen(names), ',');
}

void _GetItem(const char* names, int i, string_path& dest)
{
    while (i--)
        names = std::strchr(names, ',') + 1;
    const auto* next = std::strchr(names, ',');
    xr_sprintf(dest, "%.*s", next ? static_cast<int>(next - names) : static_cast<int>(std::strlen(names)), names);
}

namespace CPU { unsigned QPC() { return 16; } }
struct ref_sound {};
struct SoundCollection {
    struct CSoundCollectionParams {
        const char* const* m_sound_prefix;
        const char* const* m_sound_player_prefix;
        unsigned m_max_count;
        unsigned m_type;
    };
    unsigned m_last_sound_id;
    unsigned seeded;
    unsigned pending_rescan_after = 0;
    ref_sound valid;
    std::vector<ref_sound*> m_sounds;
    std::vector<std::string> requests;
    void seed(unsigned value) { seeded = value; }
    ref_sound* add(unsigned type, const char* name)
    {
        require(type == 9);
        requests.emplace_back(name);
        if (pending_rescan_after == requests.size())
            FS.m_Flags.bits |= CLocatorAPI::flNeedRescan;
        return requests.back().ends_with("19") ? nullptr : &valid;
    }
    void before_collection(const CSoundCollectionParams&);
    void after_collection(const CSoundCollectionParams&);
};

#include "before.inc"
#include "after.inc"

int meta_index(lua_State* L)
{
    auto* calls = static_cast<int*>(lua_touserdata(L, lua_upvalueindex(1)));
    ++*calls;
    const char* key = lua_tostring(L, 2);
    require(key && std::strcmp(key, "__luabind_class") == 0);
    lua_pushboolean(L, true);
    return 1;
}

void verify_lua(lua_State* L)
{
    require(lua_gettop(L) == 0);
    int calls = 0;
    auto* object = static_cast<object_rep*>(lua_newuserdata(L, 4));
    require(!before_class(L, 1) && !after_class(L, 1) && lua_gettop(L) == 1);
    lua_newtable(L);
    lua_pushboolean(L, true);
    lua_setfield(L, -2, "__luabind_class");
    lua_newtable(L);
    lua_pushlightuserdata(L, &calls);
    lua_pushcclosure(L, meta_index, 1);
    lua_setfield(L, -2, "__index");
    lua_setmetatable(L, -2);
    lua_setmetatable(L, 1);

    require(before_class(L, -1) == object && after_class(L, -1) == object && calls == 0);
    lua_getmetatable(L, 1);
    lua_pushboolean(L, false);
    lua_setfield(L, -2, "__luabind_class");
    lua_pop(L, 1);
    require(!before_class(L, 1) && !after_class(L, 1) && calls == 0);
    lua_getmetatable(L, 1);
    lua_pushnil(L);
    lua_setfield(L, -2, "__luabind_class");
    lua_pop(L, 1);
    require(before_class(L, 1) == object && after_class(L, 1) == object && calls == 2);
    require(lua_gettop(L) == 1);

    require(!class_registry::before_registry(L) && !class_registry::after_registry(L));
    class_registry registry;
    lua_pushlightuserdata(L, &registry);
    lua_setfield(L, LUA_REGISTRYINDEX, "__luabind_classes");
    auto* thread = lua_newthread(L);
    for (auto* state : {L, thread})
    {
        const int top = lua_gettop(state);
        require(class_registry::before_registry(state) == &registry);
        require(class_registry::after_registry(state) == &registry);
        require(lua_gettop(state) == top);
    }
    lua_pushnil(L);
    lua_setfield(L, LUA_REGISTRYINDEX, "__luabind_classes");
    lua_settop(L, 0);
}

int main()
{
    auto* first = luaL_newstate();
    auto* second = luaL_newstate();
    verify_lua(first);
    verify_lua(second);
    verify_lua(first);
    lua_close(second);
    lua_close(first);

    for (const char* path : {"voice.ogg", "voice0.ogg", "voice2.ogg", "voice10.ogg", "voice19.ogg",
                             "voice99.ogg", "voice100.ogg", "voice01.ogg", "voice-2.ogg", "voice3.ogg\\x",
                             "voice4.wav", "voice5.OGG", "voicemore.ogg", "sub\\x9.ogg"})
        FS.insert(path);
    for (unsigned i = 0; i < 130; ++i)
        FS.insert("broad_suffix_" + std::to_string(i) + ".ogg");
    std::mt19937 random(1986);
    for (unsigned i = 0; i < 9000; ++i)
    {
        FS.insert("random" + std::to_string(random() % 200) + "_" +
                  std::to_string(random() % 1000) + ".ogg");
    }
    const char* root = "";
    unsigned trials = 0;
    auto compare = [&](const char* prefix, unsigned count, unsigned flags, unsigned rescan_after)
    {
        SoundCollection a, b;
        a.pending_rescan_after = b.pending_rescan_after = rescan_after;
        const SoundCollection::CSoundCollectionParams params{&prefix, &root, count, 9};
        FS.m_Flags.bits = flags;
        FS.probes = 0;
        a.before_collection(params);
        const unsigned previous_probes = FS.probes;
        FS.m_Flags.bits = flags;
        FS.probes = 0;
        b.after_collection(params);
        require(a.requests == b.requests);
        require(a.m_sounds.size() == b.m_sounds.size() && a.m_last_sound_id == b.m_last_sound_id);
        require(a.seeded == b.seeded && FS.probes <= previous_probes);
        ++trials;
    };
    for (unsigned limit : {0, 15, 16, 20, 100, 1000, 1001})
    {
        compare("VOiCe,sub\\x", limit, 0, 0);
        compare("voice", limit, CLocatorAPI::flBuildCopy, 0);
        compare("voice", limit, 0, 3);
        compare("broad", limit, 0, 0);
    }
    for (unsigned i = 0; i < 2000; ++i)
    {
        const auto prefix = "random" + std::to_string(random() % 220) + "_";
        compare(prefix.c_str(), random() % 1100, 0, 0);
    }
    compare("voice", 100, 0, 0);
    require(FS.probes == 1);
    std::printf("PASS: Lua lookup equivalence; %u sound sequences; numbered probes 100 to 0\n", trials);
}
