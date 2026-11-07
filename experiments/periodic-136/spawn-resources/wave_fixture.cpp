#include "SoundReadProof.h"

#include <chrono>
#include <fstream>
#include <iterator>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#endif

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

using SoundWavePreparation::ReadProof;

std::vector<unsigned char> load_bytes(const std::filesystem::path& path)
{
    std::ifstream input(path, std::ios::binary);
    require(static_cast<bool>(input));
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

void verify_read_proof(const std::filesystem::path& directory)
{
    const auto path = directory / "long.ogg";
    const auto bytes = load_bytes(path);
    auto* input = std::fopen(path.string().c_str(), "rb");
    require(input != nullptr);
    ReadProof proof;
    Metadata cached;
    require(SoundWavePreparation::PrepareWithReadProof(input, OV_CALLBACKS_NOCLOSE, bytes, 3, cached, proof));
    std::fclose(input);
    require(proof.matches(bytes) && proof.bytesCompared > 0 && proof.bytesCompared < bytes.size() / 2);
    require(!proof.matches(std::span(bytes).first(bytes.size() - 1)));

    const auto audio = directory / "long-audio-edit.ogg";
    require(proof.matches(load_bytes(audio)));
    input = std::fopen(audio.string().c_str(), "rb");
    require(input != nullptr);
    const auto editedAudio = reference(input);
    std::fclose(input);
    require(editedAudio.minimum == cached.minimum && editedAudio.maximum == cached.maximum &&
        editedAudio.base == cached.base && editedAudio.ai == cached.ai && editedAudio.type == cached.type &&
        editedAudio.rate == cached.rate && editedAudio.channels == cached.channels && editedAudio.bytes == cached.bytes);

    const auto comment = directory / "long-comment-edit.ogg";
    const auto changedComment = load_bytes(comment);
    require(changedComment.size() == bytes.size() && !proof.matches(changedComment));
    input = std::fopen(comment.string().c_str(), "rb");
    require(input != nullptr);
    require(reference(input).minimum != cached.minimum);
    std::fclose(input);
    auto changedRead = bytes;
    for (const auto& fragment : proof.fragments)
    {
        changedRead[fragment.offset] ^= 1;
        require(!proof.matches(changedRead));
        changedRead[fragment.offset] ^= 1;
    }
    std::printf("PASS: %zu fragments, %zu/%zu bytes; size, comment, observed and unobserved audio edits\n",
        proof.fragments.size(), proof.bytesCompared, bytes.size());

#ifdef _WIN32
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    require(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0);
    DWORD workSize = 0;
    DWORD resultSize = 0;
    require(BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
        reinterpret_cast<PUCHAR>(&workSize), sizeof(workSize), &resultSize, 0) >= 0);
    std::vector<unsigned char> work(workSize);
    auto hashInput = bytes;
    std::array<unsigned char, 32> digest{};
    constexpr int iterations = 3000;
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < iterations; ++i)
    {
        BCRYPT_HASH_HANDLE hash = nullptr;
        require(BCryptCreateHash(algorithm, &hash, work.data(), workSize, nullptr, 0, 0) >= 0);
        require(BCryptHashData(hash, hashInput.data(), static_cast<ULONG>(hashInput.size()), 0) >= 0);
        require(BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0);
        BCryptDestroyHash(hash);
    }
    const auto middle = std::chrono::steady_clock::now();
    for (int i = 0; i < iterations; ++i)
        require(proof.matches(i % 2 ? bytes : hashInput));
    const auto end = std::chrono::steady_clock::now();
    BCryptCloseAlgorithmProvider(algorithm, 0);
    using Microseconds = std::chrono::duration<double, std::micro>;
    std::printf("Metadata validation only, %d warm trials: %.3f -> %.3f us/call\n", iterations,
        Microseconds(middle - start).count() / iterations, Microseconds(end - middle).count() / iterations);
#endif
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
    verify_read_proof(argv[1]);
    std::puts("PASS: real mono, stereo and chained Vorbis; all three game comment layouts; rejected bad inputs");
}
