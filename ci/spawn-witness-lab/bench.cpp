#include "SoundRangeDigest.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <vector>

using SoundWavePreparation::Digest;
using SoundWavePreparation::SoundRangeDigest;
using Clock = std::chrono::steady_clock;

static Digest Hash(const unsigned char* bytes, size_t size)
{
    Digest result;
    if (!SoundRangeDigest::Compute([&](const auto& add) { return add(bytes, size); }, result))
        std::abort();
    return result;
}

int main()
{
    constexpr size_t files = 512;
    std::mt19937 random(136);
    for (size_t length : {4096u, 24576u, 65536u})
    {
        std::vector<unsigned char> expected(files * length);
        for (auto& b : expected)
            b = static_cast<unsigned char>(random());
        auto current = expected;
        std::vector<Digest> digests;
        digests.reserve(files);
        for (size_t i = 0; i < files; ++i)
            digests.push_back(Hash(expected.data() + i * length, length));
        current[(files / 2) * length + length / 2] ^= 1;
        std::vector<double> times[2];
        for (unsigned run = 0; run < 13; ++run)
        {
            for (unsigned step = 0; step < 2; ++step)
            {
                const auto variant = (run + step) % 2;
                const auto start = Clock::now();
                size_t rejected = 0;
                for (size_t i = 0; i < files; ++i)
                {
                    const auto offset = i * length;
                    const bool same = variant ? std::memcmp(current.data() + offset, expected.data() + offset, length) == 0 :
                        Hash(current.data() + offset, length) == digests[i];
                    if (!same)
                        rejected += i + 1;
                }
                times[variant].push_back(std::chrono::duration<double, std::milli>(Clock::now() - start).count());
                if (rejected != files / 2 + 1)
                    std::abort();
            }
        }
        for (auto& values : times)
            std::sort(values.begin(), values.end());
        std::printf("512 ranges of %zu bytes: SHA-256 / exact median %.3f / %.3f ms; edit rejected by both\n",
            length, times[0][6], times[1][6]);
    }
}
