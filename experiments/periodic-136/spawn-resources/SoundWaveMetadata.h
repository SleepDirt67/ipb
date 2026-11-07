#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <limits>

#include <vorbis/vorbisfile.h>

namespace SoundWavePreparation
{
struct Metadata
{
    std::uint32_t rate = 0;
    std::uint16_t channels = 0;
    std::uint32_t bytes = 0;
    float minimum = 0.f;
    float maximum = 0.f;
    float base = 1.f;
    float ai = 0.f;
    std::uint32_t type = 0;
};

template<class T>
T ReadScalar(const char*& position)
{
    T value;
    std::memcpy(&value, position, sizeof(value));
    position += sizeof(value);
    return value;
}

inline bool Prepare(void* input, ov_callbacks callbacks, std::uint32_t currentVersion, Metadata& out)
{
    OggVorbis_File ogg{};
    if (ov_open_callbacks(input, &ogg, nullptr, 0, callbacks) != 0)
        return false;

    const auto* info = ov_info(&ogg, -1);
    const auto* comments = ov_comment(&ogg, -1);
    const auto samples = ov_pcm_total(&ogg, -1);
    bool success = false;
    if (info && info->channels > 0 && info->channels <= 32767 &&
        info->rate > 0 && info->rate <= std::numeric_limits<std::uint32_t>::max() &&
        samples >= 0 && comments && comments->comments > 0 &&
        comments->comment_lengths[0] >= 16)
    {
        auto* position = static_cast<const char*>(comments->user_comments[0]);
        const auto version = ReadScalar<std::uint32_t>(position);
        const int length = comments->comment_lengths[0];
        if (version == 1 || (version == 2 && length >= 20) ||
            (version == currentVersion && length >= 24))
        {
            Metadata result;
            result.rate = static_cast<std::uint32_t>(info->rate);
            result.channels = static_cast<std::uint16_t>(info->channels);
            result.bytes = static_cast<std::uint32_t>(samples) * (2u * result.channels);
            result.minimum = ReadScalar<float>(position);
            result.maximum = ReadScalar<float>(position);
            result.base = version == 1 ? 1.f : ReadScalar<float>(position);
            result.type = ReadScalar<std::uint32_t>(position);
            result.ai = version == currentVersion ? ReadScalar<float>(position) : result.maximum;
            if (result.ai >= 0.1f && result.maximum >= 0.1f)
            {
                out = result;
                success = true;
            }
        }
    }
    ov_clear(&ogg);
    return success;
}
}
