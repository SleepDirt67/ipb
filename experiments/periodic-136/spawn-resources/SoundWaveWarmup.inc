#ifdef IXR_WINDOWS
#include "SoundWaveMetadata.h"
#include <bcrypt.h>
#include <ppl.h>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

namespace
{
using SoundWavePreparation::Metadata;
using Digest = std::array<unsigned char, 32>;

struct PreparedSound
{
    Digest digest{};
    Metadata metadata;
};

bool AudioWarmupEnabled()
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_AUDIO_WARMUP");
        return !setting || std::strcmp(setting, "0") != 0;
    }();
    return enabled;
}

constexpr auto MaxWaveBytes = 512u * 1024;

struct Sha256Provider
{
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    ULONG objectBytes = 0;

    Sha256Provider()
    {
        if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0)
            return;
        ULONG received = 0;
        if (BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
            reinterpret_cast<PUCHAR>(&objectBytes), sizeof(objectBytes), &received, 0) < 0 ||
            received != sizeof(objectBytes))
            objectBytes = 0;
    }

    ~Sha256Provider()
    {
        if (algorithm)
            BCryptCloseAlgorithmProvider(algorithm, 0);
    }
};

bool FileDigest(IReader& reader, Digest& digest)
{
    if (!reader.length() || reader.length() > MaxWaveBytes)
        return false;

    static const Sha256Provider provider;
    if (!provider.objectBytes)
        return false;
    thread_local std::vector<unsigned char> work;
    work.resize(provider.objectBytes);
    BCRYPT_HASH_HANDLE hash = nullptr;
    if (BCryptCreateHash(provider.algorithm, &hash, work.data(), provider.objectBytes,
        nullptr, 0, 0) < 0)
        return false;

    const bool success = BCryptHashData(hash, static_cast<PUCHAR>(reader.pointer()),
        static_cast<ULONG>(reader.length()), 0) >= 0 &&
        BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    BCryptDestroyHash(hash);
    return success;
}

constexpr ov_callbacks MetadataCallbacks{ov_read_func, ov_seek_func, ov_close_func, ov_tell_func};

struct PreparedSounds
{
    std::shared_mutex lock;
    std::unordered_map<std::string, PreparedSound> entries;
};

PreparedSounds& WaveCache()
{
    static PreparedSounds cache;
    return cache;
}

std::vector<unsigned char> ReadSoundSnapshot(const char* path, const CLocatorAPI::file& file)
{
    if (file.vfs == u32(-1))
    {
        // Use the same loose override as CLocatorAPI, with nonfatal I/O.
        const HANDLE handle = Platform::OpenFile(file.wrap ? file.wrap : path);
        if (handle == INVALID_HANDLE_VALUE)
            return {};
        struct CloseFileHandle
        {
            HANDLE handle;
            ~CloseFileHandle() { CloseHandle(handle); }
        } close{handle};

        LARGE_INTEGER size;
        if (!GetFileSizeEx(handle, &size) || size.QuadPart <= 0 || size.QuadPart > MaxWaveBytes)
            return {};
        std::vector<unsigned char> bytes(static_cast<size_t>(size.QuadPart));
        DWORD read = 0;
        if (!ReadFile(handle, bytes.data(), static_cast<DWORD>(bytes.size()), &read, nullptr) ||
            read != bytes.size())
            return {};
        return bytes;
    }

    // A packed OGG usually has no second compression layer. An optional
    // warmup must not invoke the fatal archive reader for unsupported files.
    if (file.vfs >= FS.m_archives.size() || !file.size_real || file.size_real > MaxWaveBytes ||
        file.size_real != file.size_compressed || !FS.dwAllocGranularity)
        return {};
    const auto& archive = FS.m_archives[file.vfs];
    if (!archive.hSrcMap || std::uint64_t(file.ptr) + file.size_real > archive.size)
        return {};

    const DWORD offset = file.ptr % FS.dwAllocGranularity;
    auto* mapped = static_cast<const unsigned char*>(MapViewOfFile(
        archive.hSrcMap, FILE_MAP_READ, 0, file.ptr - offset, offset + file.size_real));
    if (!mapped)
        return {};
    struct Unmap
    {
        const void* address;
        ~Unmap() { UnmapViewOfFile(address); }
    } unmap{mapped};
    return {mapped + offset, mapped + offset + file.size_real};
}

