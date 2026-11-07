#pragma once

#include "SoundWaveMetadata.h"
#include <algorithm>
#include <utility>
#include <vector>

namespace SoundWavePreparation
{
// A cached result is valid for any VFS-resolved reader that supplies the
// same length and the exact bytes that libvorbis observed while preparing it.
class ReadWitness
{
    struct Range
    {
        size_t first, last;
    };

    struct Capture
    {
        void* reader;
        ov_callbacks io;
        size_t size;
        std::array<Range, 64> ranges{};
        size_t used = 0;
        bool valid = true;

        void record(size_t first, size_t last)
        {
            size_t i = 0;
            while (i < used && ranges[i].last < first)
                ++i;
            size_t j = i;
            while (j < used && ranges[j].first <= last)
            {
                first = (std::min)(first, ranges[j].first);
                last = (std::max)(last, ranges[j].last);
                ++j;
            }
            if (i == j && used == ranges.size())
            {
                valid = false;
                return;
            }
            if (i == j)
                std::move_backward(ranges.begin() + j, ranges.begin() + used, ranges.begin() + used + 1);
            else if (j > i + 1)
                std::move(ranges.begin() + j, ranges.begin() + used, ranges.begin() + i + 1);
            ranges[i] = {first, last};
            used = used - (j - i) + 1;
        }

        static size_t Read(void* output, size_t unit, size_t count, void* input)
        {
            auto& capture = *static_cast<Capture*>(input);
            const long start = capture.io.tell_func(capture.reader);
            const size_t read = capture.io.read_func(output, unit, count, capture.reader);
            if (!read || !capture.valid)
                return read;
            if (start < 0 || static_cast<size_t>(start) > capture.size ||
                unit > (capture.size - static_cast<size_t>(start)) / read)
                capture.valid = false;
            else
                capture.record(static_cast<size_t>(start), static_cast<size_t>(start) + unit * read);
            return read;
        }
        static int Seek(void* input, ogg_int64_t offset, int whence)
        {
            auto& capture = *static_cast<Capture*>(input);
            return capture.io.seek_func(capture.reader, offset, whence);
        }
        static long Tell(void* input)
        {
            auto& capture = *static_cast<Capture*>(input);
            return capture.io.tell_func(capture.reader);
        }
    };

    size_t size_ = 0;
    std::vector<Range> ranges_;
    std::vector<unsigned char> bytes_;

public:
    bool PrepareFrom(void* reader, ov_callbacks io, const void* bytes, size_t size,
                     std::uint32_t version, Metadata& metadata)
    {
        Capture capture{reader, io, size};
        constexpr ov_callbacks observe{Capture::Read, Capture::Seek, nullptr, Capture::Tell};
        if (!Prepare(&capture, observe, version, metadata) || !capture.valid || !capture.used)
            return false;

        auto* data = static_cast<const unsigned char*>(bytes);
        size_t observed = 0;
        for (size_t i = 0; i < capture.used; ++i)
            observed += capture.ranges[i].last - capture.ranges[i].first;
        std::vector<unsigned char> expected;
        expected.reserve(observed);
        for (size_t i = 0; i < capture.used; ++i)
        {
            const auto& range = capture.ranges[i];
            expected.insert(expected.end(), data + range.first, data + range.last);
        }
        ranges_.assign(capture.ranges.begin(), capture.ranges.begin() + capture.used);
        bytes_ = std::move(expected);
        size_ = size;
        return true;
    }

    bool Matches(const void* bytes, size_t size) const
    {
        if (size != size_ || ranges_.empty())
            return false;
        const auto* expected = bytes_.data();
        const auto* data = static_cast<const unsigned char*>(bytes);
        for (const auto& range : ranges_)
        {
            const auto length = range.last - range.first;
            if (std::memcmp(expected, data + range.first, length) != 0)
                return false;
            expected += length;
        }
        return true;
    }

    size_t ByteCount() const { return bytes_.size(); }
};
}
