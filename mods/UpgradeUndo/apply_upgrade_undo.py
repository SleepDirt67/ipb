#!/usr/bin/env python3
"""Apply the IX-Ray r1.3.6 CoP upgrade-undo candidate to source checkout."""
from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, path: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f'{path}: expected exactly one match, got {count}: {old[:100]!r}')
    return source.replace(old, new, 1)


def apply(root: Path) -> None:
    replacements = {}

    path = 'src/xrGame/inventory_item.h'
    replacements[path] = [
        ('\tvoid\tadd_upgrade\t\t\t\t\t( const shared_str& upgrade_id, bool loading );',
         '\tvoid\tadd_upgrade\t\t\t\t\t( const shared_str& upgrade_id, bool loading );\n'
         '\tbool\tundo_upgrade\t\t\t\t\t( const shared_str& upgrade_id );\n'
         '\tbool\tupgrade_undo_needs_reload\t\t() const { return m_upgrade_undo_needs_reload; }'),
        ('\tUpgrades_type\tm_upgrades;',
         '\tUpgrades_type\tm_upgrades;\n'
         '\tbool\tm_upgrade_undo_needs_reload = false;'),
    ]

    path = 'src/xrGame/inventory_item_upgrade.cpp'
    replacements[path] = [
        ('#include "inventory_upgrade.h"',
         '#include "inventory_upgrade.h"\n#include "inventory_upgrade_group.h"\n#include "CustomOutfit.h"\n#include "ActorHelmet.h"\n#include "xrServer_Objects_ALife_Items.h"'),
        ('bool CInventoryItem::get_upgrades_str(string2048& res) const', r'''// Upgrade Undo: drop one modification and any orphaned dependent stages.
// Outfit/helmet stats recompute now; weapon stats recompute on save/reload.
bool CInventoryItem::undo_upgrade(const shared_str& upgrade_id)
{
    if (!IsGameTypeSingleCompatible() || !ai().get_alife() || m_upgrade_undo_needs_reload)
        return false;
    if (!cast_outfit() && !cast_helmet() && !cast_weapon())
        return false;
    if (std::find(m_upgrades.begin(), m_upgrades.end(), upgrade_id) == m_upgrades.end())
        return false;

    // Built-in modifications of unique items are not removable.
    LPCSTR defaults = READ_IF_EXISTS(pSettings, r_string, m_section_id.c_str(), "installed_upgrades", "");
    if (defaults)
    {
        string512 one = {};
        for (int i = 0, n = _GetItemCount(defaults); i < n; ++i)
        {
            _GetItem(defaults, i, one, sizeof(one));
            if (xr_strcmp(upgrade_id.c_str(), one) == 0)
                return false;
        }
    }

    CSE_ALifeDynamicObject* server_object = ai().alife().objects().object((ALife::_OBJECT_ID)object_id(), true);
    CSE_ALifeInventoryItem* server_item = smart_cast<CSE_ALifeInventoryItem*>(server_object);
    if (!server_item)
        return false;

    inventory::upgrade::Manager* manager = Level().m_upgrade_manager;
    if (!manager || !manager->get_upgrade(upgrade_id))
        return false;

    const Upgrades_type original = m_upgrades;
    auto selected = std::find(m_upgrades.begin(), m_upgrades.end(), upgrade_id);
    m_upgrades.erase(selected);

    bool changed;
    do
    {
        changed = false;
        for (auto it = m_upgrades.begin(); it != m_upgrades.end(); ++it)
        {
            inventory::upgrade::Upgrade* upgrade = manager->get_upgrade(*it);
            // Group::can_install is non-const in the upstream API although
            // this query does not mutate the group.
            if (!upgrade || const_cast<inventory::upgrade::Group*>(upgrade->parent_group())->can_install(
                *this, *upgrade, false) == inventory::upgrade::result_e_parents)
            {
                m_upgrades.erase(it);
                changed = true;
                break;
            }
        }
    } while (changed);

    const Upgrades_type remaining = m_upgrades;

    // Weapon Load() overwrites a live magazine/chamber/addon state.
    // Update the serialized upgrade list; save & reload to rebuild stats.
    if (cast_weapon())
    {
        server_item->m_upgrades = remaining;
        m_upgrade_undo_needs_reload = true;
        return true;
    }

    m_upgrades.clear();
    const float old_condition = GetCondition();
    Load(m_section_id.c_str());
    if (CCustomOutfit* outfit = cast_outfit())
        outfit->ReloadBonesProtection();
    if (CHelmet* helmet = cast_helmet())
        helmet->ReloadBonesProtection();

    for (const shared_str& kept : remaining)
    {
        if (!manager->upgrade_install(*this, kept, true))
        {
            m_upgrades.clear();
            Load(m_section_id.c_str());
            if (CCustomOutfit* outfit = cast_outfit())
                outfit->ReloadBonesProtection();
            if (CHelmet* helmet = cast_helmet())
                helmet->ReloadBonesProtection();
            for (const shared_str& previous : original)
                manager->upgrade_install(*this, previous, true);
            SetCondition(old_condition);
            return false;
        }
    }
    SetCondition(old_condition);
    server_item->m_upgrades = remaining;
    return true;
}

bool CInventoryItem::get_upgrades_str(string2048& res) const'''),
    ]

    path = 'src/xrGame/inventory_upgrade.cpp'
    replacements[path] = [
        ('UpgradeStateResult Upgrade::can_install(CInventoryItem& item, bool loading)\n{',
         'UpgradeStateResult Upgrade::can_install(CInventoryItem& item, bool loading)\n{\n'
         '\tif (!loading && item.upgrade_undo_needs_reload())\n'
         '\t\treturn result_e_cant_do;'),
    ]

    path = 'src/xrGame/ui/UIInventoryUpgradeWnd.h'
    replacements[path] = [
        ('\tvoid AskUsing(LPCSTR text, LPCSTR upgrade_name);',
         '\tvoid AskUsing(LPCSTR text, LPCSTR upgrade_name);\n\tvoid AskUndo(LPCSTR upgrade_name);'),
        ('\tLPCSTR m_cur_upgrade_id;',
         '\tLPCSTR m_cur_upgrade_id = nullptr;\n\tbool m_pending_upgrade_undo = false;'),
    ]

    path = 'src/xrGame/ui/UIInventoryUpgradeWnd.cpp'
    replacements[path] = [
        ('\tm_cur_upgrade_id = upgrade_name;\n\n\tCUIActorMenu* parent_wnd',
         '\tm_cur_upgrade_id = upgrade_name;\n\tm_pending_upgrade_undo = false;\n\n\tCUIActorMenu* parent_wnd'),
        ('void CUIInventoryUpgradeWnd::OnMesBoxYes()\n{', r'''void CUIInventoryUpgradeWnd::AskUndo(LPCSTR upgrade_name)
{
    if (!m_inv_item || !upgrade_name || !m_pParentWnd || !ai().get_alife())
        return;
    if (m_inv_item->upgrade_undo_needs_reload() || !m_inv_item->has_upgrade(upgrade_name))
        return;

    m_cur_upgrade_id = upgrade_name;
    m_pending_upgrade_undo = true;
    if (CUIActorMenu* parent = smart_cast<CUIActorMenu*>(m_pParentWnd))
        parent->CallMessageBoxYesNo("Undo this upgrade and dependent upgrades? No money refund.");
}

void CUIInventoryUpgradeWnd::OnMesBoxYes()
{
    if (m_pending_upgrade_undo)
    {
        m_pending_upgrade_undo = false;
        if (m_inv_item && m_inv_item->undo_upgrade(m_cur_upgrade_id))
        {
            if (CUIActorMenu* parent = smart_cast<CUIActorMenu*>(m_pParentWnd))
            {
                parent->UpdateActor();
                parent->SeparateUpgradeItem();
                if (m_inv_item->upgrade_undo_needs_reload())
                    parent->CallMessageBoxOK("Weapon upgrade removed from save state. Save and reload the game before any further upgrades to this weapon.");
            }
        }
        UpdateAllUpgrades();
        return;
    }'''),
    ]

    path = 'src/xrGame/ui/UIInvUpgrade.cpp'
    replacements[path] = [
        ('void UIUpgrade::OnRClick()\n{\n\tm_parent_wnd->set_info_cur_upgrade(nullptr);',
         'void UIUpgrade::OnRClick()\n{\n'
         '\tif (m_state == STATE_SELECTED)\n'
         '\t\tm_parent_wnd->AskUndo(get_upgrade()->id_str());\n'
         '\tm_parent_wnd->set_info_cur_upgrade(nullptr);'),
    ]

    patches = {}
    for name, edits in replacements.items():
        file = root / name
        if not file.is_file():
            raise RuntimeError(f'Missing source file: {file}')
        old = file.read_bytes()
        newline = '\r\n' if b'\r\n' in old else '\n'
        text = old.decode('utf-8-sig').replace('\r\n', '\n')
        modified = text
        for before, after in edits:
            modified = replace_once(modified, before, after, name)
        patches[file] = modified.replace('\n', newline).encode('utf-8')

    for path, data in patches.items():
        path.write_bytes(data)
    print('Applied upgrade undo patch to', len(patches), 'IX-Ray r1.3.6 files')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python apply_upgrade_undo.py <ixray-r1.3.6-source-path>')
    apply(Path(sys.argv[1]))
