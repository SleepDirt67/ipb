"""Select exact sound witnesses using the same level cohort as model preparation."""
import argparse
from pathlib import Path


def edit(path, before, after):
    raw = path.read_bytes()
    data = raw.replace(b"\r\n", b"\n")
    before, after = before.encode(), after.encode()
    if data.count(before) != 1:
        raise ValueError((path, before[:80], data.count(before)))
    result = data.replace(before, after, 1)
    path.write_bytes(result.replace(b"\n", b"\r\n") if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"") else result)


def patch(root):
    sound = root / "src/xrSound"
    edit(sound / "Sound.h", "XRSOUND_API void PrepareSpawnSoundMetadata();",
         "XRSOUND_API void PrepareSpawnSoundMetadata();\n"
         "XRSOUND_API void PromoteSpawnSoundMetadata(const char* const* prefixes, size_t count);")
    edit(sound / "SoundWaveReadWitness.h",
         "    void ReleaseExactBytes() { std::vector<unsigned char>().swap(bytes_); }",
         """    bool RememberExactBytes(const void* bytes, size_t size)
    {
        if (!bytes || size != size_ || ranges_.empty())
            return false;
        const auto* data = static_cast<const unsigned char*>(bytes);
        size_t total = 0;
        for (const auto& range : ranges_)
            total += range.last - range.first;
        std::vector<unsigned char> exact;
        exact.reserve(total);
        for (const auto& range : ranges_)
            exact.insert(exact.end(), data + range.first, data + range.last);
        bytes_.swap(exact);
        return true;
    }

    template<class Visit>
    bool VisitExactBytes(const Visit& visit) const
    {
        return !bytes_.empty() && visit(bytes_.data(), bytes_.size());
    }

    void ReleaseExactBytes() { std::vector<unsigned char>().swap(bytes_); }""")
    edit(sound / "SoundRender_Source_loader.cpp", "bool TryUsePreparedWave(IReader& reader, const char* path, Metadata& out)",
         Path(__file__).with_name("SpawnWavePromotion.inc").read_text() +
         "\nbool TryUsePreparedWave(IReader& reader, const char* path, Metadata& out)")
    edit(sound / "SoundRender_Source_loader.cpp", "void PrepareSpawnSoundMetadata() {}",
         "void PrepareSpawnSoundMetadata() {}\nvoid PromoteSpawnSoundMetadata(const char* const*, size_t) {}")
    edit(sound / "SoundRender_Source_loader.cpp", "constexpr auto MaxWaveBytes = 512u * 1024;",
         "constexpr auto MaxWaveBytes = 512u * 1024;\n"
         "constexpr size_t MaxExactWitnessBytes = 128u * 1024 * 1024;")
    edit(sound / "SoundRender_Source_loader.cpp", "    constexpr size_t maxWitnessBytes = 128u * 1024 * 1024;\n", "")
    edit(sound / "SoundRender_Source_loader.cpp", "maxWitnessBytes - witnessBytes", "MaxExactWitnessBytes - witnessBytes")

    server = root / "src/xrServerEntities"
    edit(server / "xml_str_id_loader.h", "\tstatic\tvoid\t\t\t\t\tInitInternal ();",
         """    static const ITEM_DATA* FindInitializedId(const shared_str& id)
    {
        if (m_pItemDataVector)
            for (const auto& entry : *m_pItemDataVector)
                if (entry.id == id)
                    return &entry;
        return nullptr;
    }

\tstatic\tvoid\t\t\t\t\tInitInternal ();""")
    edit(server / "specific_character.h", "\tLPCSTR\t\t\t\t\t\tsound_voice_prefix\t\t() const ;",
         "    static LPCSTR SpawnVoicePrefix(const shared_str& id);\n"
         "\tLPCSTR\t\t\t\t\t\tsound_voice_prefix\t\t() const ;")
    edit(server / "specific_character.cpp", "LPCSTR CSpecificCharacter::sound_voice_prefix () const",
         """LPCSTR CSpecificCharacter::SpawnVoicePrefix(const shared_str& id)
{
    const auto* record = id_to_index::FindInitializedId(id);
    if (!record || !record->_xml)
        return nullptr;
    auto& xml = *record->_xml;
    auto* node = xml.NavigateToNode(xml.GetRoot(), id_to_index::tag_name, record->pos_in_file);
    return node ? xml.Read(node, "snd_config", 0, "") : nullptr;
}

LPCSTR CSpecificCharacter::sound_voice_prefix () const""")

    game = root / "src/xrGame"
    edit(game / "PrepareSpawnVisuals.inc", "    xr_set<xr_string> visuals;",
         """    xr_set<xr_string> visuals;
    xr_set<xr_string> voicePrefixes;
    const char* prepare = std::getenv("IXRAY_SPAWN_PREPARE");
    const bool prepareVoice = prepare && xr_strcmp(prepare, "1") == 0;""")
    edit(game / "PrepareSpawnVisuals.inc", "        if (auto* visual = object->visual())",
         """        if (prepareVoice)
        {
            if (const auto* stalker = smart_cast<const CSE_ALifeHumanStalker*>(object))
            {
                const char* prefix = nullptr;
                if (pSettings->line_exist(object->s_name, "voice_prefix"))
                    prefix = pSettings->r_string(object->s_name, "voice_prefix");
                else if (stalker->m_SpecificCharacter.size())
                    prefix = CSpecificCharacter::SpawnVoicePrefix(stalker->m_SpecificCharacter);
                if (prefix && *prefix)
                    voicePrefixes.emplace(prefix);
            }
        }
        if (auto* visual = object->visual())""")
    edit(game / "PrepareSpawnVisuals.inc", "    // PDA sections may be created",
         """    if (!voicePrefixes.empty())
    {
        std::vector<const char*> paths;
        paths.reserve(voicePrefixes.size());
        for (const auto& prefix : voicePrefixes)
            paths.push_back(prefix.c_str());
        PromoteSpawnSoundMetadata(paths.data(), paths.size());
    }

    // PDA sections may be created""")
    edit(game / "Level_network_start_client.cpp", '#include "PrepareSpawnVisuals.inc"',
         '#include "../xrSound/Sound.h"\n#include "specific_character.h"\n#include "PrepareSpawnVisuals.inc"')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    patch(parser.parse_args().engine)
