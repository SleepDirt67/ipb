"""Fuse the verified stock community query inside a stalker's net_Spawn."""
import argparse
import hashlib
import shutil
from pathlib import Path


STOCK_HASH = "0b671e24d737087d4c97ad10758110d628039ae57146ca470d93273a2b9fa79f"


def edit(path, replacements):
    original = path.read_bytes()
    result = original.replace(b"\r\n", b"\n")
    for before, after in replacements:
        before, after = before.encode(), after.encode()
        if result.count(before) != 1:
            raise ValueError((path, before[:70], result.count(before)))
        result = result.replace(before, after, 1)
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        result = result.replace(b"\n", b"\r\n")
    path.write_bytes(result)


def array(name, data):
    values = [", ".join(map(str, data[i:i + 32])) for i in range(0, len(data), 32)]
    return f"static constexpr unsigned char {name}[] = {{\n" + ",\n".join(values) + "\n};\n"


def generate(root, output):
    stock = (root / "gamedata/scripts/_g.script").read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(stock).hexdigest() != STOCK_HASH:
        raise ValueError("Unexpected stock _g.script")
    start = stock.index(b"function character_community (obj)")
    replacement = b"""local spawn_native_community = rawget(_G, "ixray_read_spawn_community")
local spawn_stock_is_stalker = IsStalker
local spawn_stock_get_clsid = get_clsid

function character_community (obj)
    if spawn_native_community and IsStalker == spawn_stock_is_stalker and get_clsid == spawn_stock_get_clsid then
        local community = spawn_native_community(obj, spawn_stock_is_stalker, spawn_stock_get_clsid, stalker_classes)
        if community ~= nil then
            return community
        end
    end"""
    declaration = b"function character_community (obj)"
    candidate = stock[:start] + stock[start:].replace(declaration, replacement, 1)
    (root / "src/xrScripts/PreparedCommunity.inc").write_text(
        array("stockCommunityScript", stock) + array("preparedCommunityScript", candidate),
        encoding="ascii",
    )
    if output:
        output.mkdir(parents=True, exist_ok=True)
        def fixture(source):
            first = source.index(b"function get_clsid(npc)")
            get_clsid = source[first:source.index(b"--", first)]
            is_stalker = source[source.index(b"function IsStalker"):source.index(b"function isWeapon")]
            start = source.find(b"local spawn_native_community")
            if start == -1:
                start = source.index(b"function character_community (obj)")
            community = source[start:source.index(b"function alife_character_community")]
            return b"local stalker_classes = {[42] = true}\n" + get_clsid + is_stalker + community

        (output / "community-stock.lua").write_bytes(fixture(stock))
        (output / "community-candidate.lua").write_bytes(fixture(candidate))


def patch(root, output):
    game = root / "src/xrGame"
    generate(root, output)
    shutil.copyfile(Path(__file__).with_name("SpawnCommunity.inc"), game / "SpawnCommunity.inc")
    edit(game / "SpawnVoiceBindings.h", [
        ("SoundType, Talk, KeyCount = Talk", "SoundType, Talk, Clsid, Community, GetClsid, KeyCount = GetClsid"),
        ('    "snd_type", "talk"', '    "snd_type", "talk", "clsid", "character_community", "get_clsid"'),
    ])
    edit(game / "SpawnVoiceScope.h", [
        ("    static std::shared_ptr<const void> Prepared(const void* owner)",
         """    static bool Contains(const void* owner)
    {
        return owner && current_ && current_->owner_ == owner;
    }

    static std::shared_ptr<const void> Prepared(const void* owner)"""),
    ])
    edit(game / "SpawnVoiceApply.inc", [
        ("void RegisterNativeApply(lua_State* L)", '#include "SpawnCommunity.inc"\n\nvoid RegisterNativeApply(lua_State* L)'),
        ('"sound_prefix", "add_sound", "add_combat_sound"', '"sound_prefix", "add_sound", "add_combat_sound", "clsid", "character_community"'),
        ('    lua_setglobal(L, "ixray_apply_spawn_voice");',
         '''    lua_setglobal(L, "ixray_apply_spawn_voice");
    for (const auto* key : Keys)
        lua_pushstring(L, key);
    lua_pushcclosure(L, ReadCommunity, KeyCount);
    lua_setglobal(L, "ixray_read_spawn_community");'''),
    ])
    shutil.copyfile(Path(__file__).with_name("community_replay.inc"), root / "community_replay.inc")
    edit(root / "ixray_spawn_mainline_replay.cpp", [
        ("    unsigned id() const { return id_; }", """    unsigned id() const { return id_; }
    int clsid() const { return 42; }
    const char* CharacterCommunity() { return "stalker"; }"""),
        ('            .def("id", &CScriptGameObject::id)', '''            .def("id", &CScriptGameObject::id)
            .def("clsid", &CScriptGameObject::clsid)
            .def("character_community", &CScriptGameObject::CharacterCommunity)'''),
        ("int main(int argc, char** argv)", '#include "community_replay.inc"\n\nint main(int argc, char** argv)'),
        ('    Require(argc == 5, "stock, previous, candidate and replay input");', '''    if (argc == 4 && std::string_view(argv[1]) == "--community")
    {
        Core._initialize("spawn-community-replay", nullptr, FALSE, nullptr);
        luabind::allocator = &ReplayLuabindAllocator;
        luabind::allocator_parameter = nullptr;
        CheckCommunity(argv[2], argv[3]);
        Core._destroy();
        return 0;
    }
    Require(argc == 5, "stock, previous, candidate and replay input");'''),
    ])
    # _g is loaded in the global namespace, unlike the named script modules.
    edit(root / "src/xrScripts/script_storage.cpp", [
        ('#include "PreparedStockLogic.inc"', '#include "PreparedStockLogic.inc"\n#include "PreparedCommunity.inc"'),
        ('        const auto source = !prepared.empty() ? prepared : patched.empty() ? original : std::string_view(patched);', '''        if (prepared.empty() && caNameSpaceName && xr_strcmp(caNameSpaceName, "_G") == 0 &&
            original.size() >= sizeof(stockCommunityScript) && original.size() <= 2 * sizeof(stockCommunityScript))
        {
            size_t at = 0;
            for (size_t i = 0; i < original.size(); ++i)
            {
                if (original[i] == '\\r' && i + 1 < original.size() && original[i + 1] == '\\n')
                    continue;
                if (at == sizeof(stockCommunityScript) || static_cast<unsigned char>(original[i]) != stockCommunityScript[at])
                {
                    at = 0;
                    break;
                }
                ++at;
            }
            if (at == sizeof(stockCommunityScript))
                prepared = {reinterpret_cast<const char*>(preparedCommunityScript), sizeof(preparedCommunityScript)};
        }
        const auto source = !prepared.empty() ? prepared : patched.empty() ? original : std::string_view(patched);'''),
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("fixtures", type=Path, nargs="?")
    args = parser.parse_args()
    patch(args.engine, args.fixtures)
