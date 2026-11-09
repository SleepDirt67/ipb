"""Exercise stock voice registration and real resource IO on the same nine-root cohort."""
import argparse
from pathlib import Path
import shutil


def replace(data, before, after):
    if data.count(before) != 1:
        raise ValueError((before, data.count(before)))
    return data.replace(before, after, 1)


def patch(root):
    folder = Path(__file__).resolve().parent
    target = root / "ixray_spawn_mainline_replay.cpp"
    source = target.read_text(encoding="utf-8")
    source = replace(source, "#include <vector>", '''#include <vector>
#include <map>
#include <unordered_set>

static bool cohortMode = false;
static unsigned cohortApplied = 0;
unsigned ResolveCohortSound(const char* prefix, const char* name, unsigned maximum);''')
    for name in ("add_sound", "add_combat_sound"):
        pattern = f"    unsigned {name}(const char*, unsigned,"
        source = replace(source, pattern, f"    unsigned {name}(const char* name, unsigned maximum,")
        start = source.index(f"    unsigned {name}(")
        body = source.index("        ++registrations;", start) + len("        ++registrations;")
        source = source[:body] + '''
        if (cohortMode)
            return ResolveCohortSound(prefix_.c_str(), name, maximum);''' + source[body:]
    source = replace(source, "        code = lua_pcall(L, 1, 0, 0);",
                     "        code = lua_pcall(L, 1, 0, 0);\n        cohortApplied += scope.Registrations();")
    source = replace(source, "int main(int argc, char** argv)\n{",
                     '''#include "CohortResourceReplay.inc"

int main(int argc, char** argv)
{
    if (argc == 6 && std::string_view(argv[1]) == "--cohort")
    {
        cohortMode = true;
        return RunCohort(argv[2], argv[3], argv[4], argv[5]);
    }''')
    target.write_text(source, encoding="utf-8")
    shutil.copyfile(folder / "CohortResourceReplay.inc", root / "CohortResourceReplay.inc")
    original = (root / "src/xrGame/sound_player.cpp").read_text(encoding="utf-8")
    start = original.index("CSoundPlayer::CSoundCollection::CSoundCollection")
    end = original.index("CSoundPlayer::CSoundCollection::~CSoundCollection", start)
    data = original[start:end]
    data = data.replace("CSoundPlayer::CSoundCollection::CSoundCollection", "ReplayCollection::ReplayCollection")
    data = data.replace("const CSoundCollectionParams &params", "const CohortSoundParams &params")
    data = data.replace("    PacingDiag::SpawnSpan spawnPath(PacingDiag::Kind::BinderSoundCollection);\n", "")
    (root / "CohortCollectionUnderTest.inc").write_text(data, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    patch(parser.parse_args().engine)
