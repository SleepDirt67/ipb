#pragma once

#include <cstdint>
#include <limits>
#include <luabind/luabind.hpp>
#include <luabind/detail/class_registry.hpp>
#include <luabind/detail/class_rep.hpp>
#include <luabind/detail/object_rep.hpp>

namespace spawn_goap
{
struct SpawnRule
{
    const char* key;
    bool value;
    bool effect;
};

#include "PreparedSpawnGoapRules.inc"

inline void raw_field(lua_State* L, int index, const char* name)
{
    if (index < 0)
        --index;
    lua_pushstring(L, name);
    lua_rawget(L, index);
}

inline bool metatable_field_is(lua_State* L, int object, const char* field, int expected)
{
    if (!lua_getmetatable(L, object))
        return false;
    raw_field(L, -1, field);
    const bool same = lua_rawequal(L, -1, expected) != 0;
    lua_pop(L, 2);
    return same;
}

inline bool is_plain_table(lua_State* L, int index)
{
    if (!lua_istable(L, index))
        return false;
    if (!lua_getmetatable(L, index))
        return true;
    lua_pop(L, 1);
    return false;
}

inline bool method_is(lua_State* L, const char* name, int expected, bool instanceTable)
{
    raw_field(L, -1, name);
    const bool same = (instanceTable && lua_isnil(L, -1)) || lua_rawequal(L, -1, expected);
    lua_pop(L, 1);
    return same;
}

template <typename Action, typename Property>
bool apply(lua_State* L)
{
    using namespace luabind::detail;
    if (lua_gettop(L) != 4 || lua_type(L, 4) != LUA_TNUMBER || lua_gethook(L)
        || lua_type(L, 1) != LUA_TUSERDATA || lua_type(L, 3) != LUA_TUSERDATA
        || !is_plain_table(L, 2))
        return false;

    const lua_Number number = lua_tonumber(L, 4);
    constexpr auto groupCount = sizeof(spawnRuleOffsets) / sizeof(spawnRuleOffsets[0]) - 1;
    if (!(number >= 0 && number < groupCount) || number != static_cast<unsigned>(number))
        return false;

    const auto* worldProperty = class_registry::get_registry(L)->find_class(LUABIND_TYPEID(Property));
    if (!worldProperty || lua_touserdata(L, 3) != worldProperty
        || !metatable_field_is(L, 3, "__call", lua_upvalueindex(3)))
        return false;

    if (!metatable_field_is(L, 1, "__index", lua_upvalueindex(4))
        || lua_objlen(L, 1) < sizeof(object_rep))
        return false;
    const auto* object = static_cast<object_rep*>(lua_touserdata(L, 1));
    if (!object->ptr() || !(object->flags() & object_rep::lua_class)
        || (object->flags() & (object_rep::constant | object_rep::call_super)))
        return false;

    object->get_lua_table().get(L);
    const bool unmodified = is_plain_table(L, -1)
        && method_is(L, "add_precondition", lua_upvalueindex(1), true)
        && method_is(L, "add_effect", lua_upvalueindex(2), true);
    lua_pop(L, 1);
    if (!unmodified)
        return false;

    object->crep()->get_table(L);
    const bool same = is_plain_table(L, -1)
        && method_is(L, "add_precondition", lua_upvalueindex(1), false)
        && method_is(L, "add_effect", lua_upvalueindex(2), false);
    lua_pop(L, 1);
    if (!same)
        return false;

    ptrdiff_t offset = 0;
    if (implicit_cast(object->crep(), LUABIND_TYPEID(Action), offset) < 0 || object->crep()->has_holder())
        return false;
    auto* action = static_cast<Action*>(object->crep()->convert_to(LUABIND_TYPEID(Action), object, nullptr));
    if (!action)
        return false;

    const auto first = spawnRuleOffsets[static_cast<unsigned>(number)];
    const auto count = spawnRuleOffsets[static_cast<unsigned>(number) + 1] - first;
    std::uint32_t ids[maxSpawnRules];
    for (unsigned i = 0; i < count; ++i)
    {
        raw_field(L, 2, spawnRules[first + i].key);
        const bool numeric = lua_type(L, -1) == LUA_TNUMBER;
        const lua_Number id = lua_tonumber(L, -1);
        lua_pop(L, 1);
        if (!numeric || !(id >= 0 && id <= (std::numeric_limits<std::uint32_t>::max)())
            || id != static_cast<std::uint32_t>(id))
            return false;
        ids[i] = static_cast<std::uint32_t>(id);
    }

    // Use the original mutators, including their validation and hash invalidation.
    for (unsigned i = 0; i < count; ++i)
    {
        const auto& rule = spawnRules[first + i];
        const Property property(ids[i], rule.value);
        if (rule.effect)
            action->add_effect(property);
        else
            action->add_condition(property);
    }
    return true;
}

template <typename Action, typename Property>
int apply_lua(lua_State* L)
{
    const bool applied = apply<Action, Property>(L);
    lua_pushboolean(L, applied);
    return 1;
}

template <typename Action, typename Property>
void register_rules(lua_State* L)
{
    using namespace luabind::detail;
    auto* registry = class_registry::get_registry(L);
    registry->find_class(LUABIND_TYPEID(Action))->get_table(L);
    raw_field(L, -1, "add_precondition");
    raw_field(L, -2, "add_effect");
    lua_remove(L, -3);
    const int refs[] = {registry->cpp_class(), registry->lua_instance()};
    const char* keys[] = {"__call", "__index"};
    for (unsigned i = 0; i < 2; ++i)
    {
        getref(L, refs[i]);
        raw_field(L, -1, keys[i]);
        lua_remove(L, -2);
    }
    lua_pushcclosure(L, (&apply_lua<Action, Property>), 4);
    lua_setglobal(L, "ixray_apply_stock_goap_rules");
}
}
