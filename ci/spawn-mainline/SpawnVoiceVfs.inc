namespace
{
struct SpawnVoiceIndex
{
    std::shared_mutex mutex;
    const CLocatorAPI* owner = nullptr;
    std::string root;
    std::shared_ptr<const SpawnVoice::Catalogue> catalogue;
    u64 revision = 0;
    bool ready = false;

    void Invalidate(const CLocatorAPI* fs, std::string_view file)
    {
        if (!file.ends_with(".ogg"))
            return;
        std::unique_lock guard(mutex);
        if (owner == fs && file.starts_with(root))
        {
            ++revision;
            ready = false;
        }
    }

    void Reset(const CLocatorAPI* fs)
    {
        std::unique_lock guard(mutex);
        if (owner == fs)
        {
            ++revision;
            owner = nullptr;
            root.clear();
            catalogue.reset();
            ready = false;
        }
    }
};
SpawnVoiceIndex spawnVoiceIndex;
}

void CLocatorAPI::prepare_spawn_voice_catalogue() try
{
    const char* admission = std::getenv("IXRAY_SPAWN_PREPARE");
    const char* disabled = std::getenv("IXRAY_SPAWN_VOICE_PLAN");
    if (!admission || xr_strcmp(admission, "1") != 0 ||
        (disabled && xr_strcmp(disabled, "0") == 0) || !path_exist("$game_sounds$"))
        return;
    check_pathes();
    const std::string root = get_path("$game_sounds$")->m_Path;
    u64 revision;
    {
        std::unique_lock guard(spawnVoiceIndex.mutex);
        if (spawnVoiceIndex.owner == this && spawnVoiceIndex.root == root && spawnVoiceIndex.ready)
            return;
        spawnVoiceIndex.owner = this;
        spawnVoiceIndex.root = root;
        spawnVoiceIndex.ready = false;
        revision = ++spawnVoiceIndex.revision;
    }
    auto built = std::make_shared<SpawnVoice::Catalogue>();
    file first{};
    first.name = root.c_str();
    size_t files = 0;
    for (auto it = m_files.lower_bound(first); it != m_files.end(); ++it)
    {
        const std::string_view path(it->name);
        if (!path.starts_with(root))
            break;
        const auto name = path.substr(root.size());
        if (!name.starts_with("characters_voice\\") || !name.ends_with(".ogg"))
            continue;
        built->Add(name);
        ++files;
    }
    built->Finish();
    {
        std::unique_lock guard(spawnVoiceIndex.mutex);
        if (spawnVoiceIndex.revision != revision)
            return;
        spawnVoiceIndex.catalogue = std::move(built);
        spawnVoiceIndex.ready = true;
    }
    Msg("* spawn voice catalogue: prepared from %zu VFS entries", files);
}
catch (const std::bad_alloc&)
{
    // No incomplete catalogue is published. The original binder handles it.
}

bool CLocatorAPI::read_spawn_voice_catalogue(LPCSTR base, int* count, u32 limit, xr_vector<u32>* variants)
{
    if (!base || !path_exist("$game_sounds$") ||
        m_Flags.is_any(flNeedRescan | flNeedCheck | flEventNotificator | flBuildCopy | flEBuildCopy | flCacheFiles))
        return false;
    const auto* root = get_path("$game_sounds$")->m_Path;
    const size_t size = xr_strlen(base);
    if (!size || size > 240 || xr_strlen(root) + size + 12 >= sizeof(string_path))
        return false;
    string256 normalized;
    xr_strcpy(normalized, base);
    xr_strlwr(normalized);
    const std::string_view key(normalized);
    if (!key.starts_with("characters_voice\\"))
        return false;

    std::shared_lock guard(spawnVoiceIndex.mutex);
    if (!spawnVoiceIndex.ready || spawnVoiceIndex.owner != this || spawnVoiceIndex.root != root)
        return false;
    if (count)
        *count = spawnVoiceIndex.catalogue->Count(key);
    if (variants)
        spawnVoiceIndex.catalogue->CopyNumbered(key, limit, *variants);
    return true;
}

int CLocatorAPI::prepared_spawn_voice_count(LPCSTR base)
{
    int count;
    return read_spawn_voice_catalogue(base, &count, 0, nullptr) ? count : -2;
}

std::shared_ptr<const SpawnVoice::Catalogue> CLocatorAPI::acquire_spawn_voice_catalogue()
{
    if (!path_exist("$game_sounds$") ||
        m_Flags.is_any(flNeedRescan | flNeedCheck | flEventNotificator | flBuildCopy | flEBuildCopy | flCacheFiles))
        return {};
    const auto* root = get_path("$game_sounds$")->m_Path;
    std::shared_lock guard(spawnVoiceIndex.mutex);
    if (!spawnVoiceIndex.ready || spawnVoiceIndex.owner != this || spawnVoiceIndex.root != root)
        return {};
    return spawnVoiceIndex.catalogue;
}
