namespace
{
struct ReplayCollection;
struct CSoundPlayer
{
#include "CollectionParams.inc"
    using CSoundCollection = ReplayCollection;
};
using CohortSoundParams = CSoundPlayer::CSoundCollectionParams;
using ref_sound = bool;

std::unordered_set<std::string> cohortSources;
unsigned cohortOpens;
std::uint64_t cohortCollectionOrder;
constexpr std::uint64_t orderSeed = 14695981039346656037ull;

std::uint64_t HashText(std::uint64_t hash, const char* text)
{
    while (*text)
        hash = (hash ^ static_cast<unsigned char>(*text++)) * 1099511628211ull;
    return hash * 1099511628211ull;
}
bool indexedCollections;

struct ReplayCollection
{
    u32 m_last_sound_id;
    std::uint64_t variantOrder = orderSeed;
    xr_vector<ref_sound*> m_sounds;
    explicit ReplayCollection(const CohortSoundParams& params)
    {
        if (indexedCollections)
            BuildIndexed(params);
        else
            BuildOriginal(params);
        if (!m_sounds.empty())
            cohortCollectionOrder += HashText(HashText(variantOrder, *params.m_sound_prefix), *params.m_sound_player_prefix);
    }
    void BuildOriginal(const CohortSoundParams& params);
    void BuildIndexed(const CohortSoundParams& params);
    void seed(u32) {}
    ref_sound* add(ESoundTypes, const char* name)
    {
        static ref_sound value = true;
        variantOrder = HashText(variantOrder, name);
        if (!cohortSources.emplace(name).second)
            return &value;
        const std::string file = std::string(name) + ".ogg";
        auto* reader = FS.r_open("$game_sounds$", file.c_str());
        Require(reader && reader->length() == 8192 && reader->r_u8() == 91, "real packed wave read");
        FS.r_close(reader);
        ++cohortOpens;
        return &value;
    }
};
#include "BuildOriginal.inc"
#include "BuildIndexed.inc"
template<class Vector> void DeleteReplayCollections(Vector& pairs)
{
    for (auto& pair : pairs) delete pair.second;
}
#include "BaselineStorage.inc"
#include "IndexedStorage.inc"
std::unique_ptr<BaselineStorage> baselineStorage;
std::unique_ptr<IndexedStorage> indexedStorage;

const ReplayCollection& ResolveCollection(const CohortSoundParams& params)
{
    if (indexedCollections)
        return *indexedStorage->object(params).second;
    return *baselineStorage->object(params).second;
}
}

unsigned ResolveCohortSound(const char* prefix, const char* name, unsigned maximum)
{
    const CohortSoundParams parameters{name, prefix, maximum, SOUND_TYPE_TALKING};
    return static_cast<unsigned>(ResolveCollection(parameters).m_sounds.size());
}

static int ReadCohortItem(lua_State* L)
{
    const auto* name = luaL_checkstring(L, 1);
    auto* reader = FS.r_open("$game_sounds$", name);
    Require(reader && reader->length() == 8192 && reader->r_u8() == 91, "owned resource bytes");
    FS.r_close(reader);
    ++cohortOpens;
    return 0;
}

// The game already has a long-lived VM when a batch arrives. Group the
// roots to avoid adding one large Lua table as an artificial atomic task.
static void SeedCohortGc(lua_State* L, unsigned count, unsigned trial)
{
    if (!count)
        return;
    lua_gc(L, LUA_GCSTOP, 0);
    constexpr unsigned groupSize = 96;
    const unsigned groups = (count + groupSize - 1) / groupSize;
    lua_createtable(L, static_cast<int>(groups), 0);
    const int roots = lua_gettop(L);
    uint32_t random = 1;
    const auto bytes = [&]() {
        random = random * 1664525u + 1013904223u;
        return 8u + ((random >> 18) & 31u) * 16u;
    };
    for (unsigned group = 0; group < groups; ++group)
    {
        const auto size = std::min(groupSize, count);
        lua_createtable(L, static_cast<int>(size), 0);
        const int slots = lua_gettop(L);
        for (unsigned slot = 1; slot <= size; ++slot)
        {
            lua_newuserdata(L, bytes());
            lua_rawseti(L, slots, static_cast<int>(slot));
            if (slot % 5 == 0)
            {
                lua_newuserdata(L, bytes());
                lua_pop(L, 1);
            }
        }
        lua_rawseti(L, roots, static_cast<int>(group + 1));
        count -= size;
    }
    lua_setglobal(L, "fixture_gc_roots");
    lua_gc(L, LUA_GCCOLLECT, 0);
    // Sweep across initial GC phases instead of choosing one phase which
    // favors a runtime. Both DLLs receive the same number of stock steps.
    for (unsigned step = 0; step < trial * 20; ++step)
        lua_gc(L, LUA_GCSTEP, 0);
}

