#include "LuaSourceFragment.h"

#include <cstdlib>
#include <iostream>
#include <string_view>

static void require(bool value)
{
    if (!value)
        std::abort();
}

int main()
{
    using SpawnLuaSource::FindUnique;
    constexpr std::string_view expected = "function voice:init() local x = 'keep -- text' .. name return x end";
    constexpr std::string_view layout = "local marker = [=[function voice:init() end]=]\r\n"
        "--[==[ function voice:init() local x = 'keep -- text' .. name return x end ]==]\r\n"
        "function\tvoice : init ( ) -- comment\r\n"
        "local x='keep -- text' .. name return x end\r\nreturn marker";
    const auto match = FindUnique(layout, expected);
    require(match.has_value() && layout.substr(match->start, 14) == "function\tvoice");
    require(!FindUnique("local function f() return 1 end", "function f() return 1 end"));
    require(!FindUnique("function f() return 1e - 2 end", "function f() return 1e-2 end"));
    require(!FindUnique("function f() return x . . y end", "function f() return x .. y end"));
    require(!FindUnique("function f() return 'bad' end", "function f() return 'keep' end"));
    require(!FindUnique("function f() return 1 end\nfunction f() return 1 end", "function f() return 1 end"));
    require(!FindUnique("--[[unfinished", expected));
    require(!FindUnique("local s = 'unterminated", expected));
    std::cout << "PASS: guarded Lua function match, comments, CRLF, strings, edits and ambiguity\n";
}
