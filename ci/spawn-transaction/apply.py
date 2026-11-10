"""Resolve stock voice names once and reuse the result across native registration."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
bundle = Path(__file__).parent


def edit(path, changes):
    path = root / path
    raw = path.read_bytes()
    text = raw.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in changes:
        if text.count(before) != 1:
            raise ValueError((path, before[:90], text.count(before)))
        text = text.replace(before, after, 1)
    output = text.encode("latin-1")
    if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""):
        output = output.replace(b"\n", b"\r\n")
    path.write_bytes(output)


core = "src/xrCore/"
game = "src/xrGame/"
shutil.copyfile(bundle / "PreparedVoicePath.h", root / (game + "PreparedVoicePath.h"))
edit(core + "SpawnVoiceCatalogue.h", [
    ("class Catalogue\n{\n    struct Entry", "class Catalogue\n{\npublic:\n    struct Entry"),
    ("        std::vector<std::string_view> paths;\n    };",
     """        std::vector<std::string_view> paths;

        int Count() const { return single ? -1 : static_cast<int>(consecutive); }
    };

private:"""),
    ("    Catalogue() = default;",
     """    explicit Catalogue(size_t maxBaseSize = 240) : maxBaseSize_(maxBaseSize) {}

    bool Accepts(size_t size) const { return size <= maxBaseSize_; }

    const Entry* Find(std::string_view base) const
    {
        const auto found = entries_.find(base);
        return found == entries_.end() ? nullptr : &found->second;
    }"""),
    ("    std::unordered_map<std::string, Entry, StringHash, std::equal_to<>> entries_;",
     """    std::unordered_map<std::string, Entry, StringHash, std::equal_to<>> entries_;
    size_t maxBaseSize_;"""),
    ("""        const auto found = entries_.find(base);
        if (found == entries_.end())
            return 0;
        return found->second.single ? -1 : static_cast<int>(found->second.consecutive);""",
     """        const auto* entry = Find(base);
        return entry ? entry->Count() : 0;"""),
])
edit(core + "SpawnVoiceVfs.inc", [
    ("    auto built = std::make_shared<SpawnVoice::Catalogue>();",
     """    const auto maxBaseSize = root.size() + 12 < sizeof(string_path)
        ? sizeof(string_path) - root.size() - 13 : 0;
    auto built = std::make_shared<SpawnVoice::Catalogue>(maxBaseSize);"""),
])
reference = root / (game + "SpawnVoiceApply.inc")
shutil.copyfile(reference, root / "SpawnVoiceReference.inc")
edit(game + "SpawnVoiceApply.inc", [
    ("namespace SpawnVoice\n{", '#include "PreparedVoicePath.h"\n\nnamespace SpawnVoice\n{'),
    ("""    const auto admitted = Scope::Prepared(&object.object());
    if (!admitted || FS.acquire_spawn_voice_catalogue().get() != admitted.get())""",
     """    const auto scoped = Scope::Prepared(&object.object());
    if (!scoped)"""),
    ("""    const char* prefix = object.sound_prefix();
    if (!prefix || std::strlen(prefix) + length > 240)
        return 0;
    std::string base(prefix);
    base.append(path, length);
    int count = FS.prepared_spawn_voice_count(base.c_str());
    if (count == -2)
        return 0;""",
     """    PreparedVoicePath prepared;
    const auto admitted = FS.acquire_spawn_voice_catalogue();
    if (!admitted || admitted.get() != scoped.get() ||
        !prepared.Prepare(*admitted, object.sound_prefix(), {path, length}))
        return 0;"""),
    ("""    const char* currentPrefix = object.sound_prefix();
    if (currentPrefix)
    {
        base.assign(currentPrefix);
        base.append(path, length);
    }
    // Emit the detached path plan when its spelling matches Lua exactly.
    // Reacquire after registration so a changed VFS root or revision cannot
    // publish old filenames. No VFS lock is held across a Lua allocation.
    const auto catalogue = FS.acquire_spawn_voice_catalogue();
    if (catalogue)
    {
        if (const auto* names = catalogue->Paths(base))
        {
            for (size_t i = 0; i < names->size(); ++i)
            {
                const auto& name = (*names)[i];
                lua_pushlstring(L, name.data(), name.size());
                lua_rawseti(L, paths, static_cast<int>(i + 1));
            }
            Scope::Mark(true);
            lua_pushboolean(L, 1);
            return 1;
        }
    }
    count = FS.prepared_spawn_voice_count(base.c_str());""",
     """    const char* currentPrefix = object.sound_prefix();
    const auto catalogue = FS.acquire_spawn_voice_catalogue();
    const bool unchanged = catalogue == admitted && prepared.SamePrefix(currentPrefix, length);
    std::string changedBase;
    if (!unchanged)
    {
        if (currentPrefix)
            changedBase = std::string(currentPrefix).append(path, length);
        else
            changedBase = prepared.Base();
    }

    // No VFS lock is held across a Lua allocation. Both the same snapshot
    // and the same prefix are required before reusing the resolved entry.
    const auto* names = unchanged ? prepared.Paths() : catalogue ? catalogue->Paths(changedBase) : nullptr;
    if (names)
    {
        for (size_t i = 0; i < names->size(); ++i)
        {
            const auto& name = (*names)[i];
            lua_pushlstring(L, name.data(), name.size());
            lua_rawseti(L, paths, static_cast<int>(i + 1));
        }
        Scope::Mark(true);
        lua_pushboolean(L, 1);
        return 1;
    }
    const auto base = unchanged ? prepared.Base() : std::string_view(changedBase);
    int count = unchanged ? prepared.Count() : FS.prepared_spawn_voice_count(changedBase.c_str());"""),
    ("""        if (FS.exist("$game_sounds$", (base + ".ogg").c_str()))""",
     """        if (FS.exist("$game_sounds$", (std::string(base) + ".ogg").c_str()))"""),
    ("""            while (FS.exist("$game_sounds$", (base + std::to_string(count + 1) + ".ogg").c_str()))""",
     """            while (FS.exist("$game_sounds$", (std::string(base) + std::to_string(count + 1) + ".ogg").c_str()))"""),
    ("""        const auto name = base + std::to_string(i);""",
     """        const auto name = std::string(base) + std::to_string(i);"""),
])
edit("ixray_spawn_mainline_replay.cpp", [
    ('#include "src/xrGame/SpawnVoiceApply.inc"',
     '''#include "src/xrGame/SpawnVoiceApply.inc"
#define ReadTalkingType ReadReferenceTalkingType
#define ApplyImpl ApplyReferenceImpl
#define Apply ApplyReference
#define RegisterNativeApply RegisterReferenceApply
#include "SpawnVoiceReference.inc"
#undef RegisterNativeApply
#undef Apply
#undef ApplyImpl
#undef ReadTalkingType

static bool useReference;
static double spawnBatchMs;
static std::chrono::steady_clock::time_point spawnBatchStart;

static int MarkSpawnBatch(lua_State* L)
{
    const auto now = std::chrono::steady_clock::now();
    if (lua_toboolean(L, 1))
        spawnBatchStart = now;
    else
        spawnBatchMs = std::chrono::duration<double, std::milli>(now - spawnBatchStart).count();
    return 0;
}'''),
    ("    SpawnVoice::RegisterNativeApply(L);",
     """    if (useReference)
        SpawnVoice::RegisterReferenceApply(L);
    else
        SpawnVoice::RegisterNativeApply(L);
    lua_pushcfunction(L, MarkSpawnBatch);
    lua_setglobal(L, "mark_spawn_batch");"""),
    ("    unsigned applied;\n};", "    unsigned applied;\n    double batchMs;\n};"),
    ("    Result result{lua_tostring(L, -1), ms, fsCalls, registrations, 0};",
     "    Result result{lua_tostring(L, -1), ms, fsCalls, registrations, 0, spawnBatchMs};"),
    ("    const auto plan = FS.acquire_spawn_voice_catalogue();\n    Require(plan != nullptr, \"immutable VFS snapshot\");",
     """    std::vector<double> referenceCohort, candidateCohort;
    for (unsigned trial = 0; trial < 13; ++trial)
    {
        Result result[2];
        for (unsigned step = 0; step < 2; ++step)
        {
            const auto variant = (trial + step) % 2;
            useReference = variant == 0;
            result[variant] = Replay(argv[3], argv[4], "cohort");
            auto& times = useReference ? referenceCohort : candidateCohort;
            times.push_back(result[variant].batchMs);
        }
        Require(result[0].state == result[1].state && result[0].added == 9 * 569 &&
            result[0].added == result[1].added && result[0].applied == result[1].applied &&
            result[0].fs == result[1].fs, "paired native stock cohort");
    }
    useReference = false;
    std::sort(referenceCohort.begin(), referenceCohort.end());
    std::sort(candidateCohort.begin(), candidateCohort.end());
    std::printf("Paired native 9 x 569 cohort median %.3f -> %.3f ms; max %.3f -> %.3f ms\\n",
        referenceCohort[6], candidateCohort[6], referenceCohort.back(), candidateCohort.back());

    const auto plan = FS.acquire_spawn_voice_catalogue();
    Require(plan != nullptr, "immutable VFS snapshot");"""),
])

# The gameplay capture scanned 330 MiB of short wave data. Keep enough
# verified ranges for that cohort so gameplay compares bytes rather than
# hashing the same ranges on the bind thread. Larger inputs stay bounded.
edit("src/xrSound/SoundRender_Source_loader.cpp", [
    ("constexpr size_t MaxExactWitnessBytes = 128u * 1024 * 1024;",
     "constexpr size_t MaxExactWitnessBytes = 384u * 1024 * 1024;"),
])
