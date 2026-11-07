#pragma once

#include <windows.h>
#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>

namespace SoundWavePreparation
{
class PackedWaveView
{
    HANDLE section_ = nullptr;
    const unsigned char* view_ = nullptr;
    std::uint32_t offset_ = 0;
    std::uint32_t size_ = 0;

public:
    PackedWaveView() = default;
    PackedWaveView(const PackedWaveView&) = delete;
    PackedWaveView& operator=(const PackedWaveView&) = delete;

    ~PackedWaveView()
    {
        if (view_)
            UnmapViewOfFile(view_);
        if (section_)
            CloseHandle(section_);
    }

    bool Open(HANDLE section, std::uint32_t offset, std::uint32_t size)
    {
        if (!section || !size || section_)
            return false;
        const HANDLE process = GetCurrentProcess();
        if (!DuplicateHandle(process, section, process, &section_, 0, FALSE, DUPLICATE_SAME_ACCESS))
            return false;
        view_ = static_cast<const unsigned char*>(MapViewOfFile(section_, FILE_MAP_READ, 0, offset, size));
        if (!view_)
            return false;
        offset_ = offset;
        size_ = size;
        return true;
    }

    const unsigned char* Bytes(std::uint32_t offset, std::uint32_t size) const
    {
        if (!view_ || offset < offset_ || size > size_ || offset - offset_ > size_ - size)
            return nullptr;
        return view_ + (offset - offset_);
    }

    bool MatchesSection(HANDLE section) const
    {
        using Compare = BOOL(WINAPI*)(HANDLE, HANDLE);
        static const auto compare = reinterpret_cast<Compare>(
            GetProcAddress(GetModuleHandleW(L"kernelbase.dll"), "CompareObjectHandles"));
        return section && compare && compare(section_, section);
    }
};

class PackedWaveRegistry
{
    std::mutex mutex_;
    std::unordered_map<HANDLE, std::unordered_map<std::uint32_t, std::shared_ptr<PackedWaveView>>> sections_;
    std::size_t count_ = 0;

public:
    std::shared_ptr<const PackedWaveView> Prepare(HANDLE section, std::uint32_t offset, std::uint32_t size)
    {
        std::lock_guard guard(mutex_);
        auto existing = sections_.find(section);
        if (existing != sections_.end())
        {
            auto found = existing->second.find(offset);
            if (found != existing->second.end())
                return found->second;
        }
        constexpr std::size_t maxWindows = 32;
        if (count_ >= maxWindows)
            return {};
        auto view = std::make_shared<PackedWaveView>();
        if (!view->Open(section, offset, size))
            return {};
        sections_[section].emplace(offset, view);
        ++count_;
        return view;
    }

    void CloseSection(HANDLE section)
    {
        std::lock_guard guard(mutex_);
        const auto found = sections_.find(section);
        if (found == sections_.end())
            return;
        count_ -= found->second.size();
        sections_.erase(found);
    }
};
}
