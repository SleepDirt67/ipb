"""Wire static spawn descriptors into the same engine/script entry points."""
from pathlib import Path
import sys

root = Path(sys.argv[1])


def edit(path, before, after):
    target = root / path
    original = target.read_bytes()
    style = b'\r\n' if b'\r\n' in original else b'\n'
    data = original.replace(b'\r\n', b'\n')
    before, after = before.encode(), after.encode()
    if data.count(before) != 1:
        raise ValueError((path, before, data.count(before)))
    target.write_bytes(data.replace(before, after, 1).replace(b'\n', style))


edit('src/xrScripts/script_storage.cpp', '#include "script_process.h"', '''#include "script_process.h"
#include <cstdlib>
#include <string_view>

namespace
{
#include "PreparedStockLogic.inc"
#include "PreparedStockGoap.inc"

template <size_t OriginalSize, size_t PreparedSize>
std::string_view MatchStockScript(std::string_view data, const unsigned char (&original)[OriginalSize],
    const unsigned char (&prepared)[PreparedSize])
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_SPAWN_PLANS");
        return !setting || xr_strcmp(setting, "0") != 0;
    }();
    if (!enabled || data.size() < OriginalSize || data.size() > 2 * OriginalSize)
        return {};

    size_t index = 0;
    for (size_t offset = 0; offset < data.size(); ++offset)
    {
        if (data[offset] == '\\r' && offset + 1 < data.size() && data[offset + 1] == '\\n')
            continue;
        if (index == OriginalSize || static_cast<unsigned char>(data[offset]) != original[index++])
            return {};
    }
    if (index != OriginalSize)
        return {};
    return {reinterpret_cast<const char*>(prepared), PreparedSize};
}

std::string_view PrepareStockSpawnScript(LPCSTR name, std::string_view data)
{
    if (name && xr_strcmp(name, "xr_logic") == 0)
        return MatchStockScript(data, stockLogic, preparedStockLogic);
    if (name && xr_strcmp(name, "state_mgr_goap") == 0)
        return MatchStockScript(data, stockGoap, preparedStockGoap);
    return {};
}
}''')

edit('src/xrScripts/script_storage.cpp',
     '        loaded = load_buffer(lua(), static_cast<LPCSTR>(l_tpFileReader->pointer()), (size_t)l_tpFileReader->length(), caNameSpaceName, caNameSpaceName);',
     '''        const std::string_view original(static_cast<LPCSTR>(l_tpFileReader->pointer()),
            static_cast<size_t>(l_tpFileReader->length()));
        const auto prepared = PrepareStockSpawnScript(caNameSpaceName, original);
        const auto source = prepared.empty() ? original : prepared;
        if (!prepared.empty())
            Msg("* %s: prepared stock spawn script", caNameSpaceName);
        loaded = load_buffer(lua(), source.data(), source.size(), caNameSpaceName, caNameSpaceName);''')

edit('src/xrScripts/exports/script_ini_file_script.cpp', '#include "script_ini_file.h"',
     '''#include "script_ini_file.h"
#include "SpawnSwitchKeys.h"

// Read the authoritative ordered section on each resume. Lua still calls
// the original rule reader at the original position and applies its effects.
static int next_switch_key(CScriptIniFile* ini, LPCSTR section, LPCSTR prefix, int start, int end, luabind::internal_string& result)
{
    result.clear();
    if (!ini->section_exist(section))
        return -2;

    const auto& entries = ini->r_section(section).Data;
    const int index = NextSpawnSwitchKey(entries, prefix, start, end);
    if (index >= 0)
        result = entries[index].first.c_str();
    return index;
}''')
edit('src/xrScripts/exports/script_ini_file_script.cpp',
     '\t\t\t.def("line_count",\t\t&CScriptIniFile::line_count)',
     '''\t\t\t.def("line_count",\t\t&CScriptIniFile::line_count)
            .def("ixray_next_switch_key", &next_switch_key, out_value<6>())''')


edit('src/xrGame/action_base_script.cpp', '#include "script_game_object.h"',
     '#include "script_game_object.h"\n#include "script_world_property.h"\n#include "SpawnGoapRules.h"')
edit('src/xrGame/action_base_script.cpp', '\n\t];\n}', '\n\t];\n    spawn_goap::register_rules<CScriptActionBase, CScriptWorldProperty>(L);\n}')

fixture_root = Path(__file__).resolve().parent
target_dir = root / 'src/xrScripts/exports'
(root / 'src/xrGame/SpawnGoapRules.h').write_bytes((fixture_root / 'SpawnGoapRules.h').read_bytes())
(target_dir / 'SpawnSwitchKeys.h').write_bytes((fixture_root / 'SpawnSwitchKeys.h').read_bytes())
(root / 'ixray_spawn_goap_fixture.cpp').write_bytes((fixture_root / 'goap_fixture.cpp').read_bytes())
(root / 'ixray_spawn_plan_fixture.cpp').write_bytes((fixture_root / 'native_fixture.cpp').read_bytes())
with (root / 'CMakeLists.txt').open('a', encoding='utf-8') as cmake:
    cmake.write("""
add_executable(ixray_spawn_plan_fixture ixray_spawn_plan_fixture.cpp)
target_include_directories(ixray_spawn_plan_fixture PRIVATE src/xrCore src/xrScripts/exports)
target_link_libraries(ixray_spawn_plan_fixture PRIVATE xrCore)
add_executable(ixray_spawn_goap_fixture ixray_spawn_goap_fixture.cpp)
target_include_directories(ixray_spawn_goap_fixture PRIVATE src/xrGame)
target_link_libraries(ixray_spawn_goap_fixture PRIVATE luabind)
""")
