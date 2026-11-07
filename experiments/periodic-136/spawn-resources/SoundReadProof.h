#pragma once

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstring>
#include <span>
#include <utility>
#include <vector>

#include "SoundWaveMetadata.h"

namespace SoundWavePreparation
{
struct ReadProof
{
    struct Fragment
    {
        size_t offset;
        std::vector<unsigned char> bytes;
    };

    size_t fileSize = 0;
    size_t bytesCompared = 0;
    std::vector<Fragment> fragments;

    bool matches(std::span<const unsigned char> source) const
    {
        if (fragments.empty() || fileSize != source.size())
            return false;
        for (const auto& fragment : fragments)
            if (std::memcmp(source.data() + fragment.offset, fragment.bytes.data(), fragment.bytes.size()))
                return false;
        return true;
    }
};

namespace detail
{
struct RecordingInput
{
    struct Range { size_t first; size_t last; };
    void* input;
    ov_callbacks original;
    size_t fileSize;
    std::array<Range, 128> ranges{};
    size_t count = 0;
    bool complete = true;

    static size_t read(void* destination, size_t size, size_t requested, void* userdata)
    {
        auto& state = *static_cast<RecordingInput*>(userdata);
        if (!size)
        {
            state.complete = false;
            return 0;
        }
        const long first = state.original.tell_func(state.input);
        const auto readCount = state.original.read_func(destination, size, requested, state.input);
        const long last = state.original.tell_func(state.input);
        if (first < 0 || last < first || static_cast<size_t>(last) > state.fileSize
            || static_cast<size_t>(last - first) % size
            || static_cast<size_t>(last - first) / size != readCount)
            state.complete = false;
        else if (last != first)
        {
            if (state.count == state.ranges.size())
                state.complete = false;
            else
                state.ranges[state.count++] = {static_cast<size_t>(first), static_cast<size_t>(last)};
        }
        return readCount;
    }

    static int seek(void* userdata, ogg_int64_t offset, int whence)
    {
        auto& state = *static_cast<RecordingInput*>(userdata);
        return state.original.seek_func(state.input, offset, whence);
    }

    static int close(void* userdata)
    {
        auto& state = *static_cast<RecordingInput*>(userdata);
        return state.original.close_func ? state.original.close_func(state.input) : 0;
    }

    static long tell(void* userdata)
    {
        auto& state = *static_cast<RecordingInput*>(userdata);
        return state.original.tell_func(state.input);
    }
};
}

inline bool PrepareWithReadProof(void* input, ov_callbacks callbacks, std::span<const unsigned char> source,
    std::uint32_t currentVersion, Metadata& metadata, ReadProof& proof)
{
    detail::RecordingInput recording{input, callbacks, source.size()};
    if (!Prepare(&recording, {recording.read, recording.seek, recording.close, recording.tell},
        currentVersion, metadata) || !recording.complete || !recording.count)
        return false;

    // Same length and bytes at every recorded read imply the same decoder
    // decisions and metadata. Seeks and tells use the original callbacks.
    auto first = recording.ranges.begin();
    const auto end = first + recording.count;
    std::sort(first, end, [](const auto& left, const auto& right) { return left.first < right.first; });
    ReadProof result;
    result.fileSize = source.size();
    constexpr size_t MaxProofBytes = 96 * 1024;
    while (first != end)
    {
        auto range = *first++;
        while (first != end && first->first <= range.last)
        {
            range.last = (std::max)(range.last, first->last);
            ++first;
        }
        const auto length = range.last - range.first;
        if (length > MaxProofBytes - result.bytesCompared)
            return false;
        result.bytesCompared += length;
        result.fragments.push_back({range.first, {source.data() + range.first, source.data() + range.last}});
    }
    proof = std::move(result);
    return true;
}
}
