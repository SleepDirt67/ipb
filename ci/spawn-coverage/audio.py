"""Keep prepared metadata after the exact audio witness byte budget fills."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundle = Path(__file__).resolve().parent


def edit(path, replacements):
    target = root / path
    data = target.read_bytes()
    text = data.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if text.count(before) != 1:
            raise ValueError((path, before[:80], text.count(before)))
        text = text.replace(before, after, 1)
    if b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""):
        text = text.replace("\n", "\r\n")
    target.write_bytes(text.encode("latin-1"))


witness_edits = [
    ("""    bool Matches(const void* bytes, size_t size) const
    {
        if (size != size_ || ranges_.empty())""", """    bool Matches(const void* bytes, size_t size) const
    {
        if (size != size_ || bytes_.empty())"""),
    ('    size_t ByteCount() const { return bytes_.size(); }',
     '''    template<class Visit>
    bool VisitRanges(const void* bytes, size_t size, Visit&& visit) const
    {
        if (size != size_ || ranges_.empty())
            return false;
        const auto* data = static_cast<const unsigned char*>(bytes);
        for (const auto& range : ranges_)
            if (!visit(data + range.first, range.last - range.first))
                return false;
        return true;
    }

    void ReleaseExactBytes() { std::vector<unsigned char>().swap(bytes_); }
    size_t ByteCount() const { return bytes_.size(); }'''),
]
edit("src/xrSound/SoundWaveReadWitness.h", witness_edits)
edit("src/xrSound/SoundRender_Source_loader.cpp", [
    ('#include "SoundWaveReadWitness.h"', '#include "SoundWaveReadWitness.h"\n#include "SoundRangeDigest.h"'),
    ('using SoundWavePreparation::ReadWitness;', '''using SoundWavePreparation::ReadWitness;
using SoundWavePreparation::Digest;
using SoundWavePreparation::SoundRangeDigest;'''),
    ('''    Metadata metadata;
};''', '''    Metadata metadata;
    enum class Verification { Exact, Ranges, Full };
    Verification verification = Verification::Full;
    size_t fileSize = 0;
    Digest digest{};
};

bool HashPreparedWave(const PreparedSound& entry, const void* bytes, size_t size, Digest& digest)
{
    if (size != entry.fileSize)
        return false;
    return SoundRangeDigest::Compute([&](const auto& add) {
        return entry.verification == PreparedSound::Verification::Ranges ?
            entry.witness.VisitRanges(bytes, size, add) : add(bytes, size);
    }, digest);
}'''),
    ('''    size_t witnessBytes = 0;''', '''    size_t witnessBytes = 0;
    size_t exactEntries = 0, compactEntries = 0;'''),
    ('''            job.prepared = job.result.witness.PrepareFrom(&cursor, MetadataCallbacks,
                job.bytes.data(), job.bytes.size(), OGG_COMMENT_VERSION, job.result.metadata);''',
     '''            job.result.fileSize = job.bytes.size();
            job.prepared = job.result.witness.PrepareFrom(&cursor, MetadataCallbacks,
                job.bytes.data(), job.bytes.size(), OGG_COMMENT_VERSION, job.result.metadata);
            if (job.prepared)
                job.result.verification = PreparedSound::Verification::Ranges;
            else
            {
                cursor.seek(0);
                job.prepared = SoundWavePreparation::Prepare(&cursor, MetadataCallbacks,
                    OGG_COMMENT_VERSION, job.result.metadata);
            }'''),
    ('''        for (auto& job : batch)
        {
            const auto observed = job.result.witness.ByteCount();
            if (!job.prepared || observed > maxWitnessBytes - witnessBytes)
                continue;
            witnessBytes += observed;
            prepared.emplace(std::move(job.path), std::move(job.result));
        }''',
     '''        for (auto& job : batch)
        {
            const auto observed = job.result.witness.ByteCount();
            if (job.prepared && observed && observed <= maxWitnessBytes - witnessBytes)
            {
                job.result.verification = PreparedSound::Verification::Exact;
                witnessBytes += observed;
                ++exactEntries;
            }
        }
        concurrency::parallel_for(size_t{0}, batch.size(), [&](size_t index) {
            auto& job = batch[index];
            if (!job.prepared || job.result.verification == PreparedSound::Verification::Exact)
                return;
            job.prepared = HashPreparedWave(job.result, job.bytes.data(), job.bytes.size(), job.result.digest);
            job.result.witness.ReleaseExactBytes();
        });
        for (auto& job : batch)
        {
            if (!job.prepared)
                continue;
            if (job.result.verification != PreparedSound::Verification::Exact)
                ++compactEntries;
            prepared.emplace(std::move(job.path), std::move(job.result));
        }'''),
    ('''    Msg("* sound metadata: prepared %zu of %zu opened OGG files (%llu MiB scanned, %zu MiB retained)",
        prepared.size(), opened, static_cast<unsigned long long>(bytes >> 20), witnessBytes >> 20);''',
     '''    Msg("* sound metadata: prepared %zu of %zu opened OGG files (%zu exact, %zu compact, %llu MiB scanned, %zu MiB exact bytes)",
        prepared.size(), opened, exactEntries, compactEntries,
        static_cast<unsigned long long>(bytes >> 20), witnessBytes >> 20);'''),
    ('''    if (found == cache.entries.end() || !found->second.witness.Matches(reader.pointer(), reader.length()))
        return false;
    out = found->second.metadata;''',
     '''    if (found == cache.entries.end())
        return false;
    const auto& entry = found->second;
    if (entry.verification == PreparedSound::Verification::Exact)
    {
        if (!entry.witness.Matches(reader.pointer(), reader.length()))
            return false;
    }
    else
    {
        Digest current;
        if (!HashPreparedWave(entry, reader.pointer(), reader.length(), current) || current != entry.digest)
            return false;
    }
    out = entry.metadata;'''),
])
shutil.copyfile(bundle / "SoundRangeDigest.h", root / "src/xrSound/SoundRangeDigest.h")

fixture = bundle.parents[1] / "experiments/periodic-136/spawn-resources"
shutil.copyfile(root / "src/xrSound/SoundWaveReadWitness.h", fixture / "SoundWaveReadWitness.h")
shutil.copyfile(bundle / "SoundRangeDigest.h", fixture / "SoundRangeDigest.h")
test = fixture / "wave_fixture.cpp"
source = test.read_text()
source = source.replace('#include "SoundWaveReadWitness.h"', '#include "SoundWaveReadWitness.h"\n#include "SoundRangeDigest.h"')
needle = '            require(!witness.Matches(edited.data(), edited.size()));'
assert source.count(needle) == 1
source = source.replace(needle, needle + '''
            using SoundWavePreparation::Digest;
            using SoundWavePreparation::SoundRangeDigest;
            auto fingerprint = [&](const auto& data, Digest& digest) {
                return SoundRangeDigest::Compute([&](const auto& add) {
                    return witness.VisitRanges(data.data(), data.size(), add);
                }, digest);
            };
            Digest original{}, repeat{}, different{};
            require(fingerprint(bytes, original));
            witness.ReleaseExactBytes();
            require(witness.ByteCount() == 0);
            require(fingerprint(edited, different) && different != original);
            require(fingerprint(bytes, repeat) && repeat == original);''')
test.write_text(source)
with (fixture / "CMakeLists.txt").open("a") as cmake:
    cmake.write("\ntarget_link_libraries(ixray_spawn_wave_check PRIVATE bcrypt)\n")
