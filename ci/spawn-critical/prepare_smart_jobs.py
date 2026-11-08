"""Feed stock smart-terrain placement into the detached native activation worker."""
import argparse
from pathlib import Path


def patch(root):
    edits = {}

    def edit(relative, old, new):
        path = root / relative
        original, data = edits.get(path, (None, None))
        if original is None:
            original = path.read_bytes()
            data = original.replace(b"\r\n", b"\n")
        old, new = old.encode(), new.encode()
        if data.count(old) != 1:
            raise ValueError(f"{relative}: expected one patch anchor, found {data.count(old)}")
        edits[path] = original, data.replace(old, new, 1)

    stock = "gamedata/scripts/smart_terrain.script"
    raw = (root / stock).read_bytes().replace(b"\r\n", b"\n")
    edit(stock, "function se_smart_terrain:select_npc_job(npc_info)",
         """local note_spawn_job = ixray_note_spawn_job
local function prepare_spawn_job(smart, npc_info)
    if not note_spawn_job or npc_info.stype ~= modules.stype_stalker then return end
    local job = smart.job_data[npc_info.job_id]
    if job and job.position and job.level_id then
        note_spawn_job(npc_info.se_obj, smart.id, job.level_id, job.position)
    end
end

function se_smart_terrain:select_npc_job(npc_info)""")
    edit(stock, "\t\tnpc_info.job_link = selected_job_link\n",
         "\t\tnpc_info.job_link = selected_job_link\n\t\tprepare_spawn_job(self, npc_info)\n")
    edit(stock, '\tnpc_info.need_job = "nil"\n\n\tlocal obj_storage = db.storage[npc_id]',
         '\tnpc_info.need_job = "nil"\n\tprepare_spawn_job(self, npc_info)\n\n\tlocal obj_storage = db.storage[npc_id]')
    edit(stock, "\t\t\tif npc_info.job_link ~= nil then\n\t\t\t\tself.npc_by_job_section",
         "\t\t\tif npc_info.job_link ~= nil then\n\t\t\t\tprepare_spawn_job(self, npc_info)\n\t\t\t\tself.npc_by_job_section")
    _, prepared = edits.pop(root / stock)

    entity = "src/xrServerEntities/xrServer_Objects_ALife_Monsters"
    edit(entity + ".h", "\tALife::_OBJECT_ID\t\t\t\t\tm_smart_terrain_id;",
         """\tALife::_OBJECT_ID\t\t\t\t\tm_smart_terrain_id;
#ifdef XRGAME_EXPORTS
    // Prediction only, scoped to this server entity. Never serialized.
    u16 spawnPreparationSmart = u16(-1);
    u32 spawnPreparationLevel = u32(-1);
    Fvector spawnPreparationPosition{};
#endif""")
    edit(entity + "_script4.cpp", '#pragma optimize("s",on)',
         """#ifdef XRGAME_EXPORTS
static void NoteSpawnJob(CSE_ALifeMonsterAbstract* monster, u16 smart, u32 level, const Fvector& position)
{
    if (!monster || smart == u16(-1) || monster->m_smart_terrain_id != smart || !_valid(position))
        return;

    monster->spawnPreparationSmart = smart;
    monster->spawnPreparationLevel = level;
    monster->spawnPreparationPosition = position;
}
#endif

#pragma optimize("s",on)""")
    edit(entity + "_script4.cpp", '\t\t.def("force_set_goodwill",\t\t\t\t&ForceSetGoodwill)\n#endif // #ifdef XRGAME_EXPORTS\n\t];',
         '''\t\t.def("force_set_goodwill",\t\t\t\t&ForceSetGoodwill),
        def("ixray_note_spawn_job", &NoteSpawnJob)
#endif // #ifdef XRGAME_EXPORTS
\t];''')
    storage = "src/xrScripts/script_storage.cpp"
    edit(storage, '#include "PreparedStockLogic.inc"',
         '#include "PreparedStockLogic.inc"\n#include "PreparedSmartJobs.inc"')
    edit(storage, "std::string PrepareCompatibleLogic(std::string_view data)",
         """std::string_view PrepareStockSmartJobs(std::string_view data)
{
    static const bool enabled = [] {
        const auto* setting = std::getenv("IXRAY_SPAWN_PREPARE");
        return setting && xr_strcmp(setting, "1") == 0;
    }();
    if (!enabled || data.size() < sizeof(stockSmartJobs) || data.size() > 2 * sizeof(stockSmartJobs))
        return {};

    size_t index = 0;
    for (size_t offset = 0; offset < data.size(); ++offset)
    {
        if (data[offset] == '\\r' && offset + 1 < data.size() && data[offset + 1] == '\\n')
            continue;
        if (index == sizeof(stockSmartJobs) || static_cast<unsigned char>(data[offset]) != stockSmartJobs[index++])
            return {};
    }
    return index == sizeof(stockSmartJobs) ? Source(preparedSmartJobs) : std::string_view{};
}

std::string PrepareCompatibleLogic(std::string_view data)""")
    edit(storage, '        if (!prepared.empty())\n            Msg("* xr_logic: prepared stock condition programs");',
         '''        if (!prepared.empty())
            Msg("* xr_logic: prepared stock condition programs");
        else if (caNameSpaceName && xr_strcmp(caNameSpaceName, "smart_terrain") == 0)
        {
            prepared = PrepareStockSmartJobs(original);
            if (!prepared.empty())
                Msg("* smart_terrain: stock job position preparation enabled");
        }''')

    admission = "src/xrGame/SpawnAdmission.inc"
    edit(admission, """    if (!spawnActivationWork || IsDemoPlay() || IsDemoSave() || object.ID_Parent != u16(-1) ||
        !smart_cast<const CSE_ALifeHumanStalker*>(&object))
        return false;""",
         """    if (!spawnActivationWork || IsDemoPlay() || IsDemoSave() || object.ID_Parent != u16(-1))
        return false;
    const auto* stalker = smart_cast<const CSE_ALifeHumanStalker*>(&object);
    if (!stalker)
        return false;""")
    edit(admission, "    Fvector centers[3];", "    Fvector centers[4];")
    edit(admission, """    if (const auto* graph = ai().get_level_graph(); graph && graph->valid_vertex_id(object.m_tNodeID))""",
         """    const auto* graph = ai().get_level_graph();
    if (graph && stalker->spawnPreparationSmart != u16(-1) &&
        stalker->spawnPreparationSmart == stalker->m_smart_terrain_id &&
        stalker->spawnPreparationLevel == graph->level_id())
        add(stalker->spawnPreparationPosition);
    if (graph && graph->valid_vertex_id(object.m_tNodeID))""")
    edit("src/xrPhysics/SpawnPreparedGeometry.h", "constexpr unsigned maxPoses = 3;",
         "constexpr unsigned maxPoses = 4;")
    fixture = "ixray_spawn_admission_fixture.cpp"
    edit(fixture,
         "    Inputs input{&model, {Fvector{0, -.1f, 0}, Fvector{7, 1, 7}}, {.4f, .6f, .4f}, 1.3f, 2, _mm_getcsr()};",
         """    Inputs input{&model,
        {Fvector{0, -.1f, 0}, Fvector{7, 1, 7}, Fvector{9, 1, 9}, Fvector{.7f, -.1f, .7f}},
        {.4f, .6f, .4f}, 1.3f, maxPoses, _mm_getcsr()};""")
    edit(fixture, "    for (const auto& center : {input.centers[0], input.centers[1]})",
         "    for (const auto& center : input.centers)")
    for path, (original, data) in edits.items():
        if b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b""):
            data = data.replace(b"\n", b"\r\n")
        path.write_bytes(data)

    def byte_array(name, data):
        rows = [", ".join(str(x) for x in data[i:i+32]) for i in range(0, len(data), 32)]
        return "static constexpr unsigned char " + name + "[] = {\n" + ",\n".join(rows) + "\n};\n"

    (root / "src/xrScripts/PreparedSmartJobs.inc").write_text(
        byte_array("stockSmartJobs", raw) + byte_array("preparedSmartJobs", prepared), encoding="ascii")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("engine", type=Path)
    patch(cli.parse_args().engine)
