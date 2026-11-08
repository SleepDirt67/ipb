"""Build a differential fixture from the original and installed C++ function bodies."""
import argparse
from pathlib import Path

from apply import patch

args = argparse.ArgumentParser()
for name in ("engine", "luabind", "output"):
    args.add_argument(name, type=Path)
a = args.parse_args()

files = (
    (a.luabind / "luabind/include/luabind/detail/object_rep.hpp", "inline object_rep* is_class_object"),
    (a.luabind / "luabind/src/class_registry.cpp", "class_registry* class_registry::get_registry"),
    (a.engine / "src/xrGame/sound_player.cpp", "CSoundPlayer::CSoundCollection::CSoundCollection"),
)


def function(path, signature):
    source = path.read_text(encoding="utf-8")
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise ValueError(signature)


def extract():
    return [function(path, signature) for path, signature in files]


old = extract()
patch(a.engine, a.luabind)
new = extract()
# Instrument the pinned Luabind initialization only when the replay
# debugging environment is enabled. Trace calls that happen before Lua scripts run.
from apply import edit
edit(a.luabind, "luabind/src/open.cpp", [
    ('#include "luabind_api.h"', '#include "luabind_api.h"\n#include <cstdio>\n#include <cstdlib>'),
    ('    void open(lua_State* L)\n    {',
     '''    void open(lua_State* L)
    {
        auto trace = [](const char* step) {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN"))
                std::fprintf(stderr, "[LUABIND-OPEN] %s\\n", step);
        };
        trace("entered");'''),
    ('        lua_pushstring(L, "__luabind_classes");',
     '        trace("before registry push");\n        lua_pushstring(L, "__luabind_classes");\n        trace("after registry push");'),
    ('        r = static_cast<detail::class_registry*>(lua_newuserdata(L, sizeof(detail::class_registry)));',
     '        trace("before registry userdata");\n        r = static_cast<detail::class_registry*>(lua_newuserdata(L, sizeof(detail::class_registry)));\n        trace("after registry userdata");'),
    ('        lua_newtable(L);\n        lua_pushstring(L, "__gc");',
     '        trace("before GC metatable");\n        lua_newtable(L);\n        lua_pushstring(L, "__gc");'),
    ('        lua_setmetatable(L, -2);',
     '        lua_setmetatable(L, -2);\n        trace("after GC metatable");'),
    ('        new(r) detail::class_registry(L);',
     '        trace("before class_registry construction");\n        new(r) detail::class_registry(L);\n        trace("after class_registry construction");'),
    ('        lua_settable(L, LUA_REGISTRYINDEX);',
     '        lua_settable(L, LUA_REGISTRYINDEX);\n        trace("after registry publish");'),
    ('        lua_settable(L, LUA_GLOBALSINDEX);',
     '        lua_settable(L, LUA_GLOBALSINDEX);\n        trace("returned");'),
])
edit(a.luabind, "luabind/src/class_registry.cpp", [
    ('#include "luabind_api.h"', '#include "luabind_api.h"\n#include <cstdio>\n#include <cstdlib>'),
    ('        int create_cpp_class_metatable(lua_State* L)\n        {',
     '''        int create_cpp_class_metatable(lua_State* L)
        {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN")) std::fprintf(stderr, "[LUABIND-REG] cpp class start\\n");'''),
    ('        int create_cpp_instance_metatable(lua_State* L)\n        {',
     '''        int create_cpp_instance_metatable(lua_State* L)
        {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN")) std::fprintf(stderr, "[LUABIND-REG] cpp instance start\\n");'''),
    ('        int create_lua_class_metatable(lua_State* L)\n        {',
     '''        int create_lua_class_metatable(lua_State* L)
        {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN")) std::fprintf(stderr, "[LUABIND-REG] lua class start\\n");'''),
    ('        int create_lua_instance_metatable(lua_State* L)\n        {',
     '''        int create_lua_instance_metatable(lua_State* L)
        {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN")) std::fprintf(stderr, "[LUABIND-REG] lua instance start\\n");'''),
    ('        int create_lua_function_metatable(lua_State* L)\n        {',
     '''        int create_lua_function_metatable(lua_State* L)
        {
            if (std::getenv("IXRAY_DEBUG_LUABIND_OPEN")) std::fprintf(stderr, "[LUABIND-REG] lua function start\\n");'''),
])

new.append(function(a.engine / "src/xrCore/LocatorAPI.cpp", "bool CLocatorAPI::find_numbered_sounds"))
a.output.mkdir(parents=True, exist_ok=True)
for name, functions in (("before", old), ("after", new)):
    functions[1] = functions[1].replace("class_registry::get_registry", f"class_registry::{name}_registry")
    functions[0] = functions[0].replace("is_class_object", f"{name}_class")
    functions[2] = functions[2].replace("CSoundPlayer::CSoundCollection::CSoundCollection",
                                       f"void SoundCollection::{name}_collection")
    (a.output / f"{name}.inc").write_text("\n\n".join(functions) + "\n", encoding="utf-8")
