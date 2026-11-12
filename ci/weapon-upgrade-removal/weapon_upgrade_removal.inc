bool CWeapon::RemoveInstalledUpgrade(const shared_str& upgrade_id)
{
    if (!IsGameTypeSingle() || !Actor() || !Actor()->g_Alive() ||
        H_Parent() != Actor() || !ai().get_alife() || m_saving_upgrade_removal)
        return false;

    auto* manager = Level().m_upgrade_manager;
    auto& alife = *ai().get_alife();
    auto* server = smart_cast<CSE_ALifeItemWeapon*>(alife.objects().object(object_id(), true));
    if (!manager || !server)
        return false;

    const auto selected = std::find(m_upgrades.begin(), m_upgrades.end(), upgrade_id);
    if (selected == m_upgrades.end())
        return false;

    for (const auto& installed : m_upgrades)
        if (!manager->get_upgrade(installed) || !manager->get_upgrade(installed)->parent_group())
            return false;

    // Use the same dependency rule as installation, including the configured
    // legacy/non-legacy group semantics. Restore the live list before any I/O.
    Upgrades_type original = m_upgrades;
    m_upgrades.erase(selected);
    for (;;)
    {
        const auto orphan = std::find_if(m_upgrades.begin(), m_upgrades.end(),
            [this, manager](const shared_str& id)
            {
                auto* upgrade = manager->get_upgrade(id);
                auto* group = const_cast<inventory::upgrade::Group*>(upgrade->parent_group());
                return group->can_install(*this, *upgrade, false) == inventory::upgrade::result_e_parents;
            });
        if (orphan == m_upgrades.end())
            break;
        m_upgrades.erase(orphan);
    }
    m_upgrades.swap(original); // original now contains the retained list
    const Upgrades_type& retained = original;

    const auto still_installed = [&retained](const shared_str& id)
    {
        return std::find(retained.begin(), retained.end(), id) != retained.end();
    };
    const auto factory = READ_IF_EXISTS(pSettings, r_string, cNameSect().c_str(), "installed_upgrades", "");
    if (factory && *factory)
    {
        string512 id = {};
        for (int i = 0, count = _GetItemCount(factory); i < count; ++i)
        {
            _GetItem(factory, i, id, sizeof(id));
            if (!still_installed(shared_str(id)))
                return false;
        }
    }

    // Both primary and auxiliary magazines must be empty. A caliber or addon
    // upgrade can change the meaning of the serialized indices and flags.
    const auto* underbarrel = cast_weapon_magazined_w_grenade();
    if (GetAmmoElapsed() || GetAmmoChamberElapsed() || IsGrenadeMode() ||
        (underbarrel && !underbarrel->m_magazine2.empty()) ||
        GetAddonsState() || IsZoomed())
        return false;

    bool has_save_status = false;
    const char* save_status = nullptr;
    LoadCallbackGlobals(has_save_status, save_status, "OnSaveStatus");
    if (has_save_status)
    {
        luabind::functor<bool> allowed;
        if (!ai().script_engine().functor(save_status, allowed) || !allowed())
            return false;
    }

    // Each removal gets a fresh slot. If the checkpoint fails validation,
    // leave the running game and existing saves intact.
    string64 checkpoint;
    for (unsigned suffix = 0;; ++suffix)
    {
        xr_sprintf(checkpoint, "weapon_upgrade_%u_%u", Device.dwTimeGlobal, suffix);
        if (!CSavedGameWrapper::saved_game_exist(checkpoint))
            break;
    }
    const auto* saves = FS.get_path("$game_saves$");
    if (!saves || xr_strlen(saves->m_Path) + xr_strlen(checkpoint) +
        xr_strlen(IXRAY_DEF_SAVE_EXTENSION) + 5 >= sizeof(string_path))
        return false;

    LPCSTR fire_modes = READ_IF_EXISTS(pSettings, r_string, cNameSect().c_str(), "fire_modes", nullptr);
    for (const auto& id : retained)
    {
        const auto section = manager->get_upgrade(id)->section();
        if (pSettings->line_exist(section, "fire_modes"))
            fire_modes = pSettings->r_string(section, "fire_modes");
    }
    string16 first_mode = {};
    if (fire_modes && *fire_modes)
        _GetItem(fire_modes, 0, first_mode, sizeof(first_mode));
    m_upgrade_removal_first_mode = *first_mode ? static_cast<s8>(atoi(first_mode)) : 1;

    Level().ClientSend();
    auto previous_client_data = server->client_data;
    m_saving_upgrade_removal = true;
    Level().ClientSave();
    m_saving_upgrade_removal = false;

    // ClientSave stores the local weapon payload. The server writes a
    // separate spawn payload. Normalize the same selectors in both.
    auto server_upgrades = server->m_upgrades;
    const auto old_ammo = server->ammo_type;
    const auto old_loaded_ammo = server->a_elapsed;
    const auto old_loaded_chamber = server->a_chamber_elapsed;
    const auto old_addons = server->m_addon_flags;
    const auto old_condition = server->m_fCondition;
    const auto old_chamber = server->chamber_ammo_type;
    const auto old_scope = server->cur_scope;
    const auto old_zoom = server->rt_zoom_factor;
    const auto old_grenades = server->a_elapsed_grenades;
    server->m_upgrades = retained;
    server->ammo_type = 0;
    server->a_elapsed = 0;
    server->a_chamber_elapsed = 0;
    server->m_addon_flags.zero();
    server->m_fCondition = GetCondition();
    server->chamber_ammo_type = 0;
    server->cur_scope = 0;
    server->rt_zoom_factor = 0.0f;
    server->a_elapsed_grenades.unpack_from_byte(0);
    alife.save(checkpoint, false);
    server->client_data.swap(previous_client_data);
    server->m_upgrades.swap(server_upgrades);
    server->ammo_type = old_ammo;
    server->a_elapsed = old_loaded_ammo;
    server->a_chamber_elapsed = old_loaded_chamber;
    server->m_addon_flags = old_addons;
    server->m_fCondition = old_condition;
    server->chamber_ammo_type = old_chamber;
    server->cur_scope = old_scope;
    server->rt_zoom_factor = old_zoom;
    server->a_elapsed_grenades = old_grenades;

    if (!CSavedGameWrapper::saved_game_exist(checkpoint) || !CSavedGameWrapper::valid_saved_game(checkpoint))
        return false;

    string128 command;
    xr_sprintf(command, "load %s", checkpoint);
    Console->Execute(command);
    return true;
}
