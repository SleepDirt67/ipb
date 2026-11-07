"""Build a differential fixture from the original and installed C++ function bodies."""
import argparse
from pathlib import Path

from apply import patch

args = argparse.ArgumentParser()
for name in ("engine", "luabind", "output"):
    args.add_argument(name, type=Path)
a = args.parse_args()

files = (
    (a.luabind / "luabind/include/luabind/detail/object_rep.hpp", "inline object_rep* is_class_object"),
    (a.luabind / "luabind/src/class_registry.cpp", "class_registry* class_registry::get_registry"),
    (a.engine / "src/xrGame/sound_player.cpp", "CSoundPlayer::CSoundCollection::CSoundCollection"),
)


def function(path, signature):
    source = path.read_text(encoding="utf-8")
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    for end in range(opening + 1, len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if depth == 0:
            return source[start:end + 1]
    raise ValueError(signature)


def extract():
    return [function(path, signature) for path, signature in files]


old = extract()
patch(a.engine, a.luabind)
new = extract()
new.append(function(a.engine / "src/xrCore/LocatorAPI.cpp", "bool CLocatorAPI::find_numbered_sounds"))
a.output.mkdir(parents=True, exist_ok=True)
for name, functions in (("before", old), ("after", new)):
    functions[1] = functions[1].replace("class_registry::get_registry", f"class_registry::{name}_registry")
    functions[0] = functions[0].replace("is_class_object", f"{name}_class")
    functions[2] = functions[2].replace("CSoundPlayer::CSoundCollection::CSoundCollection",
                                       f"void SoundCollection::{name}_collection")
    (a.output / f"{name}.inc").write_text("\n\n".join(functions) + "\n", encoding="utf-8")
