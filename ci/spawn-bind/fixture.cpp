#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <memory>
#include <unordered_map>
#include <utility>
#include <vector>

#define IC inline
using u32 = unsigned;
using ESoundTypes = unsigned;
template<class T> using xr_vector = std::vector<T>;

struct shared_str
{
    const void* p = nullptr;
    const void* _get() const { return p; }
    bool operator==(const shared_str&) const = default;
};
struct CSoundPlayer
{
#include "CollectionParams.inc"
    struct CSoundCollection
    {
        static inline unsigned next = 0;
        static inline std::function<void(const CSoundCollectionParams&)> reenter;
        unsigned id = ++next;
        explicit CSoundCollection(const CSoundCollectionParams& params)
        {
            if (reenter) reenter(params);
        }
    };
};
template<class Vector> void delete_data(Vector& pairs)
{
    for (auto& pair : pairs) delete pair.second;
}

#include "BaselineStorage.inc"
#include "IndexedStorage.inc"

template<class Storage>
static void CompareReentry(unsigned prefill)
{
    Storage storage;
    using Collection = CSoundPlayer::CSoundCollection;
    Collection::next = 0;
    std::vector<unsigned> keys(prefill);
    for (auto& key : keys)
        storage.object({{&key}, {}, 64, 3});
    unsigned bridge = 0;
    bool nested = false;
    Collection::reenter = [&](const auto& params) {
        if (!nested)
        {
            nested = true;
            if (storage.object({{&bridge}, {}, 64, 3}).second->id != prefill + 2) std::abort();
            if (storage.object(params).second->id != prefill + 3) std::abort();
        }
    };
    CSoundPlayer::CSoundCollectionParams params{{}, {}, 64, 3};
    if (storage.object(params).second->id != prefill + 1 || storage.object(params).second->id != prefill + 3)
        std::abort();
    Collection::reenter = {};
    params.m_type = 4;
    if (storage.object(params).second->id != prefill + 4) std::abort();
    params.m_max_count = 63;
    if (storage.object(params).second->id != prefill + 5) std::abort();
}

template<class Storage>
static std::pair<double, unsigned> Replay(unsigned profiles)
{
    using namespace std::chrono;
    Storage storage;
    CSoundPlayer::CSoundCollection::next = 0;
    std::vector<unsigned> names(569), prefixes(profiles);
    for (auto& prefix : prefixes)
        for (auto& name : names)
            storage.object({{&name}, {&prefix}, 64, 3});
    unsigned checksum = 0;
    const auto begin = steady_clock::now();
    for (unsigned actor = 0; actor < 9; ++actor)
        for (auto& name : names)
            checksum += storage.object({{&name}, {&prefixes[(actor * 7) % profiles]}, 64, 3}).second->id;
    return {duration<double, std::milli>(steady_clock::now() - begin).count(), checksum};
}

int main()
{
    for (const unsigned prefill : {0u, 2047u, 2048u})
    {
        CompareReentry<BaselineStorage>(prefill);
        CompareReentry<IndexedStorage>(prefill);
    }
    std::vector<double> a, b;
    for (unsigned i = 0; i < 13; ++i)
    {
        const auto before = Replay<BaselineStorage>(12);
        const auto after = Replay<IndexedStorage>(12);
        if (before.second != after.second) std::abort();
        a.push_back(before.first);
        b.push_back(after.first);
    }
    std::sort(a.begin(), a.end());
    std::sort(b.begin(), b.end());
    std::printf("5121 lookups with 6828 entries, median %.3f -> %.3f ms; reentry passed\n", a[6], b[6]);
}
