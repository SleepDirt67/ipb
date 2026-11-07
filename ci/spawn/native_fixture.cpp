#include "xrCore.h"
#include "SpawnSwitchKeys.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace
{
void require(bool value)
{
    if (!value)
        std::abort();
}
}

int main()
{
    Memory._initialize();
    const char text[] = "[base]\non_info10 = one\non_timer = 3\nother = walk\n"
                        "[logic]:base\non_info = 1\non_info2 = 2\non_infox = wrong\n"
                        "on_actor_dist_ge = 5\non_actor_dist_ge_nvis = 5\n"
                        "on_actor_dist_ge_nvis2 = 2\non_signal9 = test\n";
    IReader input(const_cast<char*>(text), std::strlen(text));
    CInifile ini(&input);
    const auto& rows = ini.r_section("logic").Data;
    const auto end = static_cast<int>(rows.size());
    for (std::string_view key : {"on_info", "on_timer", "on_actor_dist_ge",
                                 "on_actor_dist_ge_nvis", "on_signal", "on_npc_in_zone"})
    {
        std::vector<int> reference;
        for (int line = 0; line < end; ++line)
        {
            const char* name = nullptr;
            const char* value = nullptr;
            require(ini.r_line("logic", line, &name, &value));
            const std::string_view entry(name);
            if (entry.starts_with(key))
            {
                const auto suffix = entry.substr(key.size());
                if (suffix.find_first_not_of("0123456789") == std::string_view::npos)
                    reference.push_back(line);
            }
        }
        std::vector<int> selected;
        int line = 0;
        while ((line = NextSpawnSwitchKey(rows, key, line, end)) >= 0)
        {
            selected.push_back(line);
            ++line;
        }
        require(line == -1 && reference == selected);
    }
    require(NextSpawnSwitchKey(rows, "on_info", 0, end + 1) == -2);
    require(NextSpawnSwitchKey(rows, "on_info", -1, end) == -2);
    std::puts("PASS: real xrCore inherited section, native prefix cursor preserves line order and fallback");
}
