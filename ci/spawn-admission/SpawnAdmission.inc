// Producer-side hints only. The live packet and live physics inputs are
// authoritative. Custom Lua can choose any other position or box.
void CLevel::PrepareALifeSpawn(const CSE_ALifeDynamicObject& object)
{
    if (!spawnActivationWork || IsDemoPlay() || IsDemoSave() || object.ID_Parent != u16(-1) ||
        !smart_cast<const CSE_ALifeHumanStalker*>(&object))
        return;

    const auto* section = *object.s_name;
    if (!pSettings->line_exist(section, "ph_box0_center") ||
        !pSettings->line_exist(section, "ph_box0_size"))
        return;

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
    SpawnPreparation::SubmitActivation(spawnActivationWork, object.ID, centers, count, halfSize);
}
