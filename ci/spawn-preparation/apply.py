"""Put OGG preparation and observed DX11 variants on the level-loading path."""
from pathlib import Path
import shutil
import sys

bundle = Path(__file__).resolve().parent
root = Path(sys.argv[1])


def edit(path, changes):
    target = root / path
    raw = target.read_bytes()
    crlf = b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError(f"{path}: expected one anchor {before[:80]!r}, found {text.count(before)}")
        text = text.replace(before, after, 1)
    target.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("latin-1"))


sound = "src/xrSound/SoundRender_Source_loader.cpp"
edit(sound, [
    ('#include "SoundWaveMetadata.h"\n#include <bcrypt.h>',
     '#include "SoundWaveReadWitness.h"'),
    ('#include <array>\n', ''),
    ('using Digest = std::array<unsigned char, 32>;',
     'using SoundWavePreparation::ReadWitness;'),
    ('    Digest digest{};', '    ReadWitness witness;'),
])
source = root / sound
raw = source.read_bytes()
first = raw.index(b"struct Sha256Provider")
last = raw.index(b"constexpr ov_callbacks MetadataCallbacks", first)
source.write_bytes(raw[:first] + raw[last:])
edit(sound, [
    ("""    std::vector<WaveJob> batch;""", """    constexpr size_t maxWitnessBytes = 128u * 1024 * 1024;
    size_t witnessBytes = 0;
    std::vector<WaveJob> batch;"""),
    ("""            job.prepared = FileDigest(cursor, job.result.digest) &&
                SoundWavePreparation::Prepare(&cursor, MetadataCallbacks,
                    OGG_COMMENT_VERSION, job.result.metadata);""",
     """            job.prepared = job.result.witness.PrepareFrom(&cursor, MetadataCallbacks,
                job.bytes.data(), job.bytes.size(), OGG_COMMENT_VERSION, job.result.metadata);"""),
    ("""        for (auto& job : batch)
            if (job.prepared)
                prepared.emplace(std::move(job.path), job.result);""",
     """        for (auto& job : batch)
        {
            const auto observed = job.result.witness.ByteCount();
            if (!job.prepared || observed > maxWitnessBytes - witnessBytes)
                continue;
            witnessBytes += observed;
            prepared.emplace(std::move(job.path), std::move(job.result));
        }"""),
    ("""    Msg("* sound metadata: prepared %zu of %zu opened OGG files (%llu MiB scanned)",
        prepared.size(), opened, static_cast<unsigned long long>(bytes >> 20));""",
     """    Msg("* sound metadata: prepared %zu of %zu opened OGG files (%llu MiB scanned, %zu MiB retained)",
        prepared.size(), opened, static_cast<unsigned long long>(bytes >> 20), witnessBytes >> 20);"""),
    ("""    PreparedSound candidate;
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
    out = candidate.metadata;""",
     """    auto& cache = WaveCache();
    std::shared_lock guard(cache.lock);
    const auto found = cache.entries.find(path);
    if (found == cache.entries.end() || !found->second.witness.Matches(reader.pointer(), reader.length()))
        return false;
    out = found->second.metadata;"""),
])
shutil.copyfile(bundle / "SoundWaveReadWitness.h", root / "src/xrSound/SoundWaveReadWitness.h")

