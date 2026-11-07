#pragma once

#include <algorithm>
#include <charconv>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace SpawnVoice
{
class Catalogue
{
    struct Entry
    {
        bool single = false;
        unsigned consecutive = 0;
        std::vector<unsigned> numbered;
    };

    struct StringHash
    {
        using is_transparent = void;
        size_t operator()(std::string_view text) const { return std::hash<std::string_view>{}(text); }
    };
    std::unordered_map<std::string, Entry, StringHash, std::equal_to<>> entries_;

public:
    void Add(std::string_view name)
    {
        constexpr std::string_view extension = ".ogg";
        if (!name.ends_with(extension))
            return;
        name.remove_suffix(extension.size());
        entries_[std::string(name)].single = true;
        const auto end = name.data() + name.size();
        for (auto start = end; start != name.data();)
        {
            --start;
            if (*start < '0' || *start > '9')
                break;
            if (*start == '0' && end - start > 1)
                continue;
            unsigned number = 0;
            const auto result = std::from_chars(start, end, number);
            if (result.ec != std::errc{})
                break;
            entries_[std::string(name.data(), start)].numbered.push_back(number);
        }
    }

    void Finish()
    {
        for (auto& pair : entries_)
        {
            auto& entry = pair.second;
            auto& numbers = entry.numbered;
            std::sort(numbers.begin(), numbers.end());
            numbers.erase(std::unique(numbers.begin(), numbers.end()), numbers.end());
            unsigned next = 1;
            for (const auto number : numbers)
            {
                if (number == 0)
                    continue;
                if (number != next)
                    break;
                ++next;
            }
            entry.consecutive = next - 1;
        }
    }

    // -1 denotes the unnumbered file. Other results are the consecutive
    // run starting at one, as observed by the original Lua loop.
    int Count(std::string_view base) const
    {
        const auto found = entries_.find(base);
        if (found == entries_.end())
            return 0;
        return found->second.single ? -1 : static_cast<int>(found->second.consecutive);
    }

    template<class Output>
    void CopyNumbered(std::string_view base, unsigned limit, Output& output) const
    {
        const auto found = entries_.find(base);
        if (found == entries_.end())
            return;
        const auto& numbers = found->second.numbered;
        output.assign(numbers.begin(), std::lower_bound(numbers.begin(), numbers.end(), limit));
    }
};
}
