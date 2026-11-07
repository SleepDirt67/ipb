#include "SoundWaveMetadata.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>

void require(bool value)
{
    if (!value)
        std::abort();
}

using SoundWavePreparation::Metadata;

Metadata reference(FILE* file)
{
    // Same reference API, format arithmetic and game comment fields as LoadWave.
    OggVorbis_File ogg{};
    require(ov_open_callbacks(file, &ogg, nullptr, 0, OV_CALLBACKS_NOCLOSE) == 0);
    const auto* info = ov_info(&ogg, -1);
    const auto* comments = ov_comment(&ogg, -1);
    const auto samples = ov_pcm_total(&ogg, -1);
    const auto* comment = comments->user_comments[0];
    Metadata out;
    out.rate = info->rate;
    out.channels = info->channels;
    const std::uint16_t align = (out.channels * 16) / 8;
    out.bytes = static_cast<std::uint32_t>(samples * align);
    auto load = [&](auto& value, size_t index) { std::memcpy(&value, comment + index, sizeof(value)); };
    std::uint32_t version;
    load(version, 0);
    load(out.minimum, 4);
    load(out.maximum, 8);
    out.ai = out.maximum;
    if (version == 1)
        load(out.type, 12);
    else
    {
        load(out.base, 12);
        load(out.type, 16);
        if (version == 3)
            load(out.ai, 20);
    }
    ov_clear(&ogg);
    return out;
}

int main(int argc, char** argv)
{
    require(argc == 2);
    for (const auto* name : {"v1", "v2", "v3", "chained", "bad-comment", "bad-stream", "unrecognised"})
    {
        const auto path = std::filesystem::path(argv[1]) / (std::string(name) + ".ogg");
        auto* file = std::fopen(path.string().c_str(), "rb");
        require(file != nullptr);
        Metadata cached;
        const bool prepared = SoundWavePreparation::Prepare(file, OV_CALLBACKS_NOCLOSE, 3, cached);
        if (std::string_view(name).starts_with("v") || std::string_view(name) == "chained")
        {
            require(prepared);
            std::rewind(file);
            const auto old = reference(file);
            require(cached.rate == old.rate && cached.channels == old.channels && cached.bytes == old.bytes &&
                    cached.minimum == old.minimum && cached.maximum == old.maximum && cached.base == old.base &&
                    cached.ai == old.ai && cached.type == old.type);
        }
        else
            require(!prepared);
        std::fclose(file);
    }
    std::puts("PASS: real mono, stereo and chained Vorbis; all three game comment layouts; rejected bad inputs");
}
