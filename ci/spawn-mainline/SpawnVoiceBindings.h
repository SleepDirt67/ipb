#pragma once

#include <luabind/detail/class_rep.hpp>
#include <luabind/detail/object_rep.hpp>
#include <cstdlib>
#include <exception>
#include <iterator>
#include <limits>
#include <string>

namespace SpawnVoice
{
inline constexpr char fsKey[] = "ixray.spawn.voice.fs";
inline constexpr char npcKey[] = "ixray.spawn.voice.npc";

inline void Capture(lua_State* L, const char* registryKey, const char* type, const char* const* members, size_t count)
{
    lua_getglobal(L, type);
    auto* rep = static_cast<luabind::detail::class_rep*>(lua_touserdata(L, -1));
    if (!rep)
    {
        lua_pop(L, 1);
        return;
    }
    lua_newtable(L);
    lua_pushvalue(L, -2);
    lua_setfield(L, -2, "class");
    rep->get_table(L);
    for (size_t i = 0; i < count; ++i)
    {
        lua_getfield(L, -1, members[i]);
        lua_setfield(L, -3, members[i]);
    }
    lua_pop(L, 1);
    if (registryKey == fsKey)
    {
        lua_getglobal(L, "getFS");
        lua_setfield(L, -2, "getFS");
    }
    lua_setfield(L, LUA_REGISTRYINDEX, registryKey);
    lua_pop(L, 1);
}

enum Key
{
    Index = 1, Class, NpcKey, FsKey, GetFs, Exist, VariantCount, Add, CombatAdd, Prefix, Path, Combat,
    NpcState, SoundPaths, Id, Max, Limit, SoundType, Talk, KeyCount = Talk
};
inline constexpr const char* Keys[] = {
    "__index", "class", npcKey, fsKey, "getFS", "exist", "sound_variant_count", "add_sound", "add_combat_sound",
    "sound_prefix", "path", "is_combat_sound", "npc", "sound_path", "id", "max", "nstl",
    "snd_type", "talk"
};
static_assert(std::size(Keys) == KeyCount);

// Keys are pinned as C closure upvalues at registration. Raw reads here
// neither invoke Lua metatables nor call lua_pushstring's GC check.
inline void RawField(lua_State* L, int table, Key key)
{
    if (table < 0 && table > LUA_REGISTRYINDEX)
        --table;
    lua_pushvalue(L, lua_upvalueindex(key));
    lua_rawget(L, table);
}

inline bool PlainTable(lua_State* L, int index)
{
    if (!lua_istable(L, index))
        return false;
    if (!lua_getmetatable(L, index))
        return true;
    lua_pop(L, 1);
    return false;
}

inline luabind::detail::object_rep* ReadWrapper(lua_State* L, int index, lua_CFunction getter)
{
    if (lua_type(L, index) != LUA_TUSERDATA ||
        lua_objlen(L, index) < sizeof(luabind::detail::object_rep) || !lua_getmetatable(L, index))
        return nullptr;
    RawField(L, -1, Index);
    const bool native = lua_tocfunction(L, -1) == getter;
    lua_pop(L, 2);
    return native ? static_cast<luabind::detail::object_rep*>(lua_touserdata(L, index)) : nullptr;
}

inline bool PushMember(lua_State* L, const luabind::detail::object_rep& wrapper, Key key)
{
    const auto& instance = wrapper.get_lua_table();
    if (instance.is_valid())
    {
        instance.get(L);
        if (!PlainTable(L, -1))
        {
            lua_pop(L, 1);
            return false;
        }
        RawField(L, -1, key);
        lua_remove(L, -2);
        if (!lua_isnil(L, -1))
            return true;
        lua_pop(L, 1);
    }
    wrapper.crep()->get_table(L);
    if (!PlainTable(L, -1))
    {
        lua_pop(L, 1);
        return false;
    }
    RawField(L, -1, key);
    lua_remove(L, -2);
    return true;
}

inline bool SameMember(lua_State* L, const luabind::detail::object_rep& object, int expected, Key key)
{
    if (!PushMember(L, object, key))
        return false;
    RawField(L, expected, key);
    const bool same = lua_iscfunction(L, -1) && lua_rawequal(L, -1, -2);
    lua_pop(L, 2);
    return same;
}

inline bool PushGlobal(lua_State* L, int environment, Key key)
{
    RawField(L, environment, key);
    if (!lua_isnil(L, -1))
        return true;
    lua_pop(L, 1);
    if (!lua_getmetatable(L, environment))
        return false;
    RawField(L, -1, Index);
    const bool ordinaryNamespace = lua_rawequal(L, -1, LUA_GLOBALSINDEX);
    lua_pop(L, 2);
    if (!ordinaryNamespace)
        return false;
    RawField(L, LUA_GLOBALSINDEX, key);
    return true;
}

inline bool ReadUnsigned(lua_State* L, int index, u32& out)
{
    if (lua_type(L, index) != LUA_TNUMBER)
        return false;
    const auto value = lua_tonumber(L, index);
    if (!(value >= 0 && value <= (std::numeric_limits<u32>::max)()))
        return false;
    out = static_cast<u32>(value);
    return out == value;
}
}
