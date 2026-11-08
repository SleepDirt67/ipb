"""Prepare the actual VFS voice catalogue and fuse the guarded binder operations."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundle = Path(__file__).resolve().parent
stock = (root / "gamedata/scripts/sound_theme.script").read_bytes().replace(b"\r\n", b"\n")

def apply(name, replacements):
    file = root / name
    original = file.read_bytes()
    text = original.replace(b"\r\n", b"\n").decode("utf-8")
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError((name, before[:90], text.count(before)))
        text = text.replace(before, after, 1)
    output = text.encode("utf-8")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    file.write_bytes(output)

core = root / "src/xrCore"
for filename in ("SpawnVoiceCatalogue.h", "SpawnVoiceVfs.inc"):
    shutil.copyfile(bundle / filename, core / filename)
for filename in ("SpawnVoiceBindings.h", "SpawnVoiceApply.inc", "SpawnVoiceScope.h"):
    shutil.copyfile(bundle / filename, root / "src/xrGame" / filename)

apply("src/xrCore/LocatorAPI.h", [
    ('#pragma once', '#pragma once\n#include <memory>\nnamespace SpawnVoice { class Catalogue; }'),
    ("    void\t\t\t\t\t\tcheck_pathes\t();",
     "    void\t\t\t\t\t\tcheck_pathes\t();\n"
     "    bool read_spawn_voice_catalogue(LPCSTR base, int* count, u32 limit, xr_vector<u32>* variants);"),
    ("    int sound_variant_count(LPCSTR prefix);", """    int sound_variant_count(LPCSTR prefix);
    void prepare_spawn_voice_catalogue();
    int prepared_spawn_voice_count(LPCSTR prefix);
    std::shared_ptr<const SpawnVoice::Catalogue> acquire_spawn_voice_catalogue();"""),
])
apply("src/xrCore/LocatorAPI.cpp", [
    ('#include "xrAddons.h"', '''#include "xrAddons.h"
#include "SpawnVoiceCatalogue.h"
#include <atomic>
#include <cstdlib>
#include <mutex>
#include <shared_mutex>
#include "SpawnVoiceVfs.inc"'''),
    ("\tm_files.insert\t\t(desc); ", "\tspawnVoiceIndex.Invalidate(this, desc.name);\n\tm_files.insert\t\t(desc); "),
    ("\t\t\tchar* str\t\t= LPSTR(I->name);\n\t\t\txr_free\t\t\t(str);",
     "\t\t\tspawnVoiceIndex.Invalidate(this, entry.name);\n\t\t\tchar* str\t\t= LPSTR(I->name);\n\t\t\txr_free\t\t\t(str);"),
    ("void CLocatorAPI::_destroy()\n{", "void CLocatorAPI::_destroy()\n{\n    spawnVoiceIndex.Reset(this);"),
    ("\t\t\t\tm_files.erase(cur_item);", "\t\t\t\tspawnVoiceIndex.Invalidate(this, entry.name);\n\t\t\t\tm_files.erase(cur_item);"),
    ("\t\txr_free(str);\n\t\tm_files.erase(I);", "\t\tspawnVoiceIndex.Invalidate(this, I->name);\n\t\txr_free(str);\n\t\tm_files.erase(I);"),
    ("\t\t\tchar* str\t= LPSTR(D->name);", "\t\t\tspawnVoiceIndex.Invalidate(this, D->name);\n\t\t\tchar* str\t= LPSTR(D->name);"),
    ("\t\tfile new_desc\t= *S;", "\t\tfile new_desc\t= *S;\n\t\tspawnVoiceIndex.Invalidate(this, S->name);"),
    ("\t\tm_files.insert(new_desc); ", "\t\tspawnVoiceIndex.Invalidate(this, new_desc.name);\n\t\tm_files.insert(new_desc); "),
    ("\t\tchar* str\t\t= LPSTR(cur_item->name);", "\t\tspawnVoiceIndex.Invalidate(this, cur_item->name);\n\t\tchar* str\t\t= LPSTR(cur_item->name);"),
    ("    const auto* path = get_path(\"$game_sounds$\");\n    if (xr_strlen(path->m_Path)",
     "    if (read_spawn_voice_catalogue(prefix, nullptr, limit, &indices))\n        return true;\n"
     "    const auto* path = get_path(\"$game_sounds$\");\n    if (xr_strlen(path->m_Path)"),
])
apply("src/xrEngine/IGame_Persistent.cpp", [
    ("\tif (!g_dedicated_server)\n\t\tPrepareSpawnSoundMetadata();", """\tif (!g_dedicated_server)
    {
        FS.prepare_spawn_voice_catalogue();
        PrepareSpawnSoundMetadata();
    }"""),
])
apply("src/xrGame/fs_registrator_script.cpp", [
    ('#include "fs_registrator.h"', '#include "fs_registrator.h"\n#include "SpawnVoiceBindings.h"'),
    ('\t\tdef("getFS",\t\t\t\t\t\t\t\t\tgetFS)\n\t];',
     '''\t\tdef("getFS",\t\t\t\t\t\t\t\t\tgetFS)
\t];
    static constexpr const char* methods[] = {"exist", "sound_variant_count"};
    SpawnVoice::Capture(L, SpawnVoice::fsKey, "FS", methods, std::size(methods));'''),
])
apply("src/xrGame/script_game_object_script.cpp", [
    ('#include "../xrScripts/exports/script_ini_file.h"',
     '''#include "../xrScripts/exports/script_ini_file.h"
#include "../xrSound/ai_sounds.h"
#include "GameObject.h"
#include "SpawnVoiceBindings.h"
#include "SpawnVoiceScope.h"
#include "../xrCore/SpawnVoiceCatalogue.h"
#include "SpawnVoiceApply.inc"'''),
    ('\t\tdef("show_condition",\t\t\t\t&::show_condition)\n\t];',
     '''\t\tdef("show_condition",\t\t\t\t&::show_condition)
\t];
    SpawnVoice::RegisterNativeApply(L);'''),
])

apply("src/xrGame/Level_network_spawn.cpp", [
    ('#include "SpawnAdmission.inc"', '#include "SpawnAdmission.inc"\n#include "SpawnVoiceScope.h"'),
    ('        spawnSucceeded = O->net_Spawn(E);', '''        const auto voiceSource = [](const void* context) {
            return SpawnPreparation::ActivationScope::PreparedBinder(static_cast<const IPhysicsShellHolder*>(context));
        };
        SpawnVoice::Scope voice(O->cast_game_object(),
            static_cast<const IPhysicsShellHolder*>(alive), voiceSource);
        spawnSucceeded = O->net_Spawn(E);
        if (voice.Registrations())
        {
            const auto payload = static_cast<unsigned long long>(E->ID) |
                (static_cast<unsigned long long>(voice.Registrations()) << 16) |
                (static_cast<unsigned long long>(voice.PreparedNames()) << 40);
            PacingDiag::SpawnSpan preparedVoice(PacingDiag::Kind::SpawnBinderPrepared, payload);
        }'''),
])
apply("src/xrGame/Level_network_start_client.cpp", [
    ('        PrepareSpawnVisuals();',
     '        PrepareSpawnVisuals();\n        FS.prepare_spawn_voice_catalogue();'),
])
apply("src/xrEngine/PacingDiagnostics.h", [
    ("SpawnPrepareUse, SpawnPrepareMiss", "SpawnPrepareUse, SpawnPrepareMiss, SpawnBinderPrepared"),
])
apply("src/xrGame/Level.cpp", [
    ('spawnActivationWork = SpawnPreparation::StartActivationWork(ObjectSpace.GetStaticModel());',
     'spawnActivationWork = SpawnPreparation::StartActivationWork(ObjectSpace.GetStaticModel(),\n'
     '            FS.acquire_spawn_voice_catalogue());'),
])

first = stock.index(b"function npc_sound:init_npc(npc)")
last = stock.index(b"function npc_sound:callback", first)
fast = b"""\tlocal applied = stock_bind_voice and stock_bind_voice(npc, self, npc_id)
    if not applied then
