"""Apply isolated runtime fixes to IX-Ray r1.3.6 and its pinned Luabind."""
from pathlib import Path
import sys


def edit(root, name, replacements):
    path = root / name
    data = path.read_bytes()
    source = data.decode("utf-8").replace("\r\n", "\n")
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError(f"{name}: expected exactly one {before[:80]!r}")
        source = source.replace(before, after, 1)
    if b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""):
        source = source.replace("\n", "\r\n")
    path.write_bytes(source.encode("utf-8"))


def patch(engine, luabind):
    edit(luabind, "luabind/include/luabind/detail/object_rep.hpp", [
        ('\t\tlua_pushstring(L, "__luabind_class");\n\t\tlua_gettable(L, -2);',
         '\t\t// A fixed field lookup keeps __index and avoids the push-string GC check.\n'
         '\t\tlua_getfield(L, -1, "__luabind_class");'),
    ])
    edit(luabind, "luabind/src/class_registry.cpp", [
        ('        lua_pushstring(L, "__luabind_classes");\n'
         '        lua_gettable(L, LUA_REGISTRYINDEX);',
         '        lua_getfield(L, LUA_REGISTRYINDEX, "__luabind_classes");'),
    ])

    edit(engine, "src/xrCore/LocatorAPI.h", [
        ('\tBOOL\t\t\t\t\t\tfile_find',
         '\t// Collect the existing canonical numbered OGG variants, in numeric order.\n'
         '\t// Return false when the caller should use individual existence probes.\n'
         '\tbool find_numbered_sounds(LPCSTR prefix, u32 limit, xr_vector<u32>& indices);\n\n'
         '\tBOOL\t\t\t\t\t\tfile_find'),
    ])
    edit(engine, "src/xrCore/LocatorAPI.cpp", [
        ('#include <fstream>', '#include <fstream>\n#include <charconv>\n#include <string_view>'),
        ('BOOL CLocatorAPI::dir_delete(LPCSTR path,LPCSTR nm,BOOL remove_files)',
         """bool CLocatorAPI::find_numbered_sounds(LPCSTR prefix, u32 limit, xr_vector<u32>& indices)
{
    indices.clear();
    // The legacy path formats these names into string256 and takes a signed
    // decimal index. Retain it for unusual inputs and copy/cache modes.
    if (limit < 16 || limit > 1000 || !prefix[0] || xr_strlen(prefix) > 240 ||
        m_Flags.is_any(flBuildCopy | flEBuildCopy | flCacheFiles))
        return false;

    string_path key;
    const auto* path = get_path("$game_sounds$");
    if (xr_strlen(path->m_Path) + xr_strlen(prefix) + 7 >= sizeof(key))
        return false;
    path->_update(key, prefix);
    check_pathes();

    file first{};
    first.name = key;
    const std::string_view base(key);
    constexpr std::string_view extension = ".ogg";
    u32 scanned = 0;
    for (auto it = m_files.lower_bound(first); it != m_files.end(); ++it)
    {
        std::string_view name(it->name);
        if (!name.starts_with(base))
            break;

        // A very broad prefix can match more files than point probes would.
        if (++scanned > limit)
        {
            indices.clear();
            return false;
        }

        name.remove_prefix(base.size());
        if (!name.ends_with(extension))
            continue;
        name.remove_suffix(extension.size());
        if (name.empty() || (name.size() > 1 && name.front() == '0'))
            continue;

        u32 index = 0;
        const auto end = name.data() + name.size();
        const auto result = std::from_chars(name.data(), end, index);
        if (result.ec == std::errc{} && result.ptr == end && index < limit)
            indices.push_back(index);
    }
    std::sort(indices.begin(), indices.end());
    return true;
}

BOOL CLocatorAPI::dir_delete(LPCSTR path,LPCSTR nm,BOOL remove_files)"""),
    ])
    edit(engine, "src/xrGame/sound_player.cpp", [
        ('\t\tfor (u32 i=0; i<params.m_max_count; ++i){',
         """        u32 i = 0;
        xr_vector<u32> variants;
        if (FS.find_numbered_sounds(s, params.m_max_count, variants))
        {
            for (u32 variant : variants)
            {
                if (FS.m_Flags.is(CLocatorAPI::flNeedRescan))
                    break;
                string256 name;
                xr_sprintf(name, "%s%d", s, variant);
                if (auto* sound = add(params.m_type, name))
                    m_sounds.push_back(sound);
                i = variant + 1;
            }
            if (!FS.m_Flags.is(CLocatorAPI::flNeedRescan))
                continue;
        }
        for (; i < params.m_max_count; ++i){"""),
    ])


if __name__ == "__main__":
    patch(Path(sys.argv[1]), Path(sys.argv[2]))
