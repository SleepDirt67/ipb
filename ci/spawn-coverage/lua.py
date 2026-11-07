"""Guard the rewritten functions individually so unrelated script edits survive."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundle = Path(__file__).resolve().parent
sys.path.insert(0, str(bundle.parent / "spawn-preparation"))
from voice import rewrite

script = root / "gamedata/scripts/sound_theme.script"
stock = script.read_bytes().replace(b"\r\n", b"\n")
first = b"function npc_sound:init_npc(npc)"
last = b"function npc_sound:callback"
batched = rewrite(stock)
old = stock[stock.index(first):stock.index(last)].rstrip()
new = batched[batched.index(b"local stock_getFS"):batched.index(last)].rstrip()
new = new.replace(b'        native = debug ~= nil and debug.getinfo(method, "S").what == "C"',
                  b'''        local info = type(debug) == "table" and rawget(debug, "getinfo")
        if type(info) ~= "function" then return false end
        local ok, details = pcall(info, method, "S")
        native = ok and type(details) == "table" and details.what == "C"''')
new = b"do\n" + new + b"\nend"
out = root / "src/xrScripts/StockVoiceScript.inc"
def array(name, data):
    lines = [", ".join(str(x) for x in data[i:i+32]) for i in range(0, len(data), 32)]
    return f"static constexpr unsigned char {name}[] = {{\n" + ",\n".join(lines) + "\n};\n"
out.write_text(array("stockVoiceFunction", old) + array("batchedVoiceFunction", new), encoding="ascii")
shutil.copyfile(bundle / "LuaSourceFragment.h", root / "src/xrScripts/LuaSourceFragment.h")

path = root / "src/xrScripts/script_storage.cpp"
text = path.read_text(encoding="utf-8")
header = '#include "PreparedStockLogic.inc"'
assert text.count('#include <string_view>') == 1 and text.count(header) == 1
text = text.replace('#include <string_view>', '#include <string_view>\n#include <string>\n#include "LuaSourceFragment.h"')
first = text.index("std::string_view PrepareStockVoice")
last = text.index("std::string_view PrepareStockLogic", first)
text = text[:first] + '''template<size_t Size>
std::string_view Source(const unsigned char (&bytes)[Size])
{
    return {reinterpret_cast<const char*>(bytes), Size};
}

std::string PrepareStockVoice(std::string_view data)
{
    const auto match = SpawnLuaSource::FindUnique(data, Source(stockVoiceFunction));
    if (!match)
        return {};
    std::string patched(data);
    patched.replace(match->start, match->length, Source(batchedVoiceFunction));
    return patched;
}

bool SpawnPlansEnabled()
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_SPAWN_PLANS");
        return !setting || xr_strcmp(setting, "0") != 0;
    }();
    return enabled;
}

std::string PrepareCompatibleLogic(std::string_view data)
{
    if (!SpawnPlansEnabled())
        return {};
    constexpr std::string_view start = "function abort_syntax_error_in_cond";
    constexpr std::string_view parse = "function parse_condlist(npc, section, field, src)";
    constexpr std::string_view end = "\\n\\treturn lst\\nend";
    const auto stock = Source(stockLogic);
    const auto prepared = Source(preparedStockLogic);
    const auto parseStock = stock.find("function parse_condlist(npc, section, field, src)\\n\\tlocal lst = {}");
    const auto tables = prepared.find("local compiled_conditions = {}");
    if (parseStock == stock.npos || tables == prepared.npos)
        return {};
    const auto startStock = stock.rfind(start, parseStock);
    const auto endStock = stock.find(end, parseStock);
    const auto startPrepared = prepared.rfind(start, tables);
    const auto endPrepared = prepared.find(end, prepared.find(parse, tables));
    if (startStock == stock.npos || endStock == stock.npos || startPrepared == prepared.npos ||
        endPrepared == prepared.npos)
        return {};

    const auto match = SpawnLuaSource::FindUnique(data, stock.substr(startStock, endStock + end.size() - startStock));
    if (!match)
        return {};

    std::string replacement(prepared.substr(startPrepared, tables - startPrepared));
    replacement += R"lua(do
local function ixray_native_condition_helper(fn)
    local info = type(debug) == "table" and rawget(debug, "getinfo")
    if type(info) ~= "function" or type(fn) ~= "function" then return false end
    local ok, details = pcall(info, fn, "S")
    return ok and type(details) == "table" and details.what == "C"
end
local ixray_condition_primitives =
    ixray_native_condition_helper(string.find) and ixray_native_condition_helper(string.sub)
    and ixray_native_condition_helper(string.len) and ixray_native_condition_helper(string.gfind)
    and ixray_native_condition_helper(tonumber) and ixray_native_condition_helper(table.insert)
)lua";
    std::string parser(prepared.substr(tables, endPrepared + end.size() - tables));
    const auto predicate = parser.find("if prepared and parse_infop");
    if (predicate == parser.npos)
        return {};
    parser.replace(predicate, 16, "if prepared and ixray_condition_primitives and ");
    replacement += parser;
    replacement += "\\nend";
    std::string patched(data);
    patched.replace(match->start, match->length, replacement);
    return patched;
}

''' + text[last:]
text = text.replace('''    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_SPAWN_PLANS");
        return !setting || xr_strcmp(setting, "0") != 0;
    }();
    if (!enabled || data.size()''', '''    if (!SpawnPlansEnabled() || data.size()''')
old = '''        auto prepared = PrepareStockLogic(caNameSpaceName, original);
        if (!prepared.empty())
            Msg("* xr_logic: prepared stock condition programs");
        else
        {
            prepared = PrepareStockVoice(caNameSpaceName, original);
            if (!prepared.empty())
                Msg("* sound_theme: batched stock voice discovery");
        }
        const auto source = prepared.empty() ? original : prepared;'''
new = '''        auto prepared = PrepareStockLogic(caNameSpaceName, original);
        std::string patched;
        if (!prepared.empty())
            Msg("* xr_logic: prepared stock condition programs");
        else if (caNameSpaceName && xr_strcmp(caNameSpaceName, "xr_logic") == 0 && SpawnPlansEnabled())
        {
            patched = PrepareCompatibleLogic(original);
            Msg("* xr_logic: %s", patched.empty() ? "unrecognised condition parser" : "prepared matching condition parser");
        }
        else if (caNameSpaceName && xr_strcmp(caNameSpaceName, "sound_theme") == 0)
        {
            patched = PrepareStockVoice(original);
            Msg("* sound_theme: %s", patched.empty() ? "unrecognised NPC voice function" : "batched matching NPC voice function");
        }
        const auto source = !prepared.empty() ? prepared : patched.empty() ? original : std::string_view(patched);'''
assert text.count(old) == 1
path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
