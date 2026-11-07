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

inline bool SameMember(lua_State* L, int object, int expected, const char* name)
{
    lua_getfield(L, object, name);
    lua_getfield(L, expected, name);
    const bool same = lua_iscfunction(L, -1) && lua_rawequal(L, -1, -2);
    lua_pop(L, 2);
    return same;
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
