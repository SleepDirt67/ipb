// Called at level load using profiles already present in the ALife registry.
// Prepared bytes remain only a witness. The live reader still validates them.
void PromoteSpawnSoundMetadata(const char* const* prefixes, size_t count)
{
    if (!count || !AudioWarmupEnabled() || !SoundRender || !FS.path_exist("$game_sounds$") ||
        FS.m_Flags.is_any(CLocatorAPI::flBuildCopy | CLocatorAPI::flEBuildCopy | CLocatorAPI::flCacheFiles))
        return;

    try
    {
        const auto pathLength = xr_strlen(FS.get_path("$game_sounds$")->m_Path);
        std::vector<std::string> roots;
        for (size_t index = 0; index < count; ++index)
        {
            string_path path;
            if (!prefixes[index] || !*prefixes[index] || pathLength >= sizeof(path) ||
                std::strlen(prefixes[index]) >= sizeof(path) - pathLength)
                continue;
            FS.update_path(path, "$game_sounds$", prefixes[index]);
            roots.emplace_back(path);
        }
        if (roots.empty())
            return;

        auto& cache = WaveCache();
        std::unique_lock guard(cache.lock);
        using Entry = decltype(cache.entries)::value_type;
        std::vector<Entry*> promote, demote;
        size_t retained = 0;
        for (auto& entry : cache.entries)
        {
            retained += entry.second.witness.ByteCount();
            const bool wanted = std::any_of(roots.begin(), roots.end(), [&](const auto& root) {
                return entry.first.starts_with(root);
            });
            if (wanted && entry.second.verification == PreparedSound::Verification::Ranges)
                promote.push_back(&entry);
            if (!wanted && entry.second.verification == PreparedSound::Verification::Exact)
                demote.push_back(&entry);
        }
        const auto byName = [](const Entry* a, const Entry* b) { return a->first < b->first; };
        std::sort(promote.begin(), promote.end(), byName);
        // Use a stable order for the entries outside the current level cohort.
        std::sort(demote.begin(), demote.end(), [&](const Entry* a, const Entry* b) { return byName(b, a); });
        auto reclaim = demote.begin();
        constexpr size_t readLimit = 64u * 1024 * 1024;
        size_t scanned = 0, promoted = 0, demoted = 0;
        size_t spare = MaxExactWitnessBytes > retained ? MaxExactWitnessBytes - retained : 0;
        for (auto* candidate : promote)
        {
            auto& wave = candidate->second;
            if (wave.fileSize > readLimit - scanned)
                break;
            scanned += wave.fileSize;
            const auto* file = FS.exist(candidate->first.c_str());
            if (!file)
                continue;
            const auto snapshot = ReadSoundSnapshot(candidate->first.c_str(), *file);
            Digest current;
            if (!HashPreparedWave(wave, snapshot.data(), snapshot.size(), current) || current != wave.digest)
                continue;
            auto verified = wave.witness;
            if (!verified.RememberExactBytes(snapshot.data(), snapshot.size()))
                continue;
            const auto needed = verified.ByteCount();
            while (spare < needed && reclaim != demote.end())
            {
                auto& old = (*reclaim++)->second;
                Digest compact;
                if (!SoundRangeDigest::Compute([&](const auto& add) {
                    return old.witness.VisitExactBytes(add);
                }, compact))
                    continue;
                spare += old.witness.ByteCount();
                old.digest = compact;
                old.verification = PreparedSound::Verification::Ranges;
                old.witness.ReleaseExactBytes();
                ++demoted;
            }
            if (spare < needed)
                break;
            spare -= needed;
            wave.witness = std::move(verified);
            wave.verification = PreparedSound::Verification::Exact;
            ++promoted;
        }
        Msg("* spawn level sound inputs: %zu prefixes, %zu promoted, %zu compacted, %zu MiB scanned",
            roots.size(), promoted, demoted, scanned >> 20);
    }
    catch (const std::bad_alloc&)
    {
        // Keep the valid portion of the warmup. Live parsing remains available.
    }
}
