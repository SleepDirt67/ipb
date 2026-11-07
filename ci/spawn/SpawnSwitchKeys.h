#pragma once
#include <algorithm>
#include <string_view>

// CInifile keeps ordered keys. The caller resumes by the original line
// index after each Lua callback and can hand unusual keys back to Lua.
template <typename Items>
int NextSpawnSwitchKey(const Items& entries, std::string_view prefix, int start, int end)
{
    if (start < 0 || end < start || static_cast<size_t>(end) > entries.size())
        return -2;
    const auto last = entries.begin() + end;
    auto found = std::lower_bound(entries.begin() + start, last, prefix,
        [](const auto& item, std::string_view key) {
            return item.first.c_str() ? std::string_view(item.first.c_str()) < key : true;
        });
    for (; found != last; ++found)
    {
        const char* key = found->first.c_str();
        if (!key || !std::string_view(key).starts_with(prefix))
            break;

        const std::string_view suffix(key + prefix.size());
        if (std::any_of(suffix.begin(), suffix.end(), [](unsigned char c) { return c >= 128; }))
            return -2;
        if (std::all_of(suffix.begin(), suffix.end(), [](char c) { return c >= '0' && c <= '9'; }))
            return static_cast<int>(found - entries.begin());
    }
    return -1;
}
