"""Replace the serial scan across globally registered sound collections."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
fixture = Path(sys.argv[2]) if len(sys.argv) > 2 else None
game = root / "src/xrGame"

def write(path, text, original):
    output = text.encode("utf-8")
    if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    path.write_bytes(output)

hp = game / "sound_collection_storage.h"
cp = game / "sound_collection_storage.cpp"
hraw, craw = hp.read_bytes(), cp.read_bytes()
header, source = (raw.replace(b"\r\n", b"\n").decode("utf-8") for raw in (hraw, craw))
members = "	OBJECTS								m_objects;"
if header.count(members) != 1:
    raise ValueError("Sound collection layout drift")
indexed = '''    struct ParamsHash
    {
        size_t operator()(const CSoundCollectionParams& params) const noexcept
        {
            const auto first = std::hash<const void*>{}(params.m_sound_prefix._get());
            const auto second = std::hash<const void*>{}(params.m_sound_player_prefix._get());
            auto hash = first ^ (second + 0x9e3779b9u + (first << 6) + (first >> 2));
            hash ^= params.m_max_count + 0x9e3779b9u + (hash << 6) + (hash >> 2);
            return hash ^ (static_cast<unsigned>(params.m_type) + 0x9e3779b9u + (hash << 6) + (hash >> 2));
        }
    };
    std::unordered_map<CSoundCollectionParams, size_t, ParamsHash> m_index;'''
next_header = header.replace('#include "sound_player.h"', '#include "sound_player.h"\n#include <unordered_map>', 1)
next_header = next_header.replace(members, members + "\n" + indexed, 1)
start = source.index("class collection_predicate {")
body = source.index("const CSoundCollectionStorage::SOUND_COLLECTION_PAIR&", start)
middle = source.index("CSoundCollectionStorage::~CSoundCollectionStorage", start)
old_body = source[body:]
if old_body.count("std::find_if") != 1 or old_body.count("m_objects.back()") != 1:
    raise ValueError("Sound collection lookup source drift")
new_body = old_body[:old_body.index("\n{")] + '''
{
    // Small registries avoid allocating a second container for cold misses.
    constexpr size_t IndexThreshold = 2048;
    if (m_index.empty() && m_objects.size() >= IndexThreshold)
    {
        decltype(m_index) index;
        index.reserve(m_objects.size());
        for (size_t i = 0; i < m_objects.size(); ++i)
            index.try_emplace(m_objects[i].first, i);
        m_index.swap(index);
    }

    if (m_index.empty())
    {
        const auto found = std::find_if(m_objects.begin(), m_objects.end(), [&](const auto& entry) {
            return entry.first == params;
        });
        if (found != m_objects.end())
            return *found;
    }
    else if (const auto found = m_index.find(params); found != m_index.end())
        return m_objects[found->second];

    // Construct first. A nested registration can publish the same key or
    // build the index. Its earlier vector entry remains the first match.
    std::unique_ptr<CSoundCollection> collection(new CSoundCollection(params));
    if (m_index.empty())
    {
        m_objects.emplace_back(params, collection.get());
        collection.release();
        return m_objects.back();
    }
    const auto slot = m_index.try_emplace(params, m_objects.size());
    try
    {
        m_objects.emplace_back(params, collection.get());
    }
    catch (...)
    {
        if (slot.second)
            m_index.erase(slot.first);
        throw;
    }
    collection.release();
    return m_objects.back();
}
'''
next_source = source[:start].replace('#include "object_broker.h"', '#include "object_broker.h"\n#include <memory>', 1) + source[middle:body] + new_body
write(hp, next_header, hraw)
write(cp, next_source, craw)
# Query the immutable VFS catalogue once for both the exact name and
# numbered names. A successful unnumbered open can run VFS work, so it
# must revalidate the numbered plan through the existing path afterward.
player_path = game / "sound_player.cpp"
player_raw = player_path.read_bytes()
player_source = player_raw.replace(b"\r\n", b"\n").decode("utf-8")
before = '''		if (FS.exist(fn,"$game_sounds$",s,".ogg")) {
			ref_sound					*temp_ = add(params.m_type,s);
			if (temp_)
				m_sounds.push_back		(temp_);
		}
        u32 i = 0;
        xr_vector<u32> variants;
        if (FS.find_numbered_sounds(s, params.m_max_count, variants))
'''
after = '''        int exact = 0;
        xr_vector<u32> variants;
        const bool prepared = params.m_max_count >= 16 && params.m_max_count <= 1000 &&
            FS.read_spawn_voice_catalogue(s, &exact, params.m_max_count, &variants);
        const bool unnumbered = prepared ? exact == -1 : FS.exist(fn, "$game_sounds$", s, ".ogg") != nullptr;
        if (unnumbered) {
            if (auto* sound = add(params.m_type, s))
                m_sounds.push_back(sound);
            variants.clear();
        }
        u32 i = 0;
        if ((prepared && !unnumbered) || FS.find_numbered_sounds(s, params.m_max_count, variants))
'''
if player_source.count(before) != 1:
    raise ValueError("Sound collection constructor drift")
write(player_path, player_source.replace(before, after, 1), player_raw)
locator = root / "src/xrCore/LocatorAPI.h"
locator_raw = locator.read_bytes()
locator_text = locator_raw.replace(b"\r\n", b"\n").decode("utf-8")
query = "    bool read_spawn_voice_catalogue(LPCSTR base, int* count, u32 limit, xr_vector<u32>* variants);\n"
anchor = "    int prepared_spawn_voice_count(LPCSTR prefix);"
if locator_text.count(query) != 1 or locator_text.count(anchor) != 1:
    raise ValueError("Voice catalogue declaration drift")
write(locator, locator_text.replace(query, "", 1).replace(anchor, query + anchor, 1), locator_raw)
if fixture:
    fixture.mkdir(parents=True, exist_ok=True)
    player = (game / "sound_player.h").read_text(encoding="utf-8")
    params = player[player.index("	struct CSoundCollectionParams {"):player.index("	struct CSoundCollectionParamsFull")]
    (fixture / "CollectionParams.inc").write_text(params, encoding="utf-8")
    for name, decl, src in (("BaselineStorage", header, source[start:]), ("IndexedStorage", next_header, next_source[next_source.index("CSoundCollectionStorage::~"):])):
        declaration = decl[decl.index("class CSoundCollectionStorage {"):decl.index("extern CSoundCollectionStorage")]
        definition = src
        if name == "BaselineStorage":
            definition = definition.replace("collection_predicate", "BaselinePredicate")
        (fixture / (name + ".inc")).write_text((declaration + definition).replace("CSoundCollectionStorage", name), encoding="utf-8")
