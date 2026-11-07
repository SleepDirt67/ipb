#pragma once

#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <cstddef>

namespace SoundWavePreparation
{
using Digest = std::array<unsigned char, 32>;

class SoundRangeDigest
{
    BCRYPT_ALG_HANDLE provider_ = nullptr;
    BCRYPT_HASH_HANDLE hash_ = nullptr;
    bool reusable_ = true;

    void ResetHash()
    {
        if (hash_)
            BCryptDestroyHash(hash_);
        hash_ = nullptr;
    }

    SoundRangeDigest()
    {
        BCRYPT_ALG_HANDLE provider = nullptr;
        if (BCryptOpenAlgorithmProvider(&provider, BCRYPT_SHA256_ALGORITHM, nullptr, 0) >= 0)
            provider_ = provider;
    }

    ~SoundRangeDigest()
    {
        ResetHash();
        if (provider_)
            BCryptCloseAlgorithmProvider(provider_, 0);
    }

    bool Begin()
    {
        if (hash_)
            return true;
        if (!provider_)
            return false;
        BCRYPT_HASH_HANDLE hash = nullptr;
        if (reusable_ &&
            BCryptCreateHash(provider_, &hash, nullptr, 0, nullptr, 0, BCRYPT_HASH_REUSABLE_FLAG) >= 0)
        {
            hash_ = hash;
            return true;
        }
        reusable_ = false;
        if (BCryptCreateHash(provider_, &hash, nullptr, 0, nullptr, 0, 0) < 0)
            return false;
        hash_ = hash;
        return true;
    }

public:
    template<class Feed>
    static bool Compute(Feed&& feed, Digest& digest)
    {
        thread_local SoundRangeDigest state;
        if (!state.Begin())
            return false;
        const auto add = [&](const void* data, size_t size) {
            return BCryptHashData(state.hash_, const_cast<PUCHAR>(static_cast<const unsigned char*>(data)),
                static_cast<ULONG>(size), 0) >= 0;
        };
        const bool success = feed(add) &&
            BCryptFinishHash(state.hash_, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
        if (!success || !state.reusable_)
            state.ResetHash();
        return success;
    }
};
}