struct WaveJob
{
    std::string path;
    std::vector<unsigned char> bytes;
    PreparedSound result;
    bool prepared = false;
};
}

void PrepareSpawnSoundMetadata()
{
    if (!AudioWarmupEnabled() || !SoundRender || !FS.path_exist("$game_sounds$") ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
        return;

    auto& cache = WaveCache();
    {
        std::shared_lock guard(cache.lock);
        if (!cache.entries.empty())
            return;
    }

    FS_FileSet files;
    FS.file_list(files, "$game_sounds$", FS_ListFiles, "*.ogg");
    std::vector<const FS_File*> ordered;
    ordered.reserve(files.size());
    for (const auto& file : files)
        if (file.size > 0 && file.size <= MaxWaveBytes)
            ordered.push_back(&file);
    auto priority = [](const FS_File* file)
    {
        const std::string_view name(file->name.c_str());
        if (name.starts_with("characters_voice\\") && !name.starts_with("characters_voice\\dialogs\\"))
            return 0;
        if (name.starts_with("monsters\\"))
            return 1;
        return 2;
    };
    std::stable_sort(ordered.begin(), ordered.end(), [&](auto* left, auto* right) {
        return priority(left) < priority(right);
    });

    decltype(cache.entries) prepared;
    std::vector<WaveJob> batch;
    batch.reserve(128);
    auto finishBatch = [&] {
        // The loading thread owns VFS and publication. Each worker sees
        // immutable bytes and its own libvorbis state.
        concurrency::parallel_for(size_t{0}, batch.size(), [&](size_t index) {
            auto& job = batch[index];
            IReader cursor(job.bytes.data(), job.bytes.size());
            job.prepared = FileDigest(cursor, job.result.digest) &&
                SoundWavePreparation::Prepare(&cursor, MetadataCallbacks,
                    OGG_COMMENT_VERSION, job.result.metadata);
        });
        for (auto& job : batch)
            if (job.prepared)
                prepared.emplace(std::move(job.path), job.result);
        batch.clear();
    };

    constexpr std::uint64_t maxBytes = 512ull * 1024 * 1024;
    std::uint64_t bytes = 0;
    size_t opened = 0;
    for (const auto* file : ordered)
    {
        if (bytes >= maxBytes || opened >= 24000)
            break;
        string_path path;
        FS.update_path(path, "$game_sounds$", file->name.c_str());
        const auto* entry = FS.exist(path);
        if (!entry)
            continue;
        auto snapshot = ReadSoundSnapshot(path, *entry);
        if (snapshot.empty() || bytes + snapshot.size() > maxBytes)
            continue;
        bytes += snapshot.size();
        ++opened;
        batch.push_back({path, std::move(snapshot)});
        if (batch.size() == batch.capacity())
            finishBatch();
    }
    if (!batch.empty())
        finishBatch();

    Msg("* sound metadata: prepared %zu of %zu opened OGG files (%llu MiB scanned)",
        prepared.size(), opened, static_cast<unsigned long long>(bytes >> 20));
    std::unique_lock guard(cache.lock);
    cache.entries.swap(prepared);
}

bool TryUsePreparedWave(IReader& reader, const char* path, Metadata& out)
{
    if (!AudioWarmupEnabled() ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
        return false;

    PreparedSound candidate;
    {
        auto& cache = WaveCache();
        std::shared_lock guard(cache.lock);
        const auto found = cache.entries.find(path);
        if (found == cache.entries.end())
            return false;
        candidate = found->second;
    }
    Digest digest;
    if (!FileDigest(reader, digest) || digest != candidate.digest)
        return false;
    out = candidate.metadata;
    return true;
}
#else
void PrepareSpawnSoundMetadata() {}
#endif
