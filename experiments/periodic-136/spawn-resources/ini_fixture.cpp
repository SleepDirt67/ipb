#include "xrCore.h"

#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <string>

struct ScriptConfig : CInifile
{
    explicit ScriptConfig(const char* path) : CInifile(path, TRUE, FALSE, TRUE)
    {
        cached = LoadScriptConfig();
    }

    void makeWritable()
    {
        m_flags.set(eReadOnly, FALSE);
        set_override_names(TRUE);
        save_at_end(FALSE);
    }

    bool cached;
};

void require(bool condition)
{
    if (!condition)
        std::abort();
}

int main()
{
    const auto directory = std::filesystem::absolute("spawn-ini-fixture");
    std::filesystem::remove_all(directory);
    std::filesystem::create_directories(directory);
    auto write = [&](const char* name, const char* body)
    {
        std::ofstream file(directory / name, std::ios::binary | std::ios::trunc);
        file << body;
        require(bool(file));
    };
    write("root.ltx", "[base]\nvalue = first\n[child]:base\nlist = a,b\n");
    write("inc_root.ltx", "#include \"nested.ltx\"\n");
    write("nested.ltx", "[base]\nvalue = child\n");

    Core._initialize("spawn-ini-fixture", nullptr, FALSE, nullptr);
    const auto absolute = directory.string();
    FS.append_path("$fixture$", absolute.c_str(), nullptr, TRUE);
    string_path root;
    FS.update_path(root, "$fixture$", "root.ltx");
    {
        ScriptConfig first(root);
        require(!first.cached && std::strcmp(first.r_string("child", "value"), "first") == 0);
        for (int i = 0; i < 100; ++i)
        {
            ScriptConfig next(root);
            require(next.cached && next.section_count() == first.section_count());
            require(std::strcmp(next.r_string("child", "value"), "first") == 0);
            next.makeWritable();
            next.w_string("child", "value", "mutated");
            require(std::strcmp(next.r_string("child", "value"), "mutated") == 0);
            require(std::strcmp(first.r_string("child", "value"), "first") == 0);
        }
        write("root.ltx", "[base]\nvalue = other\n[child]:base\nlist = a,b\n");
        ScriptConfig changed(root);
        require(!changed.cached && std::strcmp(changed.r_string("child", "value"), "other") == 0);
        ScriptConfig hot(root);
        require(hot.cached);
        write("mod_root_fixture.ltx", "![base]\nvalue = modded\n");
        FS.rescan_path(FS.get_path("$fixture$")->m_Path, TRUE);
        ScriptConfig overridden(root);
        require(!overridden.cached && std::strcmp(overridden.r_string("base", "value"), "modded") == 0);
        string_path include;
        FS.update_path(include, "$fixture$", "inc_root.ltx");
        ScriptConfig nested(include);
        require(!nested.cached && std::strcmp(nested.r_string("base", "value"), "child") == 0);
        write("nested.ltx", "[base]\nvalue = fresh\n");
        ScriptConfig changedNested(include);
        require(!changedNested.cached && std::strcmp(changedNested.r_string("base", "value"), "fresh") == 0);
    }
    Core._destroy();
    std::filesystem::remove_all(directory);
    std::puts("PASS: actual xrCore script INI snapshots, 100 independent writes, equal-size root edit, DLTX add and include edits");
}
