namespace
{
struct IniSnapshot
{
    std::string bytes;
    xr_vector<CInifile::Sect> sections;
};

struct ScriptIniCache
{
    std::mutex lock;
    std::unordered_map<std::string, IniSnapshot> entries;
};

ScriptIniCache& ScriptIniSnapshots()
{
    static ScriptIniCache cache;
    return cache;
}

bool ScriptIniCacheEnabled()
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_SCRIPT_INI_CACHE");
        return !setting || std::strcmp(setting, "0") != 0;
    }();
    return enabled;
}
}

void ClearScriptIniSnapshots()
{
    auto& cache = ScriptIniSnapshots();
    std::lock_guard guard(cache.lock);
    cache.entries.clear();
}

bool CInifile::LoadScriptConfig()
{
    string_path path, folder;
    _splitpath(m_file_name, path, folder, 0, 0);
    xr_strcat(path, sizeof(path), folder);
    struct CloseReader
    {
        void operator()(IReader* reader) const { FS.r_close(reader); }
    };
    std::unique_ptr<IReader, CloseReader> reader(FS.r_open(m_file_name));
    if (!reader)
        return false;

    const auto original = [&] { Load(reader.get(), path); };
    if (!ScriptIniCacheEnabled() || !m_flags.test(eReadOnly) || !DATA.empty() ||
        !reader->length() || reader->length() > 256 * 1024 ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
    {
        original();
        return false;
    }

    const std::string_view bytes(static_cast<const char*>(reader->pointer()), reader->length());
    // Fall back for includes, explicit overrides, and any possible implicit
    // DLTX override. Recheck discovery even on cache hits.
    if (bytes.find_first_of("#!") != std::string_view::npos)
    {
        original();
        return false;
    }

    string256 drive, directory, stem;
    _splitpath_s(m_file_name, drive, sizeof(drive), directory, sizeof(directory),
        stem, sizeof(stem), nullptr, 0);
    const auto mask = xr_string("mod_") + stem + "_*.ltx";
    const auto modPath = xr_string(drive) + directory;
    FS_FileSet overrides;
    FS.file_list(overrides, modPath.c_str(), FS_ListFiles, mask.c_str());
    if (!overrides.empty())
    {
        original();
        return false;
    }

    auto& cache = ScriptIniSnapshots();
    const std::string name(m_file_name);
    {
        std::lock_guard guard(cache.lock);
        auto it = cache.entries.find(name);
        if (it != cache.entries.end() && it->second.bytes == bytes)
        {
            // Each script object owns independent mutable sections, including
            // when set_readonly(false) or remove_line is subsequently called.
            DATA.reserve(it->second.sections.size());
            for (const auto& section : it->second.sections)
                DATA.push_back(new Sect(section));
            return true;
        }
    }

    IniSnapshot snapshot;
    snapshot.bytes.assign(bytes);
    IReader stable(snapshot.bytes.data(), snapshot.bytes.size());
    Load(&stable, path);
    snapshot.sections.reserve(DATA.size());
    for (const auto* section : DATA)
        snapshot.sections.push_back(*section);
    {
        std::lock_guard guard(cache.lock);
        if (cache.entries.size() >= 32)
            cache.entries.clear();
        cache.entries.insert_or_assign(name, std::move(snapshot));
    }
    return false;
}
