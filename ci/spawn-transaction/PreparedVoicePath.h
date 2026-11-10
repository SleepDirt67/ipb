#pragma once

#include <cstring>
#include <string>
#include <string_view>

namespace SpawnVoice
{
// A query owns its spelling and may keep the entry only while the same
// immutable VFS snapshot is admitted at the point of use.
class PreparedVoicePath
{
    char base_[256]{};
    const Catalogue::Entry* entry_ = nullptr;
    bool nativeSpelling_ = false;

public:
    bool Prepare(const Catalogue& snapshot, const char* prefix, std::string_view path)
    {
        if (!prefix)
            return false;
        const auto prefixSize = std::strlen(prefix);
        if (path.empty() || path.size() > 240 || prefixSize > 240 - path.size())
            return false;
        const auto size = prefixSize + path.size();
        if (!snapshot.Accepts(size))
            return false;
        std::memcpy(base_, prefix, prefixSize);
        std::memcpy(base_ + prefixSize, path.data(), path.size());
        base_[size] = '\0';
        char normalized[sizeof(base_)];
        std::memcpy(normalized, base_, size + 1);
        xr_strlwr(normalized);
        const std::string_view key(normalized, size);
        if (!key.starts_with("characters_voice\\"))
            return false;
        nativeSpelling_ = std::memcmp(base_, normalized, size) == 0;
        entry_ = snapshot.Find(key);
        return true;
    }

    bool SamePrefix(const char* prefix, size_t pathSize) const
    {
        // The existing commit path retains its original prefix if it
        // became null during registration.
        if (!prefix)
            return true;
        const auto size = std::strlen(prefix);
        return size + pathSize == std::strlen(base_) && std::memcmp(base_, prefix, size) == 0;
    }

    std::string_view Base() const { return base_; }
    int Count() const { return entry_ ? entry_->Count() : 0; }

    const std::vector<std::string_view>* Paths() const
    {
        return nativeSpelling_ && entry_ && !entry_->single ? &entry_->paths : nullptr;
    }
};
}
