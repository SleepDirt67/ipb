#include "xrCore.h"
#include <cstdlib>
#include <filesystem>
#include <fstream>

static void check(bool condition, const char* label)
{
    if (!condition)
    {
        std::fprintf(stderr, "Failed: %s\n", label);
        std::abort();
    }
}

int main()
{
    const auto root = std::filesystem::absolute("spawn-voice-fixture");
    std::filesystem::remove_all(root);
    std::filesystem::create_directories(root / "voices");
    auto create = [&](const char* path)
    {
        std::ofstream file(root / path, std::ios::binary);
        file << path;
        check(bool(file), path);
    };
    create("voices/line0.ogg");
    create("voices/line1.ogg");
    create("voices/line2.ogg");
    create("voices/line4.ogg");
    create("voices/line03.ogg");

    Core._initialize("spawn-voice-fixture", nullptr, FALSE, nullptr);
    const auto absolute = root.string();
    FS._initialize(CLocatorAPI::flTargetFolderOnly, absolute.c_str(), nullptr);
    FS.append_path("$game_sounds$", absolute.c_str(), nullptr, TRUE);
    check(FS.sound_variant_count("Voices\\LiNe") == 2, "ignore zero and stop at the first hole");
    check(FS.sound_variant_count("voices\\absent") == 0, "absent prefix");
    check(FS.sound_variant_count("") == -2, "unsupported prefix");
    FS.m_Flags.set(CLocatorAPI::flNeedCheck, TRUE);
    check(FS.sound_variant_count("voices\\line") == -2, "pending rescan fallback");
    FS.m_Flags.set(CLocatorAPI::flNeedCheck, FALSE);
    string_path first;
    FS.update_path(first, "$game_sounds$", "voices\\line1.ogg");
    FS.file_delete(first);
    check(FS.sound_variant_count("voices\\line") == 0, "deletion is visible without a cached result");
    create("voices/line.ogg");
    FS.rescan_path(FS.get_path("$game_sounds$")->m_Path, TRUE);
    check(FS.sound_variant_count("voices\\line") == -1, "bare path takes precedence after rescan");
    Core._destroy();
    std::filesystem::remove_all(root);
    std::puts("PASS: native VFS voice paths, gaps, bare precedence, rescan and live delete");
}
