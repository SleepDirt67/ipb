"""Index the live sound collections for native and Lua spawn registration."""
import argparse
from pathlib import Path

from apply import edit


def patch(root):
    game = root / "src/xrGame"
    edit(game / "sound_collection_storage.h", [
        ('#include "sound_player.h"', '#include "sound_player.h"\n#include <unordered_map>'),
        ("\tOBJECTS\t\t\t\t\t\t\t\tm_objects;",
         """    struct CollectionHash
    {
        size_t operator()(const CSoundCollectionParams& params) const noexcept;
    };

\tOBJECTS\t\t\t\t\t\t\t\tm_objects;
    std::unordered_map<CSoundCollectionParams, size_t, CollectionHash> collectionIndex;"""),
    ])
    edit(game / "sound_collection_storage.cpp", [
        ('#include "object_broker.h"', '#include "object_broker.h"\n#include <cstdlib>\n#include <memory>'),
        ("CSoundCollectionStorage::~CSoundCollectionStorage\t()", """size_t CSoundCollectionStorage::CollectionHash::operator()(const CSoundCollectionParams& params) const noexcept
{
    size_t hash = std::hash<const void*>{}(params.m_sound_prefix._get());
    const auto combine = [&hash](size_t value) { hash ^= value + 0x9e3779b9 + (hash << 6) + (hash >> 2); };
    combine(std::hash<const void*>{}(params.m_sound_player_prefix._get()));
    combine(params.m_max_count);
    combine(static_cast<unsigned>(params.m_type));
    return hash;
}

CSoundCollectionStorage::~CSoundCollectionStorage\t()"""),
        ("\tOBJECTS::const_iterator\tI = std::find_if", """    static const bool useIndex = [] {
        const char* enabled = std::getenv("IXRAY_SPAWN_PREPARE");
        return enabled && xr_strcmp(enabled, "1") == 0;
    }();
    if (useIndex)
    {
        if (const auto found = collectionIndex.find(params); found != collectionIndex.end())
            return m_objects[found->second];

        // Do not build a collection earlier. Its live creation sets the RNG
        // seed and creates sounds in the original registration order.
        auto collection = std::make_unique<CSoundCollection>(params);
        const auto [entry, inserted] = collectionIndex.try_emplace(params, m_objects.size());
        if (!inserted)
            return m_objects[entry->second];
        try
        {
            m_objects.emplace_back(params, collection.get());
        }
        catch (...)
        {
            collectionIndex.erase(entry);
            throw;
        }
        collection.release();
        return m_objects.back();
    }
\tOBJECTS::const_iterator\tI = std::find_if"""),
    ])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    patch(parser.parse_args().engine)
