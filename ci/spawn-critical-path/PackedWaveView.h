#pragma once

#include <windows.h>
#include <cstdint>

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
}