static int RunCohort(const char* voice, const char* themes, const char* files, const char* input)
{
    const auto root = std::filesystem::absolute("cohort-spawn-replay");
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root);
    const auto directory = root.string();
    Core._initialize("cohort-spawn-replay", nullptr, FALSE, nullptr);
    luabind::allocator = &ReplayLuabindAllocator;
    luabind::allocator_parameter = nullptr;
    FS._initialize(CLocatorAPI::flTargetFolderOnly, directory.c_str(), nullptr);
    FS.append_path("$game_sounds$", directory.c_str(), nullptr, TRUE);

    CMemoryWriter archive, index;
    const std::vector<u8> body(8192, 91);
    archive.open_chunk(0);
    std::ifstream manifest(files);
    std::string name;
    unsigned entries = 0;
    auto add = [&](const std::string& path) {
        const auto offset = static_cast<u32>(archive.tell());
        archive.w(body.data(), static_cast<u32>(body.size()));
        index.w_u16(static_cast<u16>(4 * sizeof(u32) + path.size()));
        index.w_u32(static_cast<u32>(body.size()));
        index.w_u32(static_cast<u32>(body.size()));
        index.w_u32(0);
        index.w(path.data(), static_cast<u32>(path.size()));
        index.w_u32(offset);
        ++entries;
    };
    while (std::getline(manifest, name))
        add(name);
    while (entries < 11677)
        add("characters_voice\\unrelated\\other_" + std::to_string(entries) + ".ogg");
    archive.close_chunk();
    archive.w_chunk(1, index.pointer(), index.size());
    const auto db = (root / "replay.xdb").string();
    Require(archive.save_to(db.c_str()), "mount cohort archive");
    auto& mounted = FS.m_archives.emplace_back();
    mounted.path = db.c_str();
    mounted.vfs_idx = static_cast<u32>(FS.m_archives.size() - 1);
    const auto prefix = directory + "\\";
    FS.LoadArchive(mounted, prefix.c_str());
    FS.prepare_spawn_voice_catalogue();
    admittedPlan = FS.acquire_spawn_voice_catalogue();

    const char* pressure = std::getenv("IXRAY_REPLAY_LIVE_USERDATA");
    const auto userdata = pressure ? static_cast<unsigned>(std::strtoul(pressure, nullptr, 10)) : 0;
    Require(userdata <= 480000, "bounded fixture heap");
    const auto* indexed = std::getenv("IXRAY_REPLAY_INDEXED");
    indexedCollections = indexed && indexed[0] == '1';
    const auto* registered = std::getenv("IXRAY_REPLAY_REGISTERED");
    const auto priorKeys = registered ? static_cast<unsigned>(std::strtoul(registered, nullptr, 10)) : 6828;
    Require(priorKeys <= 6828, "bounded fixture registry");
    std::vector<double> cold, warm;
    unsigned checksum = 0, measuredOpens = 0;
    std::uint64_t orderChecksum = 0;
    for (unsigned trial = 0; trial < 15; ++trial)
    {
        auto* L = luaL_newstate();
        Require(L != nullptr, "fresh script VM");
        luaL_openlibs(L);
        Register(L);
        lua_pushcfunction(L, ReadCohortItem);
        lua_setglobal(L, "read_cohort_item");
        lua_pushstring(L, voice);
        lua_setglobal(L, "voice_file");
        lua_pushstring(L, themes);
        lua_setglobal(L, "themes_file");
        Load(L, input, true);
        SeedCohortGc(L, userdata, trial);

        cohortSources.clear();
        if (indexedCollections)
            indexedStorage = std::make_unique<IndexedStorage>();
        else
            baselineStorage = std::make_unique<BaselineStorage>();
        // Model a played session with thousands of distinct existing keys.
        for (unsigned i = 0; i < priorKeys; ++i)
        {
            const auto id = "fixture_previous_" + std::to_string(i);
            ResolveCollection({id.c_str(), "characters_voice\\cohort_0\\", 64, SOUND_TYPE_TALKING});
        }
        cohortOpens = 0;
        cohortCollectionOrder = 0;
        cohortApplied = 0;
        const auto start = std::chrono::steady_clock::now();
        Load(L, "run_cohort()", false);
        const auto bound = std::chrono::steady_clock::now();
        cold.push_back(std::chrono::duration<double, std::milli>(bound - start).count());
        measuredOpens = cohortOpens;
        if (trial)
            Require(orderChecksum == cohortCollectionOrder, "repeat collection variant order");
        orderChecksum = cohortCollectionOrder;
        Require(registrations == 569 * 9, "stock registration count");
        Require(cohortApplied == (admittedPlan ? 569 * 9 : 0), "native phase coverage");
        registrations = 0;
        Load(L, "replay_sum = compare_cohort()", false);
        lua_getglobal(L, "replay_sum");
        checksum = static_cast<unsigned>(lua_tointeger(L, -1));
        lua_pop(L, 1);
        const auto restart = std::chrono::steady_clock::now();
        Load(L, "run_cohort()", false);
        warm.push_back(std::chrono::duration<double, std::milli>(
            std::chrono::steady_clock::now() - restart).count());
        Require(registrations == 569 * 9, "warm registration count");
        registrations = 0;
        lua_close(L);
        baselineStorage.reset();
        indexedStorage.reset();
    }
    for (unsigned trial = 0; trial < cold.size(); ++trial)
        std::printf("REPLAY: prior %u, live %u, trial %u, cold %.3f ms, warm %.3f ms\n",
            priorKeys, userdata, trial, cold[trial], warm[trial]);
    std::sort(cold.begin(), cold.end());
    std::sort(warm.begin(), warm.end());
    std::printf("COHORT: 9 x 569 themes, 29 item reads, %u real opens, state %u, order %llu, cold %.3f ms, warm %.3f ms\n",
        measuredOpens, checksum, static_cast<unsigned long long>(orderChecksum), cold[cold.size() / 2], warm[warm.size() / 2]);
    admittedPlan.reset();
    FS._destroy();
    Core._destroy();
    std::filesystem::remove_all(root);
    return 0;
}
