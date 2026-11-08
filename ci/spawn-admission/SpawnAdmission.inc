// Producer-side hints only. The live packet and live physics inputs are
// authoritative. Custom Lua can choose any other position or box.
bool CLevel::PrepareALifeSpawn(const CSE_ALifeDynamicObject& object, bool speculative)
{
    if (!spawnActivationWork || IsDemoPlay() || IsDemoSave() || object.ID_Parent != u16(-1) ||
        !smart_cast<const CSE_ALifeHumanStalker*>(&object))
        return false;

    const auto* section = *object.s_name;
    if (!pSettings->line_exist(section, "ph_box0_center") ||
        !pSettings->line_exist(section, "ph_box0_size"))
        return false;

    const Fvector boxCenter = pSettings->r_fvector3(section, "ph_box0_center");
    const Fvector boxSize = pSettings->r_fvector3(section, "ph_box0_size");
    Fbox box;
    box.set(boxCenter, boxCenter);
    box.grow(boxSize);
    Fvector shift, halfSize;
    box.get_CD(shift, halfSize);

    Fvector centers[3];
    unsigned count = 0;
    const auto add = [&](const Fvector& position)
    {
        Fvector center;
        center.add(shift, position);
        for (unsigned i = 0; i < count; ++i)
            if (centers[i].x == center.x && centers[i].y == center.y && centers[i].z == center.z)
                return;
        centers[count++] = center;
    };
    add(object.o_Position);
    if (const auto* graph = ai().get_level_graph(); graph && graph->valid_vertex_id(object.m_tNodeID))
    {
        const auto node = object.m_tNodeID;
        if (graph->inside(node, object.o_Position))
        {
            Fvector floor = object.o_Position;
            floor.y = EPS_L + graph->vertex_plane_y(*graph->vertex(node), floor.x, floor.z);
            add(floor);
        }
        add(graph->vertex_position(node));
    }
    SpawnPreparation::SubmitActivation(spawnActivationWork, object.ID, centers, count, halfSize, speculative);
    return true;
}

void CLevel::PrepareALifeSpawns(const CALifeLevelRegistry& registry,
    const Fvector& actorPosition, float onlineDistance)
{
    if (!spawnActivationWork || IsDemoPlay() || IsDemoSave())
        return;
    const auto& objects = registry.objects();
    auto candidate = objects.upper_bound(spawnPreparationCursor);
    unsigned requests = 0;
    const auto scanCount = std::min<std::size_t>(objects.size(), 32);
    constexpr float anticipationDistance = 12.f;
    const float limit = onlineDistance + anticipationDistance;
    for (std::size_t scanned = 0; scanned < scanCount && requests < 4; ++scanned, ++candidate)
    {
        if (candidate == objects.end())
            candidate = objects.begin();
        const auto& [id, object] = *candidate;
        spawnPreparationCursor = id;
        if (object->ID_Parent != u16(-1))
            continue;
        const bool withinRange = actorPosition.distance_to_sqr(object->o_Position) <= limit * limit;
        if (!withinRange && !object->m_bOnline)
            continue;
        if (const auto* group = smart_cast<const CSE_ALifeOnlineOfflineGroup*>(object))
        {
            unsigned examined = 0;
            for (const auto& entry : group->squad_members())
            {
                const auto* member = entry.second;
                if (++examined > 8)
                    break;
                const bool pending = member->m_bOnline && !Objects.net_Find(member->ID);
                if ((pending || (withinRange && !member->m_bOnline)) &&
                    PrepareALifeSpawn(*member, !pending))
                    ++requests;
                if (requests == 4)
                    break;
            }
        }
        else
        {
            const bool pending = object->m_bOnline && !Objects.net_Find(object->ID);
            if ((pending || (withinRange && !object->m_bOnline)) &&
                PrepareALifeSpawn(*object, !pending))
                ++requests;
        }
    }
}
