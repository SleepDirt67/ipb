#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

void Require(bool ok)
{
    if (!ok)
    {
        std::fprintf(stderr, "Windows packed view check failed, error %lu\n", GetLastError());
        std::abort();
    }
}

int main()
{
    constexpr std::size_t archiveSize = 96u * 1024 * 1024;
    constexpr unsigned spawnCohortReads = 569 * 9;
    wchar_t directory[MAX_PATH], name[MAX_PATH];
    const auto length = GetTempPathW(MAX_PATH, directory);
    Require(length > 0 && length < MAX_PATH && GetTempFileNameW(directory, L"ixr", 0, name) != 0);
    auto file = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS,
        FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    Require(file != INVALID_HANDLE_VALUE);
    auto mapping = CreateFileMappingW(file, nullptr, PAGE_READWRITE, 0, archiveSize, nullptr);
    Require(mapping != nullptr);
    auto* write = static_cast<std::uint8_t*>(MapViewOfFile(mapping, FILE_MAP_WRITE, 0, 0, archiveSize));
    Require(write != nullptr);
    for (std::size_t i = 0; i < archiveSize; i += 4096)
        write[i] = static_cast<std::uint8_t>((i >> 12) ^ (i >> 20));
    Require(UnmapViewOfFile(write));

    unsigned unmaps = 0;
    const auto* mapped = MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, archiveSize);
    Require(mapped != nullptr);
    auto view = std::shared_ptr<const void>(mapped, [&](const void* bytes) {
        ++unmaps;
        Require(UnmapViewOfFile(bytes));
    });
    SYSTEM_INFO info{};
    GetSystemInfo(&info);
    const auto granularity = info.dwAllocationGranularity;

    const auto sample = [](const std::uint8_t* bytes, std::size_t length) {
        unsigned checksum = 0;
        for (std::size_t page = 0; page < length; page += 4096)
            checksum += bytes[page];
        return checksum;
    };
    const auto run = [&](bool reuse) {
        unsigned checksum = 0;
        for (unsigned i = 0; i < spawnCohortReads; ++i)
        {
            const std::size_t bytes = (1 + (i * 13) % 16) * 4096;
            const std::size_t offset = ((std::uint64_t(i) * 2654435761u) % ((archiveSize - bytes) >> 12)) << 12;
            if (reuse)
            {
                const auto readerOwner = view;
                checksum += sample(static_cast<const std::uint8_t*>(readerOwner.get()) + offset, bytes);
            }
            else
            {
                const auto first = offset - offset % granularity;
                const auto delta = offset - first;
                const auto* reader = static_cast<const std::uint8_t*>(
                    MapViewOfFile(mapping, FILE_MAP_READ, 0, static_cast<DWORD>(first), delta + bytes));
                Require(reader != nullptr);
                checksum += sample(reader + delta, bytes);
                Require(UnmapViewOfFile(reader));
            }
        }
        return checksum;
    };

    Require(run(false) == run(true));
    std::vector<double> times[2];
    for (unsigned trial = 0; trial < 9; ++trial)
    {
        for (unsigned order = 0; order < 2; ++order)
        {
            const auto variant = (trial + order) % 2;
            const auto start = std::chrono::steady_clock::now();
            const auto checksum = run(variant != 0);
            times[variant].push_back(std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - start).count());
            Require(checksum != 0);
        }
    }
    for (auto& values : times)
        std::sort(values.begin(), values.end());
    std::printf("Packed Windows mapping fixture, %u slices: %.3f ms per-file / %.3f ms shared\n",
        spawnCohortReads, times[0][4], times[1][4]);

    // A live reader pins its view even after the archive closes.
    auto reader = view;
    view.reset();
    Require(CloseHandle(mapping) && CloseHandle(file) && unmaps == 0);
    const auto* bytes = static_cast<const std::uint8_t*>(reader.get());
    Require(bytes[4096] == 1 && bytes[8192] == 2);
    reader.reset();
    Require(unmaps == 1);
    std::puts("PASS: same bytes at every slice; live reader survives archive close; view unmapped once");
}
