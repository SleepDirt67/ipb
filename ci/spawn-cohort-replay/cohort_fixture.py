"""Generate a repeatable spawn-resource cohort from the stock voice list."""
import argparse
from pathlib import Path
import json


def stock_themes(root):
    sections = {}

    def read(path):
        current = None
        for raw in path.read_bytes().decode("latin-1").splitlines():
            line = raw.partition(";")[0].strip()
            if line.startswith("#include"):
                read(path.with_name(line.split('"')[1]))
            elif line.startswith("["):
                name, parents = line[1:].split("]", 1)
                current = sections.setdefault(name, ([item.strip() for item in parents.lstrip(" :").split(",") if item.strip()], {}))
            elif line and not line.startswith("#") and current:
                key, _, value = line.partition("=")
                current[1][key.strip()] = value.strip()

    def section(name):
        parents, values = sections[name]
        return {**{key: value for parent in parents for key, value in section(parent).items()}, **values}

    read(root / "gamedata/configs/misc/script_sound.ltx")
    for name in sorted(section("list")):
        data = section(name)
        if data.get("type") == "npc":
            yield name, data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    output = []
    files = set()
    for i, (name, data) in enumerate(stock_themes(args.engine)):
        # Real theme count, shared paths and prefix policy. Use representative
        # archive resources and stable case rather than original game assets.
        path = data["path"].lower()
        local = data.get("npc_prefix", "false") == "true"
        combat = data.get("is_combat_sound", "false") == "true"
        output.append("{%s,%s,%s,%s}" % (json.dumps(name), json.dumps(path),
                                         str(local).lower(), str(combat).lower()))
        prefixes = [f"characters_voice\\cohort_{n}\\" for n in range(5)] if local else ["characters_voice\\"]
        for prefix in prefixes:
            for suffix in ("1", "2", "3"):
                files.add(prefix + path + suffix + ".ogg")
    for i in range(29):
        files.add(f"fixture_item_{i}.dat")
    assert len(output) == 569, len(output)
    (args.output / "themes.lua").write_text("return {\n" + ",\n".join(output) + "\n}\n", encoding="ascii")
    (args.output / "files.txt").write_text("\n".join(sorted(files)) + "\n", encoding="ascii")
    print(f"Generated {len(output)} stock voice themes and {len(files)} archive assets.")


if __name__ == "__main__":
    main()