edit("src/xrCore/LocatorAPI.h", [
    ('bool find_numbered_sounds(LPCSTR prefix, u32 limit, xr_vector<u32>& indices);',
     'bool find_numbered_sounds(LPCSTR prefix, u32 limit, xr_vector<u32>& indices);\n'
     '    int sound_variant_count(LPCSTR prefix);'),
])
edit("src/xrCore/LocatorAPI.cpp", [
    ('BOOL CLocatorAPI::dir_delete(LPCSTR path,LPCSTR nm,BOOL remove_files)',
     '''int CLocatorAPI::sound_variant_count(LPCSTR prefix)
{
    constexpr u32 limit = 1000;
    if (m_Flags.is_any(flNeedCheck | flNeedRescan | flEventNotificator |
        flBuildCopy | flEBuildCopy | flCacheFiles))
        return -2;

    xr_vector<u32> indices;
    if (!find_numbered_sounds(prefix, limit, indices))
        return -2;

    string_path path;
    if (exist(path, "$game_sounds$", prefix, ".ogg"))
        return -1;

    u32 next = 1;
    for (const auto index : indices)
    {
        if (index == 0)
            continue;
        if (index != next)
            break;
        ++next;
    }
    return next == limit ? -2 : static_cast<int>(next - 1);
}

BOOL CLocatorAPI::dir_delete(LPCSTR path,LPCSTR nm,BOOL remove_files)'''),
])
edit("src/xrGame/fs_registrator_script.cpp", [
    ('\t\t\t.def("get_file_age",', '\t\t\t.def("sound_variant_count", &CLocatorAPI::sound_variant_count)\n'
     '\t\t\t.def("get_file_age",'),
])
edit("src/xrScripts/script_storage.cpp", [
    ('#include "PreparedStockLogic.inc"', '''#include "PreparedStockLogic.inc"
#include "StockVoiceScript.inc"

std::string_view PrepareStockVoice(LPCSTR name, std::string_view data)
{
    if (!name || xr_strcmp(name, "sound_theme") != 0 ||
        data.size() < sizeof(stockVoiceScript) || data.size() > 2 * sizeof(stockVoiceScript))
        return {};

    size_t index = 0;
    for (size_t offset = 0; offset < data.size(); ++offset)
    {
        if (data[offset] == '\\r' && offset + 1 < data.size() && data[offset + 1] == '\\n')
            continue;
        if (index == sizeof(stockVoiceScript) || static_cast<unsigned char>(data[offset]) != stockVoiceScript[index++])
            return {};
    }
    if (index != sizeof(stockVoiceScript))
        return {};
    return {reinterpret_cast<const char*>(batchedVoiceScript), sizeof(batchedVoiceScript)};
}'''),
    ('''        const auto prepared = PrepareStockLogic(caNameSpaceName, original);
        const auto source = prepared.empty() ? original : prepared;
        if (!prepared.empty())
            Msg("* xr_logic: prepared stock condition programs");''',
     '''        auto prepared = PrepareStockLogic(caNameSpaceName, original);
        if (!prepared.empty())
            Msg("* xr_logic: prepared stock condition programs");
        else
        {
            prepared = PrepareStockVoice(caNameSpaceName, original);
            if (!prepared.empty())
                Msg("* sound_theme: batched stock voice discovery");
        }
        const auto source = prepared.empty() ? original : prepared;'''),
])
edit("src/xrScripts/SpawnLuaProfile.h", [
    ('''        if (!PacingDiag::SpawnPathEnabled() || recorder)
            return;
        const auto dll''',
     '''        if (!PacingDiag::SpawnPathEnabled() || recorder)
            return;
        wchar_t mode[2] = {};
        if (GetEnvironmentVariableW(L"IXRAY_SPAWN_LUA", mode, 2) != 1 || mode[0] != L'1')
            return;
        const auto dll'''),
])
from voice import generate
generate(root)
wave_fixture = bundle.parents[1] / "experiments/periodic-136/spawn-resources"
shutil.copyfile(bundle / "SoundWaveReadWitness.h", wave_fixture / "SoundWaveReadWitness.h")
shutil.copyfile(bundle / "wave_fixture.cpp", wave_fixture / "wave_fixture.cpp")

shutil.copyfile(bundle / "voice_catalog_fixture.cpp", root / "ixray_spawn_voice_catalog.cpp")
with (root / "CMakeLists.txt").open("a", encoding="utf-8") as cmake:
    cmake.write("""
add_executable(ixray_spawn_voice_catalog ixray_spawn_voice_catalog.cpp)
target_include_directories(ixray_spawn_voice_catalog PRIVATE src/xrCore)
target_link_libraries(ixray_spawn_voice_catalog PRIVATE xrCore)
""")
