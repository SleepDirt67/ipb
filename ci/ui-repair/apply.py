"""Restore the monster name in the existing loot card on the pinned IX-Ray base."""
import argparse
import hashlib
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


ASSETS = {
    "ui_flags.dds": "8d0b6df4691dd20966d96b597c07eb2576873202",
    "ui_ix-ray_team_logo.dds": "323589834fa62bbce679ccecdee6e1c6748d0aea",
    "ui_ixray_ex.dds": "a217e5e1547dbab31a4a6cdb6c80a2525958de7a",
    "ui_ixray_mutant_portrets.dds": "3e6953075f2c2c17243f4c07d058f233efc911a8",
}
RUSSIAN_NAMES = {
    "SM_BLOOD": "Кровосос",
    "SM_BOARW": "Кабан",
    "SM_DOG_S": "Слепая собака",
    "SM_FLESH": "Плоть",
    "SM_P_DOG": "Псевдособака",
    "SM_BURER": "Бюрер",
    "SM_CAT_S": "Кошка",
    "SM_CHIMS": "Химера",
    "SM_CONTR": "Контролёр",
    "SM_IZLOM": "Излом",
    "SM_POLTR": "Полтергейст",
    "SM_GIANT": "Псевдогигант",
    "SM_ZOMBI": "Зомби",
    "SM_SNORK": "Снорк",
    "SM_TUSHK": "Тушканчик",
    "SM_DOG_P": "Пси-собака",
    "SM_DOG_F": "Пси-собака (фантом)",
}
SOURCE = '				m_PartnerCharacterInfo->InitCharacter("", icon);'
PATCH = '''				string16 classId;
				CLSID2TEXT(pMonster->CLS_ID, classId);
				if (char* padding = strchr(classId, ' '))
					*padding = 0;

				string64 lootNameId;
				xr_strconcat(lootNameId, "st_ixray_loot_", classId);

				LPCSTR nameId = "monster";
				if (xr_strcmp(g_pStringTable->translate(lootNameId).c_str(), lootNameId) != 0)
					nameId = lootNameId;
				else if (xr_strcmp(g_pStringTable->translate(classId).c_str(), classId) != 0)
					nameId = classId;

				m_PartnerCharacterInfo->InitCharacter(nameId, icon);'''


def patch_source(tree):
    path = tree / "src/xrGame/ui/UIActorMenu.cpp"
    data = path.read_bytes()
    old = SOURCE.encode()
    if data.count(old) != 1:
        raise ValueError("Expected a single stock monster-card initialization")
    eol = b"\r\n" if b"\r\n" in data else b"\n"
    path.write_bytes(data.replace(old, PATCH.encode().replace(b"\n", eol), 1))


def pack_data(tree, package):
    texture_dir = package / "gamedata/textures/ui"
    texture_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in ASSETS.items():
        source = tree / "gamedata/textures/ui" / name
        data = source.read_bytes()
        blob = f"blob {len(data)}\0".encode() + data
        if not data.startswith(b"DDS ") or hashlib.sha1(blob).hexdigest() != expected:
            raise ValueError(f"Unexpected upstream texture {name}")
        (texture_dir / name).write_bytes(data)

    upstream = ET.parse(tree / "gamedata/configs/text/rus/ui_st_ixray.xml")
    known = {node.attrib["id"] for node in upstream.findall("string")}
    if not RUSSIAN_NAMES.keys() <= known:
        raise ValueError("Unknown stock monster class key")

    strings = ET.Element("string_table")
    for class_id, name in RUSSIAN_NAMES.items():
        entry = ET.SubElement(strings, "string", id="st_ixray_loot_" + class_id)
        ET.SubElement(entry, "text").text = name
    ET.indent(strings, space="    ")
    target = package / "gamedata/configs/text/rus/ui_st_ixray_loot_monsters.xml"
    target.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(strings).write(target, encoding="windows-1251", xml_declaration=True)
    assert ET.parse(target).getroot().findtext("string[@id='st_ixray_loot_SM_BOARW']/text") == "Кабан"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("--package", type=Path)
    args = parser.parse_args()
    if args.package:
        pack_data(args.engine, args.package)
        source = Path("package/bin/xrGame.dll")
        output = args.package / "bin"
        output.mkdir(exist_ok=True)
        shutil.copy2(source, output / source.name)
        shutil.copy2("package/BUILD_MANIFEST.json", args.package / "UI_BUILD_MANIFEST.json")
    else:
        patch_source(args.engine)


if __name__ == "__main__":
    main()
