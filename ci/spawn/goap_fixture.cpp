#include "SpawnGoapRules.h"
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

// Use the exact native condition and RNG implementations from the engine.
using u32 = std::uint32_t;
using u64 = std::uint64_t;
#define IC inline
#include "random32.h"
#include "operator_condition.h"
#undef IC

CRandom32 Random32;

namespace
{
using Property = COperatorConditionAbstract<u32, bool>;

struct Action
{
    struct Rule { u32 id; u32 hash; bool value; bool effect; };
    std::vector<Rule> rules;

    void add_condition(const Property& property) { rules.push_back({property.condition(), property.hash_value(), property.value(), false}); }
    void add_effect(const Property& property) { rules.push_back({property.condition(), property.hash_value(), property.value(), true}); }

    luabind::internal_string serialize() const
    {
        std::string result;
        for (const auto& rule : rules)
            result += std::to_string(rule.id) + "/" + std::to_string(rule.hash) + (rule.value ? "t" : "f") + (rule.effect ? "e;" : "p;");
        return {result.data(), result.size()};
    }
};

void* allocate(luabind::memory_allocation_function_parameter, const void* pointer, size_t size)
{
    if (!size)
    {
        std::free(const_cast<void*>(pointer));
        return nullptr;
    }
    return std::realloc(const_cast<void*>(pointer), size);
}

double now()
{
    using namespace std::chrono;
    return duration<double, std::milli>(steady_clock::now().time_since_epoch()).count();
}
}

int main(int argc, char** argv)
{
    if (argc != 4)
        return 2;
    luabind::allocator = &allocate;
    luabind::allocator_parameter = nullptr;
    auto* L = luaL_newstate();
    if (!L)
        return 2;
    luaL_openlibs(L);
    luabind::open(L);
    Random32.seed(0x7dbe1071);
    using namespace luabind;
    module(L)[
        class_<Property>("world_property")
            .def(constructor<std::uint32_t, bool>()),
        class_<Action>("action_base")
            .def(constructor<>())
            .def("add_precondition", &Action::add_condition)
            .def("add_effect", &Action::add_effect)
            .def("serialize", &Action::serialize),
        def("fixture_clock", &now),
        def("fixture_rng_seed", +[]() { return Random32.seed(); })
    ];
    spawn_goap::register_rules<Action, Property>(L);
    int status = luaL_loadfile(L, argv[1]);
    if (!status)
    {
        lua_pushstring(L, argv[2]);
        lua_pushstring(L, argv[3]);
        status = lua_pcall(L, 2, 0, 0);
    }
    if (status)
        std::cerr << lua_tostring(L, -1) << '\n';
    lua_close(L);
    return status ? 1 : 0;
}