"""
# Keep the PR24 catalogue fallback, including the exact legacy Lua branch.
inc = root / "src/xrScripts/StockVoiceScript.inc"
import re
old_generated = inc.read_text(encoding="ascii")
array = re.search(r"batchedVoiceFunction\[\] = \{\n([\d,\s]+)\n\};", old_generated)
assert array
previous = bytes(int(item) for item in re.findall(r"\d+", array[1]))
fallback_begin = previous.index(b"\tif self.is_combat_sound then")
fallback_end = previous.index(b"\tif self.npc[npc_id].max < 0 then", fallback_begin)
previous_block = previous[fallback_begin:fallback_end]
new = previous[:fallback_begin] + fast + previous_block + b"    end\n" + previous[fallback_end:]
# Pull the original native entry point into the same verified lexical scope.
assert new.startswith(b"do\n")
new = b"do\nlocal stock_bind_voice = ixray_apply_spawn_voice\n" + new[3:]
formatted = ",\n".join(", ".join(str(value) for value in new[i:i+32]) for i in range(0, len(new), 32))
inc.write_text(old_generated[:array.start(1)] + formatted + old_generated[array.end(1):], encoding="ascii")

shutil.copyfile(bundle / "voice_replay.cpp", root / "ixray_spawn_mainline_replay.cpp")
with (root / "CMakeLists.txt").open("a", encoding="utf-8") as target:
    target.write("""
add_executable(ixray_spawn_mainline_replay ixray_spawn_mainline_replay.cpp)
target_include_directories(ixray_spawn_mainline_replay PRIVATE src/xrCore "${IXRAY_SDK_INC}")
target_link_libraries(ixray_spawn_mainline_replay PRIVATE xrCore luabind Lua::Lua)
""")

if len(sys.argv) > 2:
    output = Path(sys.argv[2])
    output.mkdir(parents=True, exist_ok=True)
    (output / "stock.lua").write_bytes(stock)
    (output / "previous.lua").write_bytes(stock[:first] + previous + b"\n" + stock[last:])
    (output / "candidate.lua").write_bytes(stock[:first] + new + b"\n" + stock[last:])
