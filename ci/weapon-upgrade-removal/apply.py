"""Apply the weapon upgrade removal extension to the pinned CoP source."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
GAME = Path('src/xrGame')


def apply(root):
    edits = {}

    def edit(name, before, after):
        path = root / GAME / name
        raw = path.read_bytes()
        newline = b'\r\n' if b'\r\n' in raw else b'\n'
        source = edits.get(path, (raw.replace(b'\r\n', b'\n'), newline))[0]
        anchor = before.encode()
        if source.count(anchor) != 1:
            raise ValueError(f'{name}: anchor count {source.count(anchor)} for {before!r}')
        edits[path] = (source.replace(anchor, after.encode(), 1), newline)

    edit('Weapon.h', '\tu8\t\tGetAddonsState',
         '\tbool RemoveInstalledUpgrade(const shared_str& upgrade_id);\n'
         '\tu8\t\tGetAddonsState')
    edit('Weapon.h', '\tu8 m_LastShotAmmoType = undefined_ammo_type;',
         '\tbool m_saving_upgrade_removal = false;\n'
         '\ts8 m_upgrade_removal_first_mode = 1;\n'
         '\tu8 m_LastShotAmmoType = undefined_ammo_type;')
    edit('inventory_item_upgrade.cpp', '#include "WeaponMagazinedWGrenade.h"',
         '#include "WeaponMagazinedWGrenade.h"\n'
         '#include "Actor.h"\n#include "alife_object_registry.h"\n'
         '#include "inventory_upgrade_group.h"\n#include "saved_game_wrapper.h"\n'
         '#include "xrServer_Objects_ALife_Items.h"\n'
         '#include "../xrEngine/XR_IOConsole.h"\n#include "../xrScripts/script_engine.h"\n\n'
         + (HERE / 'weapon_upgrade_removal.inc').read_text())
    edit('Weapon.cpp', 'void CWeapon::save(NET_Packet &output_packet)\n{',
         'void CWeapon::save(NET_Packet &output_packet)\n{\n'
         '\tconst auto scope = m_saving_upgrade_removal ? decltype(m_cur_scope){} : m_cur_scope;\n'
         '\tconst auto ammo = m_saving_upgrade_removal ? decltype(m_ammoType){} : m_ammoType;\n'
         '\tconst auto chamber = m_saving_upgrade_removal ? decltype(m_ChamberAmmoType){} : m_ChamberAmmoType;\n'
         '\tconst auto last_shot = m_saving_upgrade_removal ? static_cast<u8>(undefined_ammo_type) : m_LastShotAmmoType;')
    for member, saved in (('m_cur_scope', 'scope'), ('m_ammoType', 'ammo'),
                          ('m_ChamberAmmoType', 'chamber'), ('m_LastShotAmmoType', 'last_shot')):
        edit('Weapon.cpp', f'save_data\t\t({member},', f'save_data\t\t({saved},')
    edit('WeaponMagazined.cpp', 'save_data\t\t(m_iQueueSize, output_packet);\n'
         '\tsave_data\t\t(m_iShotNum, output_packet);\n\tsave_data\t\t(m_iCurFireMode, output_packet);',
         'const auto queue = m_saving_upgrade_removal ? m_upgrade_removal_first_mode : m_iQueueSize;\n'
         '\tconst auto mode = m_saving_upgrade_removal ? decltype(m_iCurFireMode){} : m_iCurFireMode;\n'
         '\tsave_data(queue, output_packet);\n\tsave_data(m_iShotNum, output_packet);\n'
         '\tsave_data(mode, output_packet);')
    edit('WeaponMagazinedWGrenade.cpp', 'save_data(m_ammoType2, output_packet);',
         'const auto grenade = m_saving_upgrade_removal ? decltype(m_ammoType2){} : m_ammoType2;\n'
         '\tsave_data(grenade, output_packet);')
    edit('ui/UIInventoryUpgradeWnd.h', 'void AskUsing(LPCSTR text, LPCSTR upgrade_name);',
         'void AskUsing(LPCSTR text, LPCSTR upgrade_name);\n\tvoid AskRemove(LPCSTR upgrade_name);')
    edit('ui/UIInventoryUpgradeWnd.h', 'LPCSTR m_cur_upgrade_id;',
         'LPCSTR m_cur_upgrade_id = nullptr;\n\tu16 m_remove_upgrade_item = u16(-1);')
    edit('ui/UIInventoryUpgradeWnd.cpp', 'm_inv_item = static_cast<PIItem>',
         'm_remove_upgrade_item = u16(-1);\n\tm_inv_item = static_cast<PIItem>')
    edit('ui/UIInventoryUpgradeWnd.cpp', 'm_cur_upgrade_id = upgrade_name;',
         'm_remove_upgrade_item = u16(-1);\n\tm_cur_upgrade_id = upgrade_name;')
    edit('ui/UIInventoryUpgradeWnd.cpp', 'void CUIInventoryUpgradeWnd::OnMesBoxYes()\n{',
         '''void CUIInventoryUpgradeWnd::AskRemove(LPCSTR upgrade_name)
{
    if (!IsGameTypeSingle() || !m_inv_item || !m_inv_item->cast_weapon() ||
        !m_inv_item->has_upgrade(upgrade_name))
        return;

    if (auto* parent = smart_cast<CUIActorMenu*>(m_pParentWnd))
    {
        m_cur_upgrade_id = upgrade_name;
        m_remove_upgrade_item = m_inv_item->object_id();
        parent->CallMessageBoxYesNo("st_ixray_remove_weapon_upgrade_confirm");
    }
}

void CUIInventoryUpgradeWnd::OnMesBoxYes()
{
    if (m_remove_upgrade_item != u16(-1))
    {
        const u16 item = m_remove_upgrade_item;
        m_remove_upgrade_item = u16(-1);
        if (m_inv_item && m_inv_item->object_id() == item)
        {
            auto* weapon = m_inv_item->cast_weapon();
            if (weapon && !weapon->RemoveInstalledUpgrade(shared_str(m_cur_upgrade_id)))
                if (auto* parent = smart_cast<CUIActorMenu*>(m_pParentWnd))
                    parent->CallMessageBoxOK("st_ixray_remove_weapon_upgrade_failed");
        }
        return;
    }''')
    edit('ui/UIInvUpgrade.cpp', 'void UIUpgrade::OnRClick()\n{',
         'void UIUpgrade::OnRClick()\n{\n'
         '\tif (m_state == STATE_SELECTED && get_upgrade())\n'
         '\t\tm_parent_wnd->AskRemove(get_upgrade()->id_str());')
    for path, (data, newline) in edits.items():
        path.write_bytes(data.replace(b'\n', newline))
    print(f'Weapon upgrade removal applied to {len(edits)} source files')


if __name__ == '__main__':
    apply(Path(sys.argv[1]))
