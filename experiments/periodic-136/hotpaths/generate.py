"""Compile the old and new engine functions into the same differential fixture."""
from pathlib import Path
import subprocess
import sys

engine, output = map(Path, sys.argv[1:])


def functions(relative, start, end, signature):
    old = subprocess.check_output(["git", "-C", str(engine), "show", f"HEAD:{relative}"]).decode("utf-8")
    new = (engine / relative).read_text(encoding="utf-8")
    for source, suffix in ((old, "Old"), (new, "")):
        begin = source.index(start)
        finish = source.index(end, begin)
        yield source[begin:finish].replace(signature, signature + suffix, 1)


graph = functions("src/xrEngine/AI/level_graph.cpp", "bool ILevelGraph::Search(",
                  "u32 ILevelGraph::SearchNearestVertex", "ILevelGraph::Search")
sound = functions("src/xrSound/SoundRender_Core_SourceManager.cpp", "CSoundRender_Source*\tCSoundRender_Core::i_create_source",
                  "void\t\t", "CSoundRender_Core::i_create_source")
refresh = functions("src/xrSound/SoundRender_Core.cpp", "void\t\t\t\t\t\tCSoundRender_Core::refresh_sources()",
                    "void CSoundRender_Core::set_environment_size", "CSoundRender_Core::refresh_sources")
output.write_text("".join((*graph, *sound, *refresh)), encoding="utf-8")
