// Called on the loading thread before the first client spawn for this level.
// Use the live ALife snapshot and effective LTX, including overrides.
namespace
{
void AddSpawnVisual(xr_set<xr_string>& visuals, const char* name)
{
    if (!name || !*name)
        return;
    string_path model;
    if (xr_strlen(name) >= sizeof(model) - sizeof(".ogf"))
        return;
    xr_strcpy(model, name);
    xr_strlwr(model);
    if (auto* extension = strext(model))
        *extension = '\0';
    if (*model)
        visuals.emplace(model);
}

void PrepareSpawnVisuals()
{
    if (g_dedicated_server || !IsGameTypeSingle() || !psDeviceFlags.test(rsR4) ||
        Core.ParamsData.test(ECoreParams::noprefetch))
        return;

    const char* enabled = std::getenv("IXRAY_SPAWN_VISUAL_PREPARE");
    if (enabled && xr_strcmp(enabled, "0") == 0)
        return;

    const auto* alife = ai().get_alife();
    const auto* gameGraph = ai().get_game_graph();
    const auto* levelGraph = ai().get_level_graph();
    if (!alife || !gameGraph || !levelGraph)
        return;

    xr_set<xr_string> visuals;
    xr_set<ALife::_OBJECT_ID> visited;
    xr_vector<CSE_ALifeDynamicObject*> objects;
    const auto& registry = alife->objects();
    for (const auto& [id, object] : registry.objects())
    {
        const auto vertex = object->m_tGraphID;
        if (gameGraph->valid_vertex_id(vertex) && gameGraph->vertex(vertex)->level_id() == levelGraph->level_id())
        {
            objects.push_back(object);
            visited.insert(id);
        }
    }

    // Follow owned items even if the child's saved graph vertex is stale.
    for (std::size_t i = 0; i < objects.size(); ++i)
    {
        auto* object = objects[i];
        if (auto* visual = object->visual())
            AddSpawnVisual(visuals, visual->get_visual());
        if (pSettings->line_exist(object->s_name, "visual"))
            AddSpawnVisual(visuals, pSettings->r_string(object->s_name, "visual"));
        if (pSettings->line_exist(object->s_name, "set_visual"))
            AddSpawnVisual(visuals, pSettings->r_string(object->s_name, "set_visual"));

        for (const auto id : object->children)
            if (visited.insert(id).second)
                if (auto* child = registry.object(id, true))
                    objects.push_back(child);
    }

    // PDA sections may be created by a script after the saved registry was loaded.
    // CPda::Load needs the section's visual, including inherited quest variants.
    for (auto* section : pSettings->sections())
    {
        const char* type = nullptr;
        const char* visual = nullptr;
        if (section->line_exist("class", &type) && type &&
            (xr_strcmp(type, "S_PDA") == 0 || xr_strcmp(type, "D_PDA") == 0) &&
            section->line_exist("visual", &visual))
            AddSpawnVisual(visuals, visual);
    }

    CTimer timer;
    timer.Start();
    unsigned prepared = 0;
    for (const auto& model : visuals)
    {
        string_path file, resolved;
        xr_strconcat(file, model.c_str(), ".ogf");
        if (!FS.exist(model.c_str()) && !FS.exist(resolved, "$level$", file) &&
            !FS.exist(resolved, "$game_meshes$", file))
            continue;

        auto* visual = Render->model_Create(model.c_str());
        if (visual)
        {
            Render->model_Delete(visual);
            ++prepared;
        }
    }
    Msg("* spawn visuals: %u of %zu candidates prepared in %.1f ms", prepared, visuals.size(),
        timer.GetElapsed_sec() * 1000.0f);
}
}
