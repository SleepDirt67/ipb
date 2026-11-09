#include "xrCore.h"
#include "rt_compressor.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

namespace
{
void Require(bool pass, const char* message)
{
    if (!pass)
    {
        std::fprintf(stderr, "Failed: %s\n", message);
        std::abort();
    }
}
struct File
{
    std::string name;
    std::vector<u8> contents;
    std::vector<u8> packed;
    u32 offset;
};
}

int main(int argc, char** argv)
{
    Require(argc == 2, "specify shared or original archive path");
    const bool expectShared = std::string_view(argv[1]) == "shared";
    const auto root = std::filesystem::absolute("ixray-packed-replay");
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto directory = root.string();
    Core._initialize("ixray-packed-replay", nullptr, FALSE, nullptr);
    FS._initialize(CLocatorAPI::flTargetFolderOnly, directory.c_str(), nullptr);

    CMemoryWriter archive, index;
    std::vector<File> files;
    constexpr unsigned count = 569;
    archive.open_chunk(0);
    for (unsigned i = 0; i < count; ++i)
    {
        auto& file = files.emplace_back();
        file.name = "data-" + std::to_string(i) + ".ogg";
        file.contents.resize((1 + i % 7) * 2048);
        for (std::size_t j = 0; j < file.contents.size(); ++j)
            file.contents[j] = static_cast<u8>((i * 7 + j / 32) % 29);

        if (i % 5 == 0)
        {
            const auto length = static_cast<u32>(file.contents.size());
            file.packed.resize(rtc_csize(length));
            const auto bytes = rtc_compress(file.packed.data(), static_cast<u32>(file.packed.size()),
                file.contents.data(), length);
            Require(bytes != 0 && bytes < length, "synthetic resource is compressed");
            file.packed.resize(bytes);
        }
        else
            file.packed = file.contents;

        file.offset = static_cast<u32>(archive.tell());
        archive.w(file.packed.data(), static_cast<u32>(file.packed.size()));
        index.w_u16(static_cast<u16>(4 * sizeof(u32) + file.name.size()));
        index.w_u32(static_cast<u32>(file.contents.size()));
        index.w_u32(static_cast<u32>(file.packed.size()));
        index.w_u32(0);
        index.w(file.name.data(), static_cast<u32>(file.name.size()));
        index.w_u32(file.offset);
    }
    archive.close_chunk();
    archive.w_chunk(1, index.pointer(), index.size());
    const auto db = (root / "replay.xdb").string();
    Require(archive.save_to(db.c_str()), "write valid archive");
    auto& mounted = FS.m_archives.emplace_back();
    mounted.path = db.c_str();
    mounted.vfs_idx = static_cast<u32>(FS.m_archives.size() - 1);
    const auto prefix = directory + "\\";
    FS.LoadArchive(mounted, prefix.c_str());
    Require(static_cast<bool>(FS.acquire_archive_view(mounted)) == expectShared, "selected mapping path");

    auto verify = [&] {
        for (const auto& file : files)
        {
            const auto path = prefix + file.name;
            auto* reader = FS.r_open(path.c_str());
            Require(reader != nullptr && reader->length() == static_cast<intptr_t>(file.contents.size()), "asset reader size");
            Require(std::memcmp(reader->pointer(), file.contents.data(), file.contents.size()) == 0, "asset bytes");
            reader->advance(32);
            Require(reader->r_u8() == file.contents[32], "independent reader cursor");
            FS.r_close(reader);
        }
    };
    verify();
    std::vector<double> samples;
    for (unsigned i = 0; i < 11; ++i)
    {
        const auto start = std::chrono::steady_clock::now();
        for (unsigned actor = 0; actor < 9; ++actor)
            verify();
        samples.push_back(std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - start).count());
    }
    std::sort(samples.begin(), samples.end());
    std::printf("xrCore mixed packed readers for 9 x %u resources, %s: %.3f ms\n",
        count, expectShared ? "shared" : "original", samples[samples.size() / 2]);

    const auto& retained = files[1];
    const auto path = prefix + retained.name;
    auto* reader = FS.r_open(path.c_str());
    Require(reader && reader->length() == static_cast<intptr_t>(retained.contents.size()), "pin uncompressed asset");
    FS._destroy();
    Require(std::memcmp(reader->pointer(), retained.contents.data(), retained.contents.size()) == 0,
        "in-flight reader survives locator teardown");
    FS.r_close(reader);
    Core._destroy();
    std::filesystem::remove_all(root);
    std::puts("PASS: compressed and uncompressed asset bytes, cursor isolation, shutdown ownership");
}
