"""Prepare reusable live archive windows for the NPC sound source path."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundle = Path(__file__).resolve().parent
path = root / "src/xrSound/SoundRender_Source_loader.cpp"
text = path.read_text(encoding="utf-8")

def replace(before, after):
    global text
    if text.count(before) != 1:
        raise ValueError((before[:90], text.count(before)))
    text = text.replace(before, after, 1)

replace('#include "SoundRangeDigest.h"', '#include "SoundRangeDigest.h"\n#include "PackedWaveView.h"\n#include <memory>')
replace('using SoundWavePreparation::SoundRangeDigest;', '''using SoundWavePreparation::SoundRangeDigest;
using SoundWavePreparation::PackedWaveView;''')
replace('    Digest digest{};\n};', '''    Digest digest{};
    std::shared_ptr<const PackedWaveView> packed;
    u32 packedOffset = 0;
};''')
replace('constexpr auto MaxWaveBytes', '''bool PackedWavePreparationEnabled()
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_PACKED_SOUND_PREPARATION");
        return !setting || std::strcmp(setting, "0") != 0;
    }();
    return enabled;
}

constexpr auto MaxWaveBytes''')
replace('struct WaveJob\n{', '''// Both the original reader and a retained view address the same live
// section. Keeping a duplicate distinguishes an unmounted/reopened archive,
// including a recycled numeric handle. The normal content check still runs.
class PackedWaveWindows
{
    static constexpr u32 windowBytes = 16u * 1024 * 1024;
    static constexpr size_t maxWindows = 32;
    std::unordered_map<u64, std::shared_ptr<PackedWaveView>> windows_;

public:
    std::shared_ptr<const PackedWaveView> Prepare(const CLocatorAPI::file& file)
    {
        if (!PackedWavePreparationEnabled() || file.vfs >= FS.m_archives.size() ||
            !file.size_real || file.size_real != file.size_compressed ||
            !FS.dwAllocGranularity || windowBytes % FS.dwAllocGranularity)
            return {};

        const auto& archive = FS.m_archives[file.vfs];
        if (!archive.hSrcMap || u64(file.ptr) + file.size_real > archive.size)
            return {};
        const u32 start = (file.ptr / windowBytes) * windowBytes;
        const u64 key = (u64(file.vfs) << 32) | start;
        auto found = windows_.find(key);
        if (found == windows_.end())
        {
            if (windows_.size() >= maxWindows)
                return {};
            auto view = std::make_shared<PackedWaveView>();
            const u32 size = std::min(archive.size - start, windowBytes + MaxWaveBytes);
            if (!view->Open(archive.hSrcMap, start, size))
                return {};
            found = windows_.emplace(key, std::move(view)).first;
        }
        return found->second->MatchesSection(archive.hSrcMap) &&
            found->second->Bytes(file.ptr, file.size_real) ? found->second : nullptr;
    }
};

struct WaveJob
{''')
replace('    size_t opened = 0;\n    for (const auto* file', '''    size_t opened = 0;
    size_t packedEntries = 0;
    PackedWaveWindows packedWindows;
    for (const auto* file''')
replace('''        auto snapshot = ReadSoundSnapshot(path, *entry);
        if (snapshot.empty() || bytes + snapshot.size() > maxBytes)
            continue;
        bytes += snapshot.size();
        ++opened;
        batch.push_back({path, std::move(snapshot)});''', '''        WaveJob job;
        job.path = path;
        job.result.packed = packedWindows.Prepare(*entry);
        if (job.result.packed)
        {
            const auto* source = job.result.packed->Bytes(entry->ptr, entry->size_real);
            job.result.packedOffset = entry->ptr;
            job.bytes.assign(source, source + entry->size_real);
        }
        else
            job.bytes = ReadSoundSnapshot(path, *entry);
        if (job.bytes.empty() || bytes + job.bytes.size() > maxBytes)
            continue;
        bytes += job.bytes.size();
        ++opened;
        batch.push_back(std::move(job));''')
replace('''    size_t exactEntries = 0, compactEntries = 0;''','''    size_t exactEntries = 0, compactEntries = 0, packedEntries = 0;''')
replace('''    size_t opened = 0;
    size_t packedEntries = 0;''','''    size_t opened = 0;''')
replace('''                ++compactEntries;
            prepared.emplace''','''                ++compactEntries;
            if (job.result.packed)
                ++packedEntries;
            prepared.emplace''')
replace('''%zu exact, %zu compact, %llu MiB scanned, %zu MiB exact bytes)",
        prepared.size(), opened, exactEntries, compactEntries,''','''%zu exact, %zu compact, %zu with packed views, %llu MiB scanned, %zu MiB exact bytes)",
        prepared.size(), opened, exactEntries, compactEntries, packedEntries,''')
replace('''bool TryUsePreparedWave(IReader& reader, const char* path, Metadata& out)
{
    if (!AudioWarmupEnabled() ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
        return false;

    auto& cache = WaveCache();
    std::shared_lock guard(cache.lock);
    const auto found = cache.entries.find(path);
    if (found == cache.entries.end())
        return false;
    const auto& entry = found->second;''','''bool ReadPreparedMetadata(const PreparedSound& entry, const void* bytes, size_t size, Metadata& out)
{''')
replace('entry.witness.Matches(reader.pointer(), reader.length())','entry.witness.Matches(bytes, size)')
replace('HashPreparedWave(entry, reader.pointer(), reader.length(), current)','HashPreparedWave(entry, bytes, size, current)')
replace('''    out = entry.metadata;
    return true;
}
#else''','''    out = entry.metadata;
    return true;
}

bool TryUsePreparedWave(const char* path, Metadata& out, IReader*& reader)
{
    if (!AudioWarmupEnabled() ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
        return false;

    auto& cache = WaveCache();
    std::shared_lock guard(cache.lock);
    const auto found = cache.entries.find(path);
    if (found == cache.entries.end())
        return false;
    const auto& entry = found->second;
    if (entry.packed)
    {
        const auto* resolved = FS.exist(path);
        if (resolved && resolved->vfs < FS.m_archives.size() &&
            resolved->ptr == entry.packedOffset && resolved->size_real == entry.fileSize &&
            resolved->size_compressed == entry.fileSize &&
            entry.packed->MatchesSection(FS.m_archives[resolved->vfs].hSrcMap))
        {
            const auto* bytes = entry.packed->Bytes(resolved->ptr, resolved->size_real);
            if (bytes && ReadPreparedMetadata(entry, bytes, resolved->size_real, out))
            {
                ++FS.dwOpenCounter;
                return true;
            }
        }
    }
    reader = FS.r_open(path);
    R_ASSERT3(reader && reader->length(), "Can't open wave file:", path);
    return ReadPreparedMetadata(entry, reader->pointer(), reader->length(), out);
}
#else''')
replace('''\t// Load file into memory and parse WAV-format
\tm_wave\t\t\t\t\t= FS.r_open(pname.c_str());
\tR_ASSERT3\t\t\t\t(m_wave && m_wave->length(),"Can't open wave file:",pname.c_str());

#ifdef IXR_WINDOWS
    Metadata prepared;
    if (TryUsePreparedWave(*m_wave, pname.c_str(), prepared))''','''    m_wave = nullptr;
#ifdef IXR_WINDOWS
    Metadata prepared;
    if (TryUsePreparedWave(pname.c_str(), prepared, m_wave))''')
replace('''        FS.r_close(m_wave);
        return;
    }
#endif

\tov_callbacks''','''        if (m_wave)
            FS.r_close(m_wave);
        return;
    }
#endif
    if (!m_wave)
        m_wave = FS.r_open(pname.c_str());
    R_ASSERT3(m_wave && m_wave->length(), "Can't open wave file:", pname.c_str());

\tov_callbacks''')
path.write_text(text, encoding="utf-8", newline="\n")
shutil.copyfile(bundle / "PackedWaveView.h", root / "src/xrSound/PackedWaveView.h")
