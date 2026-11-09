"""Enable the prepared gameplay path and give its voice state a separate lifetime."""
import argparse
from pathlib import Path
import shutil


def edit(path, before, after):
    raw = path.read_bytes()
    source = raw.replace(b"\r\n", b"\n")
    before, after = before.encode(), after.encode()
    if source.count(before) != 1:
        raise ValueError((path, before[:100], source.count(before)))
    result = source.replace(before, after, 1)
    if b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b""):
        result = result.replace(b"\n", b"\r\n")
    path.write_bytes(result)


def patch(root):
    game = root / "src/xrGame"
    core = root / "src/xrCore"
    physics = root / "src/xrPhysics"
    shutil.copyfile(Path(__file__).with_name("SpawnPreparationConfig.h"), core / "SpawnPreparationConfig.h")

    old_gate = '''    const char* admission = std::getenv("IXRAY_SPAWN_PREPARE");
    const char* disabled = std::getenv("IXRAY_SPAWN_VOICE_PLAN");
    if (!admission || xr_strcmp(admission, "1") != 0 ||'''
    new_gate = '''    const char* disabled = std::getenv("IXRAY_SPAWN_VOICE_PLAN");
    if (!SpawnPreparation::Requested() ||'''
    for path, include in [(core / "SpawnVoiceVfs.inc", '#include "SpawnPreparationConfig.h"'),
                          (game / "script_game_object_script.cpp", '#include "../xrCore/SpawnPreparationConfig.h"')]:
        source = path.read_bytes()
        newline = b"\r\n" if b"\r\n" in source else b"\n"
        if path.parent == core:
            path.write_bytes(include.encode() + newline + source)
        else:
            edit(path, '#include "SpawnVoiceApply.inc"', include + '\n#include "SpawnVoiceApply.inc"')
    edit(core / "SpawnVoiceVfs.inc", old_gate, new_gate)
    edit(game / "SpawnVoiceApply.inc", old_gate, new_gate)

    edit(game / "PrepareSpawnVisuals.inc", '''    const char* prepare = std::getenv("IXRAY_SPAWN_PREPARE");
    const bool prepareVoice = prepare && xr_strcmp(prepare, "1") == 0;''',
         "    const bool prepareVoice = SpawnPreparation::Requested();")
    edit(game / "Level_network_start_client.cpp", '#include "PrepareSpawnVisuals.inc"',
         '#include "../xrCore/SpawnPreparationConfig.h"\n#include "PrepareSpawnVisuals.inc"')

    scope = game / "SpawnVoiceScope.h"
    edit(scope, '''public:
    using Source = std::shared_ptr<const void>(*)(const void*);

private:
''', '''private:
''')
    edit(scope, '''    const void* context_;
    Source source_;''', '''    const std::shared_ptr<const void> prepared_;''')
    edit(scope, '''    Scope(const void* owner, const void* context, Source source)
        : previous_(current_), owner_(owner), context_(context), source_(source)''',
         '''    Scope(const void* owner, std::shared_ptr<const void> prepared)
        : previous_(current_), owner_(owner), prepared_(std::move(prepared))''')
    edit(scope, '''        if (!owner || !current_ || current_->owner_ != owner || !current_->source_)
            return {};
        return current_->source_(current_->context_);''',
         '''        return owner && current_ && current_->owner_ == owner ? current_->prepared_ : nullptr;''')
    edit(scope, "#include <memory>", "#include <memory>\n#include <utility>")
    edit(game / "Level_network_spawn.cpp", '''        const auto voiceSource = [](const void* context) {
            return SpawnPreparation::ActivationScope::PreparedBinder(static_cast<const IPhysicsShellHolder*>(context));
        };
        SpawnVoice::Scope voice(O->cast_game_object(),
            static_cast<const IPhysicsShellHolder*>(alive), voiceSource);''',
         '''        auto* owner = O->cast_game_object();
        const bool prepareVoice = owner && owner->cast_stalker() && IsGameTypeSingle() &&
            OnServer() && !IsDemoPlay() && !IsDemoSave();
        SpawnVoice::Scope voice(owner, prepareVoice ? FS.acquire_spawn_voice_catalogue() : nullptr);''')
    edit(game / "Level.cpp", '''        spawnActivationWork = SpawnPreparation::StartActivationWork(ObjectSpace.GetStaticModel(),
            FS.acquire_spawn_voice_catalogue());''',
         '''        spawnActivationWork = SpawnPreparation::StartActivationWork(ObjectSpace.GetStaticModel());''')

    header = physics / "SpawnActivationWork.h"
    edit(header, "#include <memory>\n\n", "")
    edit(header, '''XRPHYSICS_API ActivationWork* StartActivationWork(const CDB::MODEL* model,
    std::shared_ptr<const void> binder = {});''',
         "XRPHYSICS_API ActivationWork* StartActivationWork(const CDB::MODEL* model);")
    edit(header, "    static std::shared_ptr<const void> PreparedBinder(const IPhysicsShellHolder* owner);\n", "")
    geometry = physics / "ActivationGeometry.inc"
    edit(geometry, '#include "SpawnPreparationQueue.h"',
         '#include "../xrCore/SpawnPreparationConfig.h"\n#include "SpawnPreparationQueue.h"')
    edit(geometry, "    const std::shared_ptr<const void> binder;\n", "")
    edit(geometry, '''    ActivationWork(const CDB::MODEL* source, float queryExpansion, std::shared_ptr<const void> preparedBinder)
        : model(source), expansion(queryExpansion), binder(std::move(preparedBinder)), queue(&Prepare) {}''',
         '''    ActivationWork(const CDB::MODEL* source, float queryExpansion)
        : model(source), expansion(queryExpansion), queue(&Prepare) {}''')
    edit(geometry, '''ActivationWork* StartActivationWork(const CDB::MODEL* model,
    std::shared_ptr<const void> binder)''',
         "ActivationWork* StartActivationWork(const CDB::MODEL* model)")
    edit(geometry, '''    const char* setting = std::getenv("IXRAY_SPAWN_PREPARE");
    if (model && setting && xr_strcmp(setting, "1") == 0)''',
         "    if (model && Requested())")
    edit(geometry, "ph_console::ph_tri_query_ex_aabb_rate, std::move(binder)",
         "ph_console::ph_tri_query_ex_aabb_rate")
    edit(geometry, '''std::shared_ptr<const void> ActivationScope::PreparedBinder(const IPhysicsShellHolder* owner)
{
    auto* scope = currentActivation;
    if (!scope || !scope->work_ || !owner || scope->owner_ != owner)
        return {};
    return scope->work_->binder;
}

''', "")

    fixture = root / "ixray_spawn_mainline_replay.cpp"
    edit(fixture, '''        const auto plan = admittedPlan;
        const auto source = [](const void* context) -> std::shared_ptr<const void>
        {
            return *static_cast<const std::shared_ptr<const SpawnVoice::Catalogue>*>(context);
        };
        SpawnVoice::Scope scope(lua_toboolean(L, 3) ? nullptr : &actor->object(), &plan, source);''',
         '''        SpawnVoice::Scope scope(lua_toboolean(L, 3) ? nullptr : &actor->object(), admittedPlan);''')
    edit(fixture, '''    Require(argc == 5, "stock, previous, candidate and replay input");''',
         '''    const auto* enabled = std::getenv("IXRAY_SPAWN_PREPARE");
    Require(!enabled, "test the normal launcher with no experimental environment variable");
    Require(argc == 5, "stock, previous, candidate and replay input");''')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    patch(parser.parse_args().engine)
