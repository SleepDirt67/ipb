"""Separate the activation solver list from the materialized world freeze."""
from pathlib import Path
import sys

src = Path(sys.argv[1]) / "src"

def edit(name, replacements):
    path = src / name
    original = path.read_bytes()
    crlf = b"\r\n" in original and b"\n" not in original.replace(b"\r\n", b"")
    source = original.replace(b"\r\n", b"\n").decode("latin-1")
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError((name, before, source.count(before)))
        source = source.replace(before, after, 1)
    path.write_bytes(source.replace("\n", "\r\n" if crlf else "\n").encode("latin-1"))

edit("xrPhysics/IPHWorld.h", [
    ('class IPHWorld:\n', '''// Optional step interface. The original callback vtable stays unchanged.
class IActivationWorldStep
{
public:
    virtual void UpdateActivationStep(void (*materialize)(void*), void* context) = 0;
protected:
    virtual ~IActivationWorldStep() = default;
};

class IPHWorld:
'''),
])
edit("xrGame/PHCommander.h", [
    ('public IPHWorldUpdateCallbck\n', 'public IPHWorldUpdateCallbck, public IActivationWorldStep\n'),
    ('private:\n\tvirtual\tvoid\t\tupdate_step', '''private:
    void UpdateActivationStep(void (*materialize)(void*), void* context) override;
\tvirtual\tvoid\t\tupdate_step'''),
])
edit("xrGame/PHCommander.cpp", [
    ('void CPHCommander::update\t()', '''void CPHCommander::UpdateActivationStep(void (*materialize)(void*), void* context)
{
    xrCriticalSectionGuard guard(&lock);
    if (m_calls.empty())
        return;
    materialize(context);
    update();
}

void CPHCommander::update\t()'''),
])
edit("xrPhysics/PHCharacter.h", [
    ('\tvirtual void\t\tFreezeContent', '''    // The ODE body enable bit must survive a skipped freeze/unfreeze round trip.
    bool ActivationFreezeIsReversible() const { return m_body && dBodyIsEnabled(m_body); }
\tvirtual void\t\tFreezeContent'''),
])
edit("xrPhysics/PHShell.h", [
    ('\tvirtual\t\tvoid\t\t\t\tvis_update_activate', '''    // At a positive count unfreeze can notify the game object.
    bool ActivationFreezeIsReversible() const { return m_active_count <= 0; }
\tvirtual\t\tvoid\t\t\t\tvis_update_activate'''),
])
edit("xrPhysics/PHWorld.h", [
    ('\tbool\t\t\t\t\t\tb_world_freezed;', '''\tbool\t\t\t\t\t\tb_world_freezed;
    IActivationWorldStep* m_deferred_activation_step = nullptr;'''),
    ('\tvoid \t\t\t\t\t\tFreeze', '''    bool DeferFreezeForActivation();
    void MaterializeActivationFreeze();
    bool ActivationFreezeDeferred() const { return m_deferred_activation_step != nullptr; }
\tvoid \t\t\t\t\t\tFreeze'''),
])
edit("xrPhysics/PHWorld.cpp", [
    ('#include "PHWorld.h"', '''#include "PHWorld.h"
#include "PHCharacter.h"
#include "PHShell.h"
#include "../xrEngine/PacingDiagnostics.h"
#include <cstdlib>'''),
    ('\tif(disable_count==0)\n\t{', '''\tif(disable_count==0)
\t{
        if (m_recently_disabled_objects.count())
            MaterializeActivationFreeze();'''),
    ('\tm_update_callback->update_step();', '''    if (auto* deferred = m_deferred_activation_step)
        deferred->UpdateActivationStep([](void* context) {
            static_cast<CPHWorld*>(context)->MaterializeActivationFreeze();
        }, this);
    else
        m_update_callback->update_step();'''),
    ('void CPHWorld::Freeze()\n{', '''bool CPHWorld::DeferFreezeForActivation()
{
    static const bool enabled = [] {
        const char* value = std::getenv("IXRAY_SPAWN_ACTIVATION_FREEZE");
        return value && xr_strcmp(value, "1") == 0;
    }();
    if (!enabled || IsFreezed() || Processing() || m_freezed_objects.count() ||
        m_freezed_update_objects.count())
        return false;

    auto* step = dynamic_cast<IActivationWorldStep*>(m_update_callback);
    if (!step)
        return false;

    for (CPHObject* object : m_objects)
    {
        if (const auto* character = dynamic_cast<const CPHCharacter*>(object)) {
            if (!character->ActivationFreezeIsReversible())
                return false;
        } else if (const auto* shell = dynamic_cast<const CPHShell*>(object)) {
            if (!shell->ActivationFreezeIsReversible())
                return false;
        } else {
            return false;
        }
    }

    PacingDiag::SpawnSpan isolate(PacingDiag::Kind::SpawnActivationIsolate, m_objects.count());
    m_freezed_objects.move_items(m_objects);
    m_freezed_update_objects.move_items(m_update_objects);
    b_world_freezed = true;
    m_deferred_activation_step = step;
    return true;
}

void CPHWorld::MaterializeActivationFreeze()
{
    if (!m_deferred_activation_step)
        return;
    PacingDiag::SpawnSpan materialize(PacingDiag::Kind::SpawnActivationMaterialize, m_freezed_objects.count());
    m_deferred_activation_step = nullptr;
    for (CPHObject* object : m_freezed_objects)
        object->FreezeContent();
}

void CPHWorld::Freeze()
{'''),
    ('''\tfor (CPHObject* Obj : m_freezed_objects)
\t\tObj->UnFreezeContent();

\tm_objects.move_items(m_freezed_objects);''', '''    if (m_deferred_activation_step) {
        m_deferred_activation_step = nullptr;
    } else {
        for (CPHObject* Obj : m_freezed_objects)
            Obj->UnFreezeContent();
    }

\tm_objects.move_items(m_freezed_objects);'''),
])
edit("xrPhysics/PHObject.cpp", [
    ('''\t\tif (CPHCollideValidator::DoCollide(*this, *obj2)) NearCallback(this, obj2, dSpacedGeom(), obj2->dSpacedGeom());''',
     '''        if (CPHCollideValidator::DoCollide(*this, *obj2))
        {
            if (ph_world->ActivationFreezeDeferred())
                ph_world->MaterializeActivationFreeze();
            NearCallback(this, obj2, dSpacedGeom(), obj2->dSpacedGeom());
        }'''),
])
edit("xrPhysics/PHActivationShape.h", [
    ('bool\tun_freeze_later\t=false)', 'bool\tun_freeze_later\t=false, bool local_world=false)'),
])
edit("xrPhysics/PHActivationShape.cpp", [
    ('bool\tun_freeze_later/*\t=false*/)','bool\tun_freeze_later/*\t=false*/, bool local_world)'),
    ('''\tCPHObject::activate();
\tph_world->Freeze();
\tUnFreeze();''', '''    if (local_world && !un_freeze_later && ph_world->DeferFreezeForActivation()) {
        CPHObject::activate();
    } else {
        CPHObject::activate();
        ph_world->Freeze();
        UnFreeze();
    }'''),
])
edit("xrEngine/PacingDiagnostics.h", [
    ("SpawnSweepQuanta", "SpawnSweepQuanta, SpawnActivationIsolate, SpawnActivationMaterialize, SpawnActivationFull"),
])
edit("xrPhysics/IActivationShape.cpp", [
    ('#include "SpawnActivationContacts.h"', '#include "SpawnActivationContacts.h"\n#include "../xrEngine/PacingDiagnostics.h"'),
    ('PROF_EVENT("ActivateShapeCharacterPhysicsSupport")',
     'PROF_EVENT("ActivateShapeCharacterPhysicsSupport")\n    PacingDiag::SpawnSpan fullActivation(PacingDiag::Kind::SpawnActivationFull);'),
    ('SpawnCollision::Scope contacts(activation_shape.ODEBody());\n\tbool ret = activation_shape.Activate(vbox,1,1.f,M_PI/8.f);',
     'SpawnCollision::Scope contacts(activation_shape.ODEBody());\n\tbool ret = activation_shape.Activate(vbox,1,1.f,M_PI/8.f, false, true);'),
])
