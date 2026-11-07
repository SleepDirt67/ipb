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

replace('#include "SoundRangeDigest.h"', '#include "SoundRangeDigest.h"\n#include "../xrCore/PackedWaveView.h"\n#include <memory>')
replace('using SoundWavePreparation::SoundRangeDigest;', '''using SoundWavePreparation::SoundRangeDigest;
using SoundWavePreparation::PackedWaveView;''')
replace('    Digest digest{};\n};', '''    Digest digest{};
    std::weak_ptr<const PackedWaveView> packed;
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
replace('''        auto snapshot = ReadSoundSnapshot(path, *entry);
        if (snapshot.empty() || bytes + snapshot.size() > maxBytes)
            continue;
        bytes += snapshot.size();
        ++opened;
        batch.push_back({path, std::move(snapshot)});''', '''        WaveJob job;
        job.path = path;
        if (PackedWavePreparationEnabled() && entry->size_real <= MaxWaveBytes)
        {
            const auto view = FS.prepare_packed_wave_view(*entry);
            if (view)
            {
                if (const auto* source = view->Bytes(entry->ptr, entry->size_real))
                {
                    job.result.packed = view;
                    job.result.packedOffset = entry->ptr;
                    job.bytes.assign(source, source + entry->size_real);
                }
            }
        }
        if (job.bytes.empty())
            job.bytes = ReadSoundSnapshot(path, *entry);
        if (job.bytes.empty() || bytes + job.bytes.size() > maxBytes)
            continue;
        bytes += job.bytes.size();
        ++opened;
        batch.push_back(std::move(job));''')
replace('''    size_t exactEntries = 0, compactEntries = 0;''','''    size_t exactEntries = 0, compactEntries = 0, packedEntries = 0;''')
replace('''                ++compactEntries;
            prepared.emplace''','''                ++compactEntries;
            if (!job.result.packed.expired())
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
    if (const auto packed = entry.packed.lock())
    {
        const auto* resolved = FS.exist(path);
        if (resolved && resolved->vfs < FS.m_archives.size() &&
            resolved->ptr == entry.packedOffset && resolved->size_real == entry.fileSize &&
            resolved->size_compressed == entry.fileSize &&
            packed->MatchesSection(FS.m_archives[resolved->vfs].hSrcMap))
        {
            const auto* bytes = packed->Bytes(resolved->ptr, resolved->size_real);
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
core = root / "src/xrCore"
shutil.copyfile(bundle / "PackedWaveView.h", core / "PackedWaveView.h")
header = core / "LocatorAPI.h"
text = header.read_text(encoding="utf-8")
replace('#include "LocatorAPI_defs.h"', '''#include "LocatorAPI_defs.h"
#ifdef IXR_WINDOWS
#include <memory>
namespace SoundWavePreparation { class PackedWaveView; }
#endif''')
replace('    int sound_variant_count(LPCSTR prefix);', '''    int sound_variant_count(LPCSTR prefix);
#ifdef IXR_WINDOWS
    std::shared_ptr<const SoundWavePreparation::PackedWaveView> prepare_packed_wave_view(const file& entry);
#endif''')
header.write_text(text, encoding="utf-8", newline="\n")

source = core / "LocatorAPI.cpp"
text = source.read_text(encoding="utf-8")
replace('#include "xrAddons.h"', '''#include "xrAddons.h"
#ifdef IXR_WINDOWS
#include "PackedWaveView.h"

namespace
{
SoundWavePreparation::PackedWaveRegistry PackedSoundViews;
}

std::shared_ptr<const SoundWavePreparation::PackedWaveView>
CLocatorAPI::prepare_packed_wave_view(const file& entry)
{
    constexpr u32 windowBytes = 16u * 1024 * 1024;
    constexpr u32 maxSoundBytes = 512u * 1024;
    if (entry.vfs >= m_archives.size() || !entry.size_real || entry.size_real > maxSoundBytes ||
        entry.size_real != entry.size_compressed || !dwAllocGranularity || windowBytes % dwAllocGranularity)
        return {};

    const auto& archive = m_archives[entry.vfs];
    if (!archive.hSrcMap || u64(entry.ptr) + entry.size_real > archive.size)
        return {};
    const u32 start = (entry.ptr / windowBytes) * windowBytes;
    const u32 size = std::min(archive.size - start, windowBytes + maxSoundBytes);
    return PackedSoundViews.Prepare(archive.hSrcMap, start, size);
}
#endif''')
replace('#ifdef IXR_WINDOWS\n\tCloseHandle\t\t(hSrcMap);', '''#ifdef IXR_WINDOWS
    PackedSoundViews.CloseSection(hSrcMap);
\tCloseHandle\t\t(hSrcMap);''')
source.write_text(text, encoding="utf-8", newline="\n")
